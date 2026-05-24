// mqtt-kafka-bridge: подписывается на MQTT-топик в EMQX и перекладывает
// каждое полученное сообщение в Kafka-топик. Сервис нужен потому,
// что EMQX Open Source не содержит встроенного Kafka Producer Bridge.
package main

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"os"
	"os/signal"
	"strconv"
	"strings"
	"sync/atomic"
	"syscall"
	"time"

	mqtt "github.com/eclipse/paho.mqtt.golang"
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"
	"github.com/prometheus/client_golang/prometheus/promhttp"
	"github.com/segmentio/kafka-go"
	"go.uber.org/zap"
)

type config struct {
	MQTTBroker   string
	MQTTTopic    string
	MQTTClientID string
	MQTTQoS      byte

	KafkaBrokers []string
	KafkaTopic   string

	HTTPPort string
}

func loadConfig() config {
	qos, _ := strconv.Atoi(getEnv("MQTT_QOS", "1"))
	return config{
		MQTTBroker:   getEnv("MQTT_BROKER", "tcp://emqx:1883"),
		MQTTTopic:    getEnv("MQTT_TOPIC", "fuel/sensors"),
		MQTTClientID: getEnv("MQTT_CLIENT_ID", "mqtt-kafka-bridge"),
		MQTTQoS:      byte(qos),
		KafkaBrokers: strings.Split(getEnv("KAFKA_BROKERS", "kafka:29092"), ","),
		KafkaTopic:   getEnv("KAFKA_TOPIC", "fuel-sensor-data"),
		HTTPPort:     getEnv("HTTP_PORT", "8090"),
	}
}

func getEnv(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}

var (
	mqttReceived = promauto.NewCounter(prometheus.CounterOpts{
		Name: "bridge_mqtt_messages_received_total",
		Help: "Сообщения, полученные из MQTT.",
	})
	kafkaPublished = promauto.NewCounter(prometheus.CounterOpts{
		Name: "bridge_kafka_messages_published_total",
		Help: "Сообщения, успешно опубликованные в Kafka.",
	})
	kafkaFailed = promauto.NewCounter(prometheus.CounterOpts{
		Name: "bridge_kafka_messages_failed_total",
		Help: "Сообщения, которые не удалось отправить в Kafka.",
	})
	parseErrors = promauto.NewCounter(prometheus.CounterOpts{
		Name: "bridge_payload_parse_errors_total",
		Help: "Сообщения с некорректным JSON-payload.",
	})
	mqttConnected = promauto.NewGauge(prometheus.GaugeOpts{
		Name: "bridge_mqtt_connected",
		Help: "1, если есть активное MQTT-соединение, иначе 0.",
	})
)

type sensorPayload struct {
	VehicleID string `json:"vehicle_id"`
}

func main() {
	logger, _ := zap.NewProduction()
	defer logger.Sync()

	cfg := loadConfig()
	logger.Info("starting mqtt-kafka-bridge",
		zap.String("mqtt_broker", cfg.MQTTBroker),
		zap.String("mqtt_topic", cfg.MQTTTopic),
		zap.Strings("kafka_brokers", cfg.KafkaBrokers),
		zap.String("kafka_topic", cfg.KafkaTopic))

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	writer := &kafka.Writer{
		Addr:         kafka.TCP(cfg.KafkaBrokers...),
		Topic:        cfg.KafkaTopic,
		Balancer:     &kafka.Hash{},
		BatchTimeout: 50 * time.Millisecond,
		BatchSize:    100,
		RequiredAcks: kafka.RequireAll,
		Async:        false,
	}
	defer writer.Close()

	var ready atomic.Bool

	handler := func(_ mqtt.Client, msg mqtt.Message) {
		mqttReceived.Inc()
		payload := msg.Payload()

		var p sensorPayload
		if err := json.Unmarshal(payload, &p); err != nil {
			parseErrors.Inc()
			logger.Warn("invalid payload",
				zap.Error(err),
				zap.String("topic", msg.Topic()))
		}

		writeCtx, writeCancel := context.WithTimeout(ctx, 10*time.Second)
		defer writeCancel()

		err := writer.WriteMessages(writeCtx, kafka.Message{
			Key:   []byte(p.VehicleID),
			Value: payload,
			Time:  time.Now(),
		})
		if err != nil {
			kafkaFailed.Inc()
			logger.Error("kafka write failed",
				zap.Error(err),
				zap.String("vehicle_id", p.VehicleID))
			return
		}
		kafkaPublished.Inc()
	}

	opts := mqtt.NewClientOptions().
		AddBroker(cfg.MQTTBroker).
		SetClientID(cfg.MQTTClientID).
		SetCleanSession(false).
		SetAutoReconnect(true).
		SetConnectRetry(true).
		SetConnectRetryInterval(5 * time.Second).
		SetKeepAlive(30 * time.Second).
		SetMaxReconnectInterval(30 * time.Second).
		SetOnConnectHandler(func(c mqtt.Client) {
			mqttConnected.Set(1)
			logger.Info("mqtt connected, subscribing", zap.String("topic", cfg.MQTTTopic))
			token := c.Subscribe(cfg.MQTTTopic, cfg.MQTTQoS, handler)
			token.Wait()
			if err := token.Error(); err != nil {
				logger.Error("mqtt subscribe failed", zap.Error(err))
				return
			}
			ready.Store(true)
		}).
		SetConnectionLostHandler(func(_ mqtt.Client, err error) {
			mqttConnected.Set(0)
			ready.Store(false)
			logger.Warn("mqtt connection lost", zap.Error(err))
		})

	client := mqtt.NewClient(opts)
	if token := client.Connect(); token.Wait() && token.Error() != nil {
		logger.Fatal("mqtt initial connect failed", zap.Error(token.Error()))
	}
	defer client.Disconnect(500)

	mux := http.NewServeMux()
	mux.Handle("/metrics", promhttp.Handler())
	mux.HandleFunc("/health", func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("ok"))
	})
	mux.HandleFunc("/ready", func(w http.ResponseWriter, _ *http.Request) {
		if !ready.Load() {
			http.Error(w, "not ready", http.StatusServiceUnavailable)
			return
		}
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("ready"))
	})

	srv := &http.Server{
		Addr:         ":" + cfg.HTTPPort,
		Handler:      mux,
		ReadTimeout:  5 * time.Second,
		WriteTimeout: 10 * time.Second,
	}
	go func() {
		logger.Info("http server listening", zap.String("addr", srv.Addr))
		if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			logger.Fatal("http listen", zap.Error(err))
		}
	}()

	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
	<-quit

	logger.Info("shutting down...")
	cancel()
	shutdownCtx, shutdownCancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer shutdownCancel()
	_ = srv.Shutdown(shutdownCtx)
}
