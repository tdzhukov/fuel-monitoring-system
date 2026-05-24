#!/usr/bin/env python3
"""IoT-симулятор: публикует MQTT-сообщения в EMQX.

EMQX по правилу rule_engine перекладывает их в Kafka-топик fuel-sensor-data,
который читает device-ingestion-service.

Зависимости:
    pip install paho-mqtt

Примеры запуска:
    # 20 сообщений по 5 машинам с интервалом 1 с (значения по умолчанию)
    python3 iot-simulator.py

    # 50 сообщений по 10 машинам каждые 500 мс
    python3 iot-simulator.py --count 50 --vehicles 10 --interval 0.5
"""
import argparse
import json
import random
import sys
from datetime import datetime, timezone

import paho.mqtt.client as mqtt


def generate_event(vehicle_id: str) -> dict:
    """Генерирует одно событие в формате из stress-test.sh."""
    return {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "vehicle_id": vehicle_id,
        "vehicle_gps_latitude": round(40 + random.random(), 6),
        "vehicle_gps_longitude": round(-78 + random.random(), 6),
        "fuel_consumption_rate": round(3 + random.random() * 7, 3),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="IoT-симулятор для отправки MQTT-сообщений в EMQX."
    )
    parser.add_argument("--host", default="localhost", help="EMQX MQTT host")
    parser.add_argument("--port", type=int, default=1883, help="EMQX MQTT port")
    parser.add_argument("--topic", default="fuel/sensors", help="MQTT topic")
    parser.add_argument("--count", type=int, default=20, help="Всего сообщений")
    parser.add_argument(
        "--interval", type=float, default=1.0, help="Пауза между сообщениями, сек"
    )
    parser.add_argument("--vehicles", type=int, default=5, help="Количество машин")
    parser.add_argument("--qos", type=int, choices=[0, 1, 2], default=1)
    args = parser.parse_args()

    client = mqtt.Client(client_id=f"iot-sim-{random.randint(1000, 9999)}")

    print(f"-> Connecting to mqtt://{args.host}:{args.port} ...")
    try:
        client.connect(args.host, args.port, keepalive=30)
    except OSError as exc:
        print(f"Не удалось подключиться к EMQX: {exc}", file=sys.stderr)
        return 1

    client.loop_start()
    print(
        f"Sending {args.count} msg to topic={args.topic}, "
        f"vehicles={args.vehicles}, interval={args.interval}s, qos={args.qos}"
    )

    sent, failed = 0, 0
    try:
        for i in range(1, args.count + 1):
            vid = f"TRUCK-{random.randint(0, args.vehicles - 1):04d}"
            event = generate_event(vid)
            payload = json.dumps(event)

            info = client.publish(args.topic, payload, qos=args.qos)
            info.wait_for_publish(timeout=5)

            if info.rc == mqtt.MQTT_ERR_SUCCESS:
                sent += 1
                print(f"  [{i:>3}/{args.count}] {vid}  fuel={event['fuel_consumption_rate']}")
            else:
                failed += 1
                print(f"  [{i:>3}/{args.count}] publish failed rc={info.rc}", file=sys.stderr)
    except KeyboardInterrupt:
        print("\n Interrupted by user")
    finally:
        client.loop_stop()
        client.disconnect()

    print(f"\n Done. sent={sent}, failed={failed}")
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
