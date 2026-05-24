package config

import (
	"os"
	"strconv"
	"strings"
	"time"
)

// Константы для Kafka offset
const (
	KafkaFirstOffset = -2
	KafkaLastOffset  = -1
)

type Config struct {
	// Service
	Port     string
	LogLevel string

	// Worker Pool
	WorkerCount  int
	BatchSize    int
	BatchTimeout time.Duration

	// Database
	DatabaseDSN    string
	DBMaxConns     int32
	MigrationsPath string

	// Kafka
	KafkaBrokers     []string
	KafkaTopic       string
	KafkaGroupID     string
	KafkaMinBytes    int
	KafkaMaxBytes    int
	KafkaMaxWait     time.Duration
	KafkaStartOffset int64
}

func Load() Config {
	cfg := Config{
		// Service
		Port:     getEnv("PORT", "8080"),
		LogLevel: getEnv("LOG_LEVEL", "info"),

		// Worker Pool
		WorkerCount:  getIntEnv("WORKER_COUNT", 20),
		BatchSize:    getIntEnv("BATCH_SIZE", 100),
		BatchTimeout: getDurationEnv("BATCH_TIMEOUT", 100*time.Millisecond),

		// Database
		DatabaseDSN:    getEnv("DATABASE_URL", "postgres://fuel:fuelpass@timescale:5432/fuel_db?sslmode=disable"),
		DBMaxConns:     int32(getIntEnv("DB_MAX_CONNS", 50)),
		MigrationsPath: getEnv("MIGRATIONS_PATH", "./migrations"),

		// Kafka
		KafkaBrokers:     getStringsEnv("KAFKA_BROKERS", "kafka:9092"),
		KafkaTopic:       getEnv("KAFKA_TOPIC", "fuel-sensor-data"),
		KafkaGroupID:     getEnv("KAFKA_GROUP_ID", "fuel-monitor-consumer"),
		KafkaMinBytes:    getIntEnv("KAFKA_MIN_BYTES", 10e3),
		KafkaMaxBytes:    getIntEnv("KAFKA_MAX_BYTES", 10e6),
		KafkaMaxWait:     getDurationEnv("KAFKA_MAX_WAIT", 10*time.Second),
		KafkaStartOffset: getInt64Env("KAFKA_START_OFFSET", KafkaLastOffset),
	}
	return cfg
}

func getEnv(key, defaultVal string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return defaultVal
}

func getIntEnv(key string, defaultVal int) int {
	if v := os.Getenv(key); v != "" {
		if i, err := strconv.Atoi(v); err == nil {
			return i
		}
	}
	return defaultVal
}

func getInt64Env(key string, defaultVal int64) int64 {
	if v := os.Getenv(key); v != "" {
		if i, err := strconv.ParseInt(v, 10, 64); err == nil {
			return i
		}
	}
	return defaultVal
}

func getDurationEnv(key string, defaultVal time.Duration) time.Duration {
	if v := os.Getenv(key); v != "" {
		if d, err := time.ParseDuration(v); err == nil {
			return d
		}
	}
	return defaultVal
}

func getStringsEnv(key, defaultVal string) []string {
	if v := os.Getenv(key); v != "" {
		return strings.Split(v, ",")
	}
	return strings.Split(defaultVal, ",")
}
