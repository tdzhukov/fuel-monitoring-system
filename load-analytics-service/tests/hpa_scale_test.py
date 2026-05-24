#!/usr/bin/env python3
"""
Тест масштабирования HPA до 6 реплик.

Алгоритм:
  1. Очистка всех данных в sensor_data за последние 7 дней
  2. 30 минут равномерной нагрузки @ 9 RPS

Математика:
  season_factor = 1.0  (единственный слот в профиле = глобальное среднее)
  WMA           ≈ 9 RPS
  predicted_rps = 9 * 1.0 = 9
  target_load   = 9 * 1.2 = 10.8
  replicas      = ceil(10.8 / 2.0) = 6  ✓
"""

import logging
import random
from datetime import datetime, timedelta

import psycopg2
import psycopg2.extras

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

DB_URL = "postgres://fuel:fuelpass@localhost:5432/fuel_db"
TARGET_RPS = 5.0
VEHICLE_IDS = [f"SCALE6-{i:03d}" for i in range(1, 11)]


def cleanup(conn):
    logger.info("Очистка исторических данных (последние 7 дней)...")
    with conn.cursor() as cur:
        cur.execute("DELETE FROM sensor_data WHERE ingested_at >= NOW() - make_interval(days => 7)")
        deleted = cur.rowcount
    conn.commit()
    logger.info(f"Удалено {deleted:,} записей.")


def generate(conn):
    now = datetime.now().replace(second=0, microsecond=0)
    buffer = []

    logger.info(f"Генерация 30 мин @ {TARGET_RPS} RPS...")
    for i in range(30):
        ts = now - timedelta(minutes=30 - i)
        count = int(TARGET_RPS * 60)
        for _ in range(count):
            t = ts + timedelta(seconds=random.uniform(0, 59.999))
            buffer.append((
                t, t,
                random.choice(VEHICLE_IDS),
                round(55.7558 + random.uniform(-0.1, 0.1), 6),
                round(37.6173 + random.uniform(-0.15, 0.15), 6),
                round(random.uniform(3.0, 15.0), 2),
            ))

    sql = """
        INSERT INTO sensor_data (timestamp, ingested_at, vehicle_id, latitude, longitude, fuel_rate)
        VALUES (%s, %s, %s, %s, %s, %s)
    """
    with conn.cursor() as cur:
        psycopg2.extras.execute_batch(cur, sql, buffer)
    conn.commit()

    logger.info(f"Вставлено {len(buffer):,} записей.")
    logger.info("")
    logger.info("Ожидаемый результат через ≤60 сек:")
    logger.info(f"  WMA ≈ {TARGET_RPS} RPS × season 1.0 -> 6 реплик")
    logger.info("Следи:")
    logger.info("  watch kubectl get hpa fuel-service-hpa -n fuel-monitor")


def main():
    conn = psycopg2.connect(DB_URL)
    try:
        cleanup(conn)
        generate(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
