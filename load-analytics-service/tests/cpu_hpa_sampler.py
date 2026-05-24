#!/usr/bin/env python3
"""
Сэмплер лага, реплик и потребления CPU для теста дефолтного HPA по CPU.

Каждые SAMPLE_INTERVAL секунд пишет в CSV строку с метриками:
- t_sec      — время от старта сэмплинга;
- lag        — суммарный consumer-lag группы по топику;
- replicas   — фактическое число реплик Deployment'а;
- cpu_total_m — суммарное потребление CPU всеми подами Deployment'а;
- cpu_avg_m   — среднее потребление CPU на под;
- cpu_util_pct — средняя утилизация относительно requests.cpu = 250m, в процентах.
"""

import csv
import subprocess
import sys
import time

DURATION_SEC = int(sys.argv[1]) if len(sys.argv) > 1 else 420
OUT_PATH = sys.argv[2] if len(sys.argv) > 2 else "cpu_hpa_test_run.csv"
SAMPLE_INTERVAL_SEC = int(sys.argv[3]) if len(sys.argv) > 3 else 5

NAMESPACE = "fuel-monitor"
DEPLOYMENT = "fuel-service"
LABEL_SELECTOR = "app=fuel-service"
CONSUMER_GROUP = "fuel-monitor-consumer"
TOPIC = "fuel-sensor-data"
CPU_REQUEST_MILLI = 250


def get_lag() -> int:
    out = subprocess.run(
        ["docker", "exec", "kafka", "kafka-consumer-groups",
         "--bootstrap-server", "kafka:29092",
         "--describe", "--group", CONSUMER_GROUP],
        capture_output=True, text=True, timeout=15,
    ).stdout
    total = 0
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 6 and parts[1] == TOPIC:
            try:
                total += int(parts[5])
            except ValueError:
                pass
    return total


def get_replicas() -> int:
    out = subprocess.run(
        ["kubectl", "get", "deploy", DEPLOYMENT, "-n", NAMESPACE,
         "-o", "jsonpath={.status.replicas}"],
        capture_output=True, text=True, timeout=10,
    ).stdout.strip()
    return int(out) if out else 0


def get_cpu_total_milli() -> tuple[int, int, int]:
    out = subprocess.run(
        ["kubectl", "top", "pods", "-n", NAMESPACE,
         "-l", LABEL_SELECTOR, "--no-headers"],
        capture_output=True, text=True, timeout=15,
    ).stdout
    total = 0
    pods = 0
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        raw = parts[1]
        try:
            if raw.endswith("m"):
                val = int(raw[:-1])
            else:
                val = int(float(raw) * 1000)
        except ValueError:
            continue
        total += val
        pods += 1
    avg = total // pods if pods else 0
    return total, avg, pods


def main() -> None:
    start = time.time()
    deadline = start + DURATION_SEC
    with open(OUT_PATH, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            ["t_sec", "lag", "replicas", "cpu_total_m", "cpu_avg_m", "cpu_util_pct"]
        )
        f.flush()
        while time.time() < deadline:
            t = int(time.time() - start)
            try:
                lag = get_lag()
            except Exception:
                lag = -1
            try:
                replicas = get_replicas()
            except Exception:
                replicas = -1
            try:
                cpu_total, cpu_avg, _ = get_cpu_total_milli()
            except Exception:
                cpu_total, cpu_avg = -1, -1
            util = round(cpu_avg * 100 / CPU_REQUEST_MILLI, 1) if cpu_avg >= 0 else -1
            print(
                f"t={t:3d}s lag={lag:>8d} replicas={replicas:>2d} "
                f"cpu_total={cpu_total:>5d}m cpu_avg={cpu_avg:>4d}m "
                f"util={util}%",
                flush=True,
            )
            writer.writerow([t, lag, replicas, cpu_total, cpu_avg, util])
            f.flush()
            next_tick = start + ((t // SAMPLE_INTERVAL_SEC) + 1) * SAMPLE_INTERVAL_SEC
            sleep_for = next_tick - time.time()
            if sleep_for > 0:
                time.sleep(sleep_for)


if __name__ == "__main__":
    main()
