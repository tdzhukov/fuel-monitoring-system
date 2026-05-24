# Масштабирование вычислительного кластера системы мониторинга расхода топлива

Работающий прототип системы мониторинга с реактивным и проактивным
масштабированием в Kubernetes.

Архитектура: IoT-устройства -> EMQX -> Kafka ->
Go-сервис обработки -> TimescaleDB -> Vue-карта.

Поверх — Prometheus/Grafana, Kubernetes HPA с
реактивной (consumer lag) и проактивной (прогноз RPS) метриками.

#### Микросервисы

- [device-ingestion-service/](device-ingestion-service/) —
  Go-сервис: читает Kafka-топик `fuel-sensor-data`, батчит сообщения и
  пишет в TimescaleDB. Точка входа —
  [cmd/server/main.go](device-ingestion-service/cmd/server/main.go).
  Внутри: [consumer/](device-ingestion-service/internal/consumer/)
  (Kafka), [storage/](device-ingestion-service/internal/storage/)
  (TimescaleDB), [worker/](device-ingestion-service/internal/worker/)
  (пул воркеров), [migrations/](device-ingestion-service/migrations/)
  (SQL-миграции). Метрики Prometheus на `:8080/metrics`.
- [load-analytics-service/](load-analytics-service/) — Python-сервис
  проактивного масштабирования. Считает прогноз RPS на 15 минут вперёд
  и публикует метрику `fuel_monitor_predicted_rps`.
- [map-ui/](map-ui/) — UI для просмотра треков:
  [backend/](map-ui/backend/) (FastAPI, отдаёт треки из TimescaleDB)
  и [frontend/](map-ui/frontend/) (Vue + Vite).

#### Инфраструктура

- [docker-compose.yml](docker-compose.yml) —
  Zookeeper, Kafka, EMQX, TimescaleDB, kafka-exporter,
  Prometheus, Grafana, load-analytics-service, map-backend, map-frontend.
- [k8s/](k8s/) — манифесты Kubernetes:
  - [fuel-service/](k8s/fuel-service/) — Deployment, Service,
    ConfigMap, Secret и HPA.
  - [prometheus-adapter/](k8s/prometheus-adapter/) — Prometheus
    Adapter, чтобы Kubernetes External Metrics API отдавал HPA метрики
    `kafka_consumergroup_lag` и `fuel_monitor_predicted_rps`.
  - [monitoring/](k8s/monitoring/) — токен сервис-аккаунта для
    сбора метрик из Prometheus.
- [monitoring/](monitoring/) — конфиг Prometheus
  ([prometheus.yml](monitoring/prometheus.yml)),
  Grafana ([dashboards/](monitoring/dashboards/),
  [datasources/](monitoring/datasources/)), kubeconfig-токен для
  сбора метрик с подов ([k8s-auth/](monitoring/k8s-auth/)).
- [emqx/](emqx/) — конфигурация MQTT-брокера.
- [kafka-config/](kafka-config/) — JVM-настройки Kafka.

#### Скрипты и эксперименты

- [tests/common](tests/common) — общие тестовые скрипты:
  симулятор IoT-устройств и генератор маршрута.
- [tests/hpa](tests/hpa) — скрипты с экспериментами для
  разных конфигураций HPA.

## Как запустить

### 1. Локальный стенд (docker-compose)

Поднимает всю инфраструктуру: брокеры, БД, мониторинг, карту.

```bash
cd fuel-monitor
docker compose up -d
```

После старта доступны:

| Сервис          | URL                                |
|-----------------|------------------------------------|
| EMQX dashboard  | http://localhost:18083 (admin/public) |
| Kafka (host)    | localhost:9092                     |
| TimescaleDB     | localhost:5432 (fuel / fuelpass)   |
| Prometheus      | http://localhost:9090              |
| Grafana         | http://localhost:3000 (admin/admin) |
| Map UI          | http://localhost                   |
| Map API         | http://localhost:8000              |
| Load analytics  | http://localhost:8000/metrics |

### 2. Симулятор данных

```bash
pip install paho-mqtt
python3 iot_simulator.py --count 100 --vehicles 10 --interval 0.5
```

### 3. Kubernetes-кластер (Minikube)

Прототип масштабируется в Kubernetes — именно там работают HPA.

```bash
# Стартуем кластер и подключаем сеть к docker-compose
minikube start
docker network connect minikube prometheus    # чтобы Prometheus видел API minikube

# Собираем образ device-ingestion-service внутрь Minikube
eval $(minikube docker-env)
docker build -t fuel-monitor:latest device-ingestion-service

# Namespace + основной сервис
kubectl create namespace fuel-monitor
kubectl apply -f k8s/fuel-service/

# Prometheus Adapter (External Metrics API для HPA)
kubectl apply -f k8s/prometheus-adapter/0-adapter/
kubectl apply -f k8s/prometheus-adapter/1-custom-metrics/

# Токен для сбора метрик
kubectl apply -f k8s/monitoring/prometheus-token.yaml
```

Проверка, что External Metrics API отдаёт метрики:

```bash
kubectl get --raw "/apis/external.metrics.k8s.io/v1beta1" | jq
kubectl get hpa -n fuel-monitor
```

### 4. Эксперименты по масштабированию

Переключение режимов HPA для экспериментов:

```bash
kubectl apply -f tests/hpa/hpa-cpu-only.yaml  # только реактивный
kubectl apply -f tests/hpa/hpa-cpu-only.yaml  # только по CPU
kubectl apply -f k8s/fuel-service/hpa.yaml    # комбинированный
```

Все скрипты в [tests/](tests/).

```bash
pip install -r load-analytics-service/requirements.txt
cd tests/hpa

python3 hpa_scale_test.py   # проактивное масштабирование (прогноз RPS)
python3 kafka_lag_test.py   # реактивное масштабирование (Kafka lag)
python3 cpu_hpa_sampler.py  # масштабирование по CPU
```
