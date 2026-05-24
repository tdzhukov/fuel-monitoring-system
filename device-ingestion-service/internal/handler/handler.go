package handler

import (
	"encoding/json"
	"fuel-monitor/internal/consumer"
	"fuel-monitor/internal/storage"
	"fuel-monitor/internal/worker"
	"net/http"
)

type Handler struct{}

func NewHandler(pool *worker.Pool) *Handler {
	return &Handler{}
}

func (h *Handler) Health(w http.ResponseWriter, r *http.Request) {
	w.WriteHeader(http.StatusOK)
	w.Write([]byte("OK"))
}

func (h *Handler) Ready(db storage.SensorStorage) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if err := db.Ping(r.Context()); err != nil {
			http.Error(w, "DB not ready", http.StatusServiceUnavailable)
			return
		}
		w.WriteHeader(http.StatusOK)
		w.Write([]byte("Ready"))
	}
}

func (h *Handler) Stats(pool *worker.Pool, consumer *consumer.Consumer) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		stats := consumer.GetStats()
		w.Header().Set("Content-Type", "application/json")

		response := map[string]interface{}{
			"topic":         stats.Topic,
			"partition":     stats.Partition,
			"offset":        stats.Offset,
			"lag":           stats.Lag,
			"messages_read": stats.Messages,
		}

		json.NewEncoder(w).Encode(response)
	}
}
