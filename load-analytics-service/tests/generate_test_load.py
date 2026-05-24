#!/usr/bin/env python3
"""
Генератор тестовых данных для алгоритма LoadAnalyzer.
Создаёт реалистичную нагрузку с:
• Суточной сезонностью (утренний/вечерний пик)
• Недельной сезонностью (будни != выходные)
• Случайным шумом и аномалиями
• Линейным трендом
"""

import psycopg2
import psycopg2.extras
import numpy as np
from datetime import datetime, timedelta
from typing import Optional
import random
import logging
import argparse

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class LoadDataGenerator:
    """Генератор реалистичных данных нагрузки."""

    # Паттерны суточной нагрузки (коэффициенты по часам)
    HOURLY_PATTERN = {
        # Ночь: минимальная активность
        **{h: 0.2 for h in range(0, 6)},
        # Утро: рост
        6: 0.4, 7: 0.7, 8: 1.2, 9: 1.5,
        # День: стабильно высокий
        10: 1.3, 11: 1.2, 12: 1.0, 13: 0.9, 14: 1.0, 15: 1.1, 16: 1.2,
        # Вечерний пик
        17: 1.6, 18: 1.8, 19: 1.4,
        # Спад
        20: 1.0, 21: 0.7, 22: 0.4, 23: 0.3,
    }

    # Паттерны по дням недели (0=Пн, 6=Вс)
    WEEKLY_PATTERN = {
        0: 1.0,  # Пн
        1: 1.1,  # Вт
        2: 1.15, # Ср
        3: 1.1,  # Чт
        4: 1.0,  # Пт
        5: 0.6,  # Сб
        6: 0.5,  # Вс
    }

    def __init__(
        self,
        db_config: dict,
        base_rps: float = 100.0,
        noise_level: float = 0.15,
        anomaly_prob: float = 0.02,
        anomaly_multiplier: float = 3.0,
        trend_per_day: float = 0.0,  # 0.01 = +1% в день
    ):
        """
        Инициализация генератора.

        :param base_rps: Базовая нагрузка (сообщений в секунду)
        :param noise_level: Уровень случайного шума (0.0-1.0)
        :param anomaly_prob: Вероятность аномалии в минуту (0.0-1.0)
        :param anomaly_multiplier: Во сколько раз усиливается нагрузка при аномалии
        :param trend_per_day: Ежедневный тренд (0.01 = +1%/день)
        """
        self.db_config = db_config
        self.base_rps = base_rps
        self.noise_level = noise_level
        self.anomaly_prob = anomaly_prob
        self.anomaly_multiplier = anomaly_multiplier
        self.trend_per_day = trend_per_day
        self.conn = None

    def connect(self):
        """Подключение к БД."""
        try:
            self.conn = psycopg2.connect(**self.db_config)
            logger.info("Подключено к БД")
        except Exception as e:
            logger.error(f"Ошибка подключения: {e}")
            raise

    def close(self):
        """Закрытие соединения."""
        if self.conn:
            self.conn.close()
            logger.info("Соединение закрыто")

    def _get_seasonal_factor(self, timestamp: datetime) -> float:
        """Расчёт сезонного коэффициента для момента времени."""
        hour = timestamp.hour
        dayofweek = timestamp.weekday()

        hourly = self.HOURLY_PATTERN.get(hour, 1.0)
        weekly = self.WEEKLY_PATTERN.get(dayofweek, 1.0)

        return hourly * weekly

    def _generate_minute_load(
        self,
        timestamp: datetime,
        start_date: datetime,
        vehicle_ids: list[str]
    ) -> list[dict]:
        """
        Генерация данных для одной минуты.
        Возвращает список записей для вставки в БД.
        """
        # 1. Базовая нагрузка с трендом
        days_elapsed = (timestamp - start_date).days
        trend_factor = 1.0 + (self.trend_per_day * days_elapsed)
        base_load = self.base_rps * trend_factor

        # 2. Сезонность
        seasonal = self._get_seasonal_factor(timestamp)
        expected_rps = base_load * seasonal

        # 3. Случайный шум (нормальное распределение)
        noise = np.random.normal(1.0, self.noise_level)
        actual_rps = max(0, expected_rps * noise)

        # 4. Аномалии (резкие всплески)
        if random.random() < self.anomaly_prob:
            actual_rps *= self.anomaly_multiplier
            logger.debug(f"⚡ Аномалия в {timestamp}: {actual_rps:.1f} RPS")

        # 5. Конвертация RPS -> количество сообщений в минуту
        msg_count = int(actual_rps * 60)

        # 6. Генерация отдельных записей
        records = []
        vehicle_count = len(vehicle_ids)

        for i in range(msg_count):
            # Распределяем сообщения равномерно по минуте + небольшой джиттер
            second_offset = random.uniform(0, 59.999)
            ingested_at = timestamp + timedelta(seconds=second_offset)

            # Случайный автомобиль + координаты
            vehicle_id = random.choice(vehicle_ids)
            lat = 55.7558 + random.uniform(-0.1, 0.1)
            lon = 37.6173 + random.uniform(-0.15, 0.15)
            fuel_rate = random.uniform(3.0, 15.0)

            records.append({
                'timestamp': ingested_at,
                'ingested_at': ingested_at,
                'vehicle_id': vehicle_id,
                'latitude': round(lat, 6),
                'longitude': round(lon, 6),
                'fuel_rate': round(fuel_rate, 2),
            })

        return records

    def generate(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        days: int = 30,
        vehicle_count: int = 10,
        batch_size: int = 10000,
        clear_existing: bool = False,
    ):
        """
        Генерация и вставка данных.

        :param start_date: Начало периода (по умолчанию: 30 дней назад)
        :param end_date: Конец периода (по умолчанию: сейчас)
        :param days: Количество дней (если не заданы start/end)
        :param vehicle_count: Количество уникальных vehicle_id
        :param batch_size: Размер пакета для вставки
        :param clear_existing: Очистить старые данные перед генерацией
        """
        if not self.conn:
            self.connect()

        # Определение периода
        if start_date is None:
            end_date = end_date or datetime.now()
            start_date = end_date - timedelta(days=days)

        logger.info(f"Генерация данных: {start_date} -> {end_date}")
        logger.info(f"Автомобилей: {vehicle_count}, Batch size: {batch_size}")

        # Генерация ID автомобилей
        vehicle_ids = [f"TEST-VEHICLE-{i:04d}" for i in range(1, vehicle_count + 1)]

        # Очистка
        if clear_existing:
            logger.warning("Очистка старых данных...")
            with self.conn.cursor() as cur:
                cur.execute("DELETE FROM sensor_data WHERE timestamp >= %s", (start_date,))
            self.conn.commit()
            logger.info("Очистка завершена")

        # Генерация данных по минутам
        current = start_date
        buffer = []
        total_inserted = 0

        logger.info("Генерация записей...")

        while current <= end_date:
            records = self._generate_minute_load(current, start_date, vehicle_ids)
            buffer.extend(records)

            if len(buffer) >= batch_size:
                total_inserted += self._insert_batch(buffer)
                buffer = []
                logger.info(f"Вставлено {total_inserted:,} записей...")

            current += timedelta(minutes=1)

        # Вставка остатка
        if buffer:
            total_inserted += self._insert_batch(buffer)

        logger.info(f"Готово! Всего записей: {total_inserted:,}")
        return total_inserted

    def _insert_batch(self, records: list[dict]) -> int:
        """Пакетная вставка записей в БД."""
        if not records:
            return 0

        query = """
        INSERT INTO sensor_data (timestamp, ingested_at, vehicle_id, latitude, longitude, fuel_rate)
        VALUES (%s, %s, %s, %s, %s, %s)
        """

        values = [
            (r['timestamp'], r['ingested_at'], r['vehicle_id'], r['latitude'], r['longitude'], r['fuel_rate'])
            for r in records
        ]

        with self.conn.cursor() as cur:
            psycopg2.extras.execute_batch(cur, query, values)
        self.conn.commit()

        return len(records)

    def generate_quick_test(self, hours: int = 2, vehicle_count: int = 3):
        """Быстрая генерация для тестов (2 часа данных)."""
        logger.info("Генерация быстрых тестовых данных...")

        end_date = datetime.now()
        start_date = end_date - timedelta(hours=hours)

        return self.generate(
            start_date=start_date,
            end_date=end_date,
            vehicle_count=vehicle_count,
            batch_size=1000,
            clear_existing=True,
        )


