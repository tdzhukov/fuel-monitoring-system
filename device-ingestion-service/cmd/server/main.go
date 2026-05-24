package main

import (
	"context"
	"fuel-monitor/internal/config"
	"fuel-monitor/internal/consumer"
	"fuel-monitor/internal/handler"
	"fuel-monitor/internal/migrate"
	"fuel-monitor/internal/storage"
	"fuel-monitor/internal/worker"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/go-chi/chi/v5/middleware"
	"github.com/prometheus/client_golang/prometheus/promhttp"
	"go.uber.org/zap"
)

func main() {
	logger, _ := zap.NewProduction()
	defer logger.Sync()

	cfg := config.Load()

	// 1. Применяем миграции
	logger.Info("Running database migrations...")
	if err := migrate.Run(cfg.DatabaseDSN, cfg.MigrationsPath, logger); err != nil {
		logger.Fatal("Database migration failed", zap.Error(err))
	}

	// 2. Инициализируем хранилище
	dbStorage, err := storage.NewTimescaleStorage(cfg.DatabaseDSN, cfg.DBMaxConns, logger)
	if err != nil {
		logger.Fatal("Failed to connect to TimescaleDB", zap.Error(err))
	}

	// 3. Инициализируем воркер пул
	poolCfg := worker.Config{
		WorkerCount:  cfg.WorkerCount,
		BatchSize:    cfg.BatchSize,
		BatchTimeout: cfg.BatchTimeout,
	}
	pool := worker.NewPool(poolCfg, logger, dbStorage)

	ctx, cancel := context.WithCancel(context.Background())
	pool.Start(ctx)

	// 4. Инициализируем Kafka consumer
	kafkaConsumer := consumer.NewConsumer(consumer.Config{
		Brokers:        cfg.KafkaBrokers,
		Topic:          cfg.KafkaTopic,
		GroupID:        cfg.KafkaGroupID,
		MinBytes:       cfg.KafkaMinBytes,
		MaxBytes:       cfg.KafkaMaxBytes,
		MaxWait:        cfg.KafkaMaxWait,
		StartOffset:    cfg.KafkaStartOffset,
		SessionTimeout: 30 * time.Second,
	}, pool, logger)

	if err := kafkaConsumer.Start(ctx); err != nil {
		logger.Fatal("Failed to start Kafka consumer", zap.Error(err))
	}

	// 5. HTTP Server
	r := chi.NewRouter()
	r.Use(middleware.Logger)
	r.Use(middleware.Recoverer)
	r.Use(middleware.RequestID)

	h := handler.NewHandler(pool)
	r.Handle("/metrics", promhttp.Handler())
	r.Get("/health", h.Health)
	r.Get("/ready", h.Ready(dbStorage))
	r.Get("/stats", h.Stats(pool, kafkaConsumer))

	srv := &http.Server{
		Addr:         ":" + cfg.Port,
		Handler:      r,
		ReadTimeout:  5 * time.Second,
		WriteTimeout: 10 * time.Second,
		IdleTimeout:  120 * time.Second,
	}

	go func() {
		logger.Info("HTTP server starting", zap.String("port", cfg.Port))
		if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			logger.Fatal("ListenAndServe", zap.Error(err))
		}
	}()

	// 6. Graceful shutdown
	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
	<-quit

	logger.Info("Shutting down...")
	cancel()

	// Закрываем consumer
	if err := kafkaConsumer.Close(); err != nil {
		logger.Error("Failed to close Kafka consumer", zap.Error(err))
	}

	// Останавливаем воркеры
	pool.Stop()

	// Закрываем БД
	dbStorage.Close()

	// Graceful shutdown HTTP
	shutdownCtx, shutdownRelease := context.WithTimeout(context.Background(), 10*time.Second)
	defer shutdownRelease()
	if err := srv.Shutdown(shutdownCtx); err != nil {
		logger.Fatal("Forced shutdown", zap.Error(err))
	}

	logger.Info("Server exited gracefully")
}
