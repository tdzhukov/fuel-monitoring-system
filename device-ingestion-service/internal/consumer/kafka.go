package consumer

import (
	"context"
	"encoding/json"
	"fuel-monitor/internal/model"
	"fuel-monitor/internal/worker"
	"time"

	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"
	"github.com/segmentio/kafka-go"
	"go.uber.org/zap"
)

var (
	messagesTotal = promauto.NewCounter(prometheus.CounterOpts{
		Name: "kafka_messages_total",
		Help: "Total number of messages consumed from Kafka",
	})
	messagesFailed = promauto.NewCounter(prometheus.CounterOpts{
		Name: "kafka_messages_failed_total",
		Help: "Total number of failed message processing",
	})
	consumerLag = promauto.NewGauge(prometheus.GaugeOpts{
		Name: "kafka_consumer_lag",
		Help: "Current consumer lag",
	})
)

type Config struct {
	Brokers        []string
	Topic          string
	GroupID        string
	MinBytes       int
	MaxBytes       int
	MaxWait        time.Duration
	StartOffset    int64
	SessionTimeout time.Duration
}

type Consumer struct {
	reader *kafka.Reader
	pool   *worker.Pool
	logger *zap.Logger
	config Config
}

func NewConsumer(cfg Config, pool *worker.Pool, logger *zap.Logger) *Consumer {
	reader := kafka.NewReader(kafka.ReaderConfig{
		Brokers:        cfg.Brokers,
		Topic:          cfg.Topic,
		GroupID:        cfg.GroupID,
		MinBytes:       cfg.MinBytes,
		MaxBytes:       cfg.MaxBytes,
		MaxWait:        cfg.MaxWait,
		StartOffset:    cfg.StartOffset,
		SessionTimeout: cfg.SessionTimeout,
	})

	return &Consumer{
		reader: reader,
		pool:   pool,
		logger: logger,
		config: cfg,
	}
}

func (c *Consumer) Start(ctx context.Context) error {
	c.logger.Info("Starting Kafka consumer",
		zap.Strings("brokers", c.config.Brokers),
		zap.String("topic", c.config.Topic),
		zap.String("group_id", c.config.GroupID))

	go func() {
		for {
			select {
			case <-ctx.Done():
				c.logger.Info("Kafka consumer stopping...")
				return
			default:
				msg, err := c.reader.FetchMessage(ctx)
				if err != nil {
					if ctx.Err() != nil {
						return
					}
					c.logger.Error("Failed to fetch message", zap.Error(err))
					time.Sleep(100 * time.Millisecond)
					continue
				}

				messagesTotal.Inc()

				// Парсинг сообщения
				var data model.SensorData
				if err := json.Unmarshal(msg.Value, &data); err != nil {
					messagesFailed.Inc()
					c.logger.Error("Failed to parse message",
						zap.Error(err),
						zap.Int("partition", msg.Partition),
						zap.Int64("offset", msg.Offset))

					if commitErr := c.reader.CommitMessages(ctx, msg); commitErr != nil {
						c.logger.Error("Failed to commit message", zap.Error(commitErr))
					}
					continue
				}

				// Валидация
				if err := data.Validate(); err != nil {
					messagesFailed.Inc()
					c.logger.Warn("Invalid message data",
						zap.Error(err),
						zap.String("vehicle_id", data.VehicleID))

					if commitErr := c.reader.CommitMessages(ctx, msg); commitErr != nil {
						c.logger.Error("Failed to commit message", zap.Error(commitErr))
					}
					continue
				}

				// Отправка в воркер пул
				if ok := c.pool.Submit(data); !ok {
					messagesFailed.Inc()
					c.logger.Warn("Worker pool overloaded, dropping message",
						zap.String("vehicle_id", data.VehicleID))

					if commitErr := c.reader.CommitMessages(ctx, msg); commitErr != nil {
						c.logger.Error("Failed to commit message", zap.Error(commitErr))
					}
					continue
				}

				// Коммит после успешной отправки в пул
				if err := c.reader.CommitMessages(ctx, msg); err != nil {
					c.logger.Error("Failed to commit message", zap.Error(err))
					messagesFailed.Inc()
				}

				stats := c.reader.Stats()
				consumerLag.Set(float64(stats.Lag))
			}
		}
	}()

	return nil
}

func (c *Consumer) Close() error {
	c.logger.Info("Closing Kafka consumer...")
	return c.reader.Close()
}

func (c *Consumer) GetStats() kafka.ReaderStats {
	return c.reader.Stats()
}