def parse_args():
    parser = argparse.ArgumentParser(description="Генератор тестовых данных для LoadAnalyzer")

    parser.add_argument('--days', type=int, default=30, help='Количество дней данных (по умолчанию: 30)')
    parser.add_argument('--base-rps', type=float, default=100.0, help='Базовая нагрузка в RPS')
    parser.add_argument('--vehicles', type=int, default=10, help='Количество тестовых автомобилей')
    parser.add_argument('--noise', type=float, default=0.15, help='Уровень шума (0.0-1.0)')
    parser.add_argument('--anomaly-prob', type=float, default=0.02, help='Вероятность аномалии')
    parser.add_argument('--trend', type=float, default=0.005, help='Ежедневный тренд (+0.5%/день)')
    parser.add_argument('--clear', action='store_true', help='Очистить старые данные')
    parser.add_argument('--quick', action='store_true', help='Режим быстрой генерации (2 часа)')

    # Параметры БД
    parser.add_argument('--db-host', default='localhost', help='Хост БД')
    parser.add_argument('--db-port', type=int, default=5432, help='Порт БД')
    parser.add_argument('--db-name', default='fuel_db', help='Имя БД')
    parser.add_argument('--db-user', default='fuel', help='Пользователь БД')
    parser.add_argument('--db-pass', default='fuelpass', help='Пароль БД')

    return parser.parse_args()


def main():
    args = parse_args()

    db_config = {
        'host': args.db_host,
        'port': args.db_port,
        'database': args.db_name,
        'user': args.db_user,
        'password': args.db_pass,
    }

    generator = LoadDataGenerator(
        db_config=db_config,
        base_rps=args.base_rps,
        noise_level=args.noise,
        anomaly_prob=args.anomaly_prob,
        trend_per_day=args.trend,
    )

    try:
        generator.connect()

        if args.quick:
            count = generator.generate_quick_test(vehicle_count=args.vehicles)
        else:
            count = generator.generate(
                days=args.days,
                vehicle_count=args.vehicles,
                clear_existing=args.clear,
            )

        # Статистика
        with generator.conn.cursor() as cur:
            cur.execute("""
                SELECT
                    COUNT(*) as total,
                    COUNT(DISTINCT vehicle_id) as vehicles,
                    MIN(timestamp) as first,
                    MAX(timestamp) as last
                FROM sensor_data
            """)
            stats = cur.fetchone()

        print(f"\n Статистика в БД:")
        print(f"   Всего записей: {stats[0]:,}")
        print(f"   Автомобилей: {stats[1]}")
        print(f"   Период: {stats[2]} -> {stats[3]}")

    except KeyboardInterrupt:
        logger.info("Прервано пользователем")
    except Exception as e:
        logger.error(f"Ошибка: {e}")
        raise
    finally:
        generator.close()


if __name__ == "__main__":
    main()