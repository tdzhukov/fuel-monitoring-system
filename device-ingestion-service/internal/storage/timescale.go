package storage

import (
	"context"
	"fuel-monitor/internal/model"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"go.uber.org/zap"
)

type SensorStorage interface {
	SaveBatch(ctx context.Context, data []model.SensorData) error
	Ping(ctx context.Context) error
	Close()
}

type TimescaleStorage struct {
	pool   *pgxpool.Pool
	logger *zap.Logger
}

func NewTimescaleStorage(dsn string, maxConns int32, logger *zap.Logger) (*TimescaleStorage, error) {
	config, err := pgxpool.ParseConfig(dsn)
	if err != nil {
		return nil, err
	}

	config.MaxConns = maxConns
	config.MinConns = 10
	config.MaxConnLifetime = 30 * time.Minute
	config.MaxConnIdleTime = 10 * time.Minute

	pool, err := pgxpool.NewWithConfig(context.Background(), config)
	if err != nil {
		return nil, err
	}

	if err := pool.Ping(context.Background()); err != nil {
		return nil, err
	}

	logger.Info("Connected to TimescaleDB", zap.Int32("max_conns", maxConns))

	return &TimescaleStorage{
		pool:   pool,
		logger: logger,
	}, nil
}

func (s *TimescaleStorage) SaveBatch(ctx context.Context, data []model.SensorData) error {
	if len(data) == 0 {
		return nil
	}

	rows := [][]interface{}{}
	for _, d := range data {
		rows = append(rows, []interface{}{
			d.Timestamp,
			d.VehicleID,
			d.VehicleGPSLatitude,
			d.VehicleGPSLongitude,
			d.FuelConsumptionRate,
		})
	}

	_, err := s.pool.CopyFrom(
		ctx,
		pgx.Identifier{"sensor_data"},
		[]string{"timestamp", "vehicle_id", "latitude", "longitude", "fuel_rate"},
		pgx.CopyFromRows(rows),
	)

	if err != nil {
		s.logger.Error("Failed to save batch", zap.Error(err), zap.Int("batch_size", len(data)))
		return err
	}

	return nil
}

func (s *TimescaleStorage) Ping(ctx context.Context) error {
	return s.pool.Ping(ctx)
}

func (s *TimescaleStorage) Close() {
	s.pool.Close()
	s.logger.Info("TimescaleDB connection pool closed")
}
