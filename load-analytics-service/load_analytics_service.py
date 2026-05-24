import os
import time
import logging
import psycopg2
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, Tuple

from prometheus_client import Gauge, start_http_server
from kubernetes import client as k8s_client, config as k8s_config

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

SCALE_SIGNAL = Gauge('fuel_monitor_predicted_rps', 'Сигнал масштабирования для HPA')


class LoadAnalyzer:
    """
    Прогнозирует нагрузку на 15 минут вперёд и посылает сигнал масштабирования
    только тогда, когда текущих ресурсов кластера не хватит для покрытия всплеска.
    """

    def __init__(self, db_url: str, hpa_name: str, hpa_namespace: str):
        self.db_url = db_url
        self.hpa_name = hpa_name
        self.hpa_namespace = hpa_namespace
        self.conn = None
        self._k8s_hpa = None

        self.short_term_window = 30
        self.weights = np.array([0.10, 0.15, 0.20, 0.25, 0.30])
        self.safety_buffer = 1.2
        self.max_rps_per_pod = float(os.getenv('MAX_RPS_PER_POD', '2.0'))
        self.lookahead_minutes = 15

        self.min_replicas = 1
        self.max_replicas = 9
        self.seasonality_profile: Dict[Tuple[int, int], float] = {}

    def init_k8s(self):
        try:
            kubeconfig = os.getenv('KUBECONFIG')
            if kubeconfig:
                k8s_config.load_kube_config(config_file=kubeconfig)
            else:
                k8s_config.load_incluster_config()
            cfg = k8s_client.Configuration.get_default_copy()
            cfg.verify_ssl = False
            k8s_client.Configuration.set_default(cfg)
            self._k8s_hpa = k8s_client.AutoscalingV2Api()
            logger.info("Kubernetes client инициализирован")
        except Exception as e:
            logger.warning(f"Kubernetes client недоступен, будет использоваться min_replicas: {e}")

    def _get_current_replicas(self) -> int:
        if not self._k8s_hpa:
            return self.min_replicas
        try:
            hpa = self._k8s_hpa.read_namespaced_horizontal_pod_autoscaler(
                name=self.hpa_name,
                namespace=self.hpa_namespace,
            )
            return hpa.status.current_replicas or self.min_replicas
        except Exception as e:
            logger.warning(f"Ошибка чтения HPA: {e}")
            return self.min_replicas

    def _connect(self):
        self.conn = psycopg2.connect(self.db_url)
        logger.info("Подключение к БД установлено")

    def _ensure_connected(self):
        try:
            if self.conn is None or self.conn.closed:
                self._connect()
            else:
                with self.conn.cursor() as cur:
                    cur.execute("SELECT 1")
        except Exception:
            self._connect()

    def close(self):
        if self.conn:
            self.conn.close()

    def _fetch_load_history(self, days: int) -> pd.DataFrame:
        query = """
        SELECT
            date_trunc('minute', ingested_at) AS time_bucket,
            COUNT(*) AS msg_count
        FROM sensor_data
        WHERE ingested_at >= NOW() - make_interval(days => %s)
        GROUP BY time_bucket
        ORDER BY time_bucket ASC
        """
        with self.conn.cursor() as cur:
            cur.execute(query, (days,))
            rows = cur.fetchall()

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows, columns=['time_bucket', 'msg_count'])
        df['rps'] = df['msg_count'] / 60.0
        df['time_bucket'] = pd.to_datetime(df['time_bucket'])
        df.set_index('time_bucket', inplace=True)
        return df

    def _build_seasonality_profile(self, df: pd.DataFrame) -> Dict[Tuple[int, int], float]:
        df_copy = df.copy()
        df_copy['hour'] = df_copy.index.hour
        df_copy['dayofweek'] = df_copy.index.dayofweek

        global_mean = df_copy['rps'].mean() or 1.0
        grouped = df_copy.groupby(['dayofweek', 'hour'])['rps'].mean()

        profile = {}
        for day in range(7):
            for hour in range(24):
                if (day, hour) in grouped.index:
                    profile[(day, hour)] = grouped[(day, hour)] / global_mean
                else:
                    profile[(day, hour)] = 1.0
        return profile

    def _calculate_weighted_average(self, recent_values: np.ndarray) -> float:
        n = len(self.weights)
        if len(recent_values) < n:
            return float(np.mean(recent_values))
        return float(np.sum(recent_values[-n:] * self.weights))

    def predict(self) -> float:
        self._ensure_connected()

        df = self._fetch_load_history(days=7)

        if df.empty:
            logger.warning("Нет данных в БД — минимальная конфигурация.")
            return 0.0

        # Строим сезонный профиль по истории
        self.seasonality_profile = self._build_seasonality_profile(df)

        # Краткосрочный тренд последних 30 минут
        recent_rps = df['rps'].tail(self.short_term_window).values
        base_forecast = self._calculate_weighted_average(recent_rps)

        # Сезонность: текущий слот и слот через 15 минут
        now = datetime.now()
        future = now + timedelta(minutes=self.lookahead_minutes)

        season_now = self.seasonality_profile.get((now.weekday(), now.hour), 1.0)
        season_future = self.seasonality_profile.get((future.weekday(), future.hour), 1.0)

        predicted_rps_now = max(0.0, base_forecast * season_now)
        predicted_rps_future = max(0.0, base_forecast * season_future)

        # Состояние кластера
        current_replicas = self._get_current_replicas()
        capacity_rps = current_replicas * self.max_rps_per_pod

        # Хватит ли текущих ресурсов, чтобы покрыть всплеск через 15 мин
        load_needed_future = predicted_rps_future * self.safety_buffer

        if load_needed_future > capacity_rps:
            # Посылаем прогноз +15 мин
            scale_signal = predicted_rps_future * self.safety_buffer
            needed_replicas = int(np.ceil(load_needed_future / self.max_rps_per_pod))
            needed_replicas = max(self.min_replicas, min(needed_replicas, self.max_replicas))
            action = "SCALE_UP"
        else:
            # Ресурсов хватает — поддерживаем текущую нагрузку
            scale_signal = predicted_rps_now * self.safety_buffer
            needed_replicas = int(np.ceil(predicted_rps_now * self.safety_buffer / self.max_rps_per_pod))
            needed_replicas = max(self.min_replicas, min(needed_replicas, self.max_replicas))
            action = "NO_ACTION"

        logger.info(
            f"[{action}] "
            f"now={predicted_rps_now:.2f} RPS | "
            f"+{self.lookahead_minutes}min={predicted_rps_future:.2f} RPS | "
            f"capacity={capacity_rps:.2f} RPS ({current_replicas} pods) | "
            f"signal={scale_signal:.2f}"
        )

        return scale_signal


def _prediction_loop(predictor: LoadAnalyzer, interval: int):
    while True:
        try:
            scale_signal = predictor.predict()
            SCALE_SIGNAL.set(scale_signal)
        except Exception as e:
            logger.error(f"Ошибка прогноза: {e}")

        time.sleep(interval)


if __name__ == "__main__":
    DB_URL            = os.getenv('DATABASE_URL', 'postgres://fuel:fuelpass@localhost:5432/fuel_db?sslmode=disable')
    METRICS_PORT      = int(os.getenv('METRICS_PORT', '8000'))
    REFRESH_INTERVAL  = int(os.getenv('REFRESH_INTERVAL_SECONDS', '60'))
    HPA_NAME          = os.getenv('HPA_NAME', 'fuel-service-hpa')
    HPA_NAMESPACE     = os.getenv('HPA_NAMESPACE', 'fuel-monitor')

    predictor = LoadAnalyzer(db_url=DB_URL, hpa_name=HPA_NAME, hpa_namespace=HPA_NAMESPACE)
    predictor.init_k8s()

    start_http_server(METRICS_PORT)
    logger.info(f"Prometheus /metrics доступен на порту {METRICS_PORT}")

    _prediction_loop(predictor, interval=REFRESH_INTERVAL)
