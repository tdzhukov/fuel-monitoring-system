#!/usr/bin/env python3
"""
Тест реактивного автомасштабирования HPA по метрике kafka_consumergroup_lag.

Применяется в составе сценария:
  1. kubectl delete hpa fuel-service-hpa -n fuel-monitor
  2. kubectl scale deploy/fuel-service --replicas=1 -n fuel-monitor
  3. kubectl apply -f k8s/fuel-service/hpa-lag-only.yaml
  4. kubectl scale deploy/fuel-service --replicas=1 -n fuel-monitor
  5. python kafka_lag_test.py [<duration_sec> [<batches_per_sec> [<batch_size>]]]
  6. наблюдение HPA + лага в течение длительности теста
"""

import json
import logging
import random
import subprocess
import sys
import time
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

KAFKA_TOPIC = "fuel-sensor-data"
KAFKA_INTERNAL_BROKER = "kafka:29092"
KAFKA_CONTAINER = "kafka"
DURATION_SEC = int(sys.argv[1]) if len(sys.argv) > 1 else 240
BATCHES_PER_SEC = int(sys.argv[2]) if len(sys.argv) > 2 else 2
BATCH_SIZE = int(sys.argv[3]) if len(sys.argv) > 3 else 5000
VEHICLE_IDS = [f"LAG-{i:03d}" for i in range(1, 21)]


def make_batch(size: int) -> str:
    out = []
    for _ in range(size):
        out.append(json.dumps({
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "vehicle_id": random.choice(VEHICLE_IDS),
            "vehicle_gps_latitude": round(55.7558 + random.uniform(-0.1, 0.1), 6),
            "vehicle_gps_longitude": round(37.6173 + random.uniform(-0.15, 0.15), 6),
            "fuel_consumption_rate": round(random.uniform(3.0, 15.0), 2),
        }))
    return "\n".join(out) + "\n"


def main():
    cmd = [
        "docker", "exec", "-i", KAFKA_CONTAINER,
        "kafka-console-producer",
        "--broker-list", KAFKA_INTERNAL_BROKER,
        "--topic", KAFKA_TOPIC,
        "--producer-property", "linger.ms=20",
        "--producer-property", "batch.size=65536",
    ]
    target_rps = BATCHES_PER_SEC * BATCH_SIZE
    logger.info(f"Старт нагрузки: {DURATION_SEC} с, {BATCHES_PER_SEC} батчей/с × "
                f"{BATCH_SIZE} сообщений = ~{target_rps} RPS")
    logger.info(f"Команда: {' '.join(cmd)}")

    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, text=True)
    start = time.time()
    sent = 0
    interval = 1.0 / BATCHES_PER_SEC
    try:
        next_tick = start
        deadline = start + DURATION_SEC
        last_log = start
        while time.time() < deadline:
            batch = make_batch(BATCH_SIZE)
            proc.stdin.write(batch)
            proc.stdin.flush()
            sent += BATCH_SIZE
            now = time.time()
            if now - last_log >= 10:
                logger.info(f"  отправлено: {sent} сообщений за {now - start:.0f} с "
                            f"(≈ {sent / (now - start):.0f} RPS)")
                last_log = now
            next_tick += interval
            sleep_for = next_tick - time.time()
            if sleep_for > 0:
                time.sleep(sleep_for)
    finally:
        proc.stdin.close()
        proc.wait(timeout=30)
    elapsed = time.time() - start
    actual_rps = sent / elapsed if elapsed else 0

    logger.info(f"Готово. Отправлено {sent} сообщений за {elapsed:.1f} с (≈ {actual_rps:.0f} RPS).")


if __name__ == "__main__":
    main()
