package worker

import (
	"context"
	"fuel-monitor/internal/model"
	"fuel-monitor/internal/storage"
	"sync"
	"time"

	"go.uber.org/zap"
)

type Pool struct {
	workerCount int
	jobChan     chan model.SensorData
	wg          sync.WaitGroup
	logger      *zap.Logger
	storage     storage.SensorStorage

	// Batch settings
	batchSize    int
	batchTimeout time.Duration
}

type Config struct {
	WorkerCount  int
	BatchSize    int
	BatchTimeout time.Duration
}

func NewPool(cfg Config, logger *zap.Logger, storage storage.SensorStorage) *Pool {
	return &Pool{
		workerCount:  cfg.WorkerCount,
		jobChan:      make(chan model.SensorData, cfg.WorkerCount*1000),
		logger:       logger,
		storage:      storage,
		batchSize:    cfg.BatchSize,
		batchTimeout: cfg.BatchTimeout,
	}
}

func (p *Pool) Start(ctx context.Context) {
	for i := 0; i < p.workerCount; i++ {
		p.wg.Add(1)
		go p.worker(ctx, i)
	}
	p.logger.Info("Worker pool started",
		zap.Int("workers", p.workerCount),
		zap.Int("batch_size", p.batchSize),
		zap.Duration("batch_timeout", p.batchTimeout))
}

func (p *Pool) Submit(data model.SensorData) bool {
	select {
	case p.jobChan <- data:
		return true
	default:
		return false
	}
}

func (p *Pool) worker(ctx context.Context, id int) {
	defer p.wg.Done()

	buffer := make([]model.SensorData, 0, p.batchSize)
	timer := time.NewTimer(p.batchTimeout)
	defer timer.Stop()

	flush := func() {
		if len(buffer) == 0 {
			return
		}

		start := time.Now()
		if err := p.storage.SaveBatch(ctx, buffer); err == nil {
			p.logger.Debug("Batch saved",
				zap.Int("worker_id", id),
				zap.Int("size", len(buffer)),
				zap.Duration("duration", time.Since(start)))
		}
		buffer = buffer[:0] // Reset buffer
	}

	for {
		select {
		case <-ctx.Done():
			flush()
			return

		case data, ok := <-p.jobChan:
			if !ok {
				flush()
				return
			}

			buffer = append(buffer, data)

			// Flush if batch is full
			if len(buffer) >= p.batchSize {
				flush()
				if !timer.Stop() {
					<-timer.C // Drain channel if timer fired
				}
				timer.Reset(p.batchTimeout)
			}

		case <-timer.C:
			flush()
			timer.Reset(p.batchTimeout)
		}
	}
}

func (p *Pool) Stop() {
	close(p.jobChan)
	p.wg.Wait()
}
