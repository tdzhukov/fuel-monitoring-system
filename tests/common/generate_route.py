import asyncpg
import asyncio
import random
from datetime import datetime, timedelta

# Конфигурация
DB_URL = "postgres://fuel:fuelpass@localhost:5432/fuel_db"
VEHICLE_ID = "MOSCOW-TRUCK-002"

# # Формат: [Широта (lat), Долгота (lon)]
WAYPOINTS = []


async def generate_and_insert():
    print(f"Генерация маршрута для {VEHICLE_ID}...")

    try:
        conn = await asyncpg.connect(DB_URL)
        print("Подключено к базе данных")

        # Очищаем старые данные для этого грузовика
        await conn.execute(f"DELETE FROM sensor_data WHERE vehicle_id = $1", VEHICLE_ID)

        points_to_insert = []
        current_time = datetime.utcnow() - timedelta(hours=5)

        total_points = 0

        # Генерируем точки между waypoints
        for i in range(len(WAYPOINTS)):
            lat, lon = WAYPOINTS[i]
            fuel_rate = random.uniform(5.0, 15.0)
            points_to_insert.append((
                current_time,
                VEHICLE_ID,
                lat,
                lon,
                fuel_rate
            ))

            current_time += timedelta(seconds=5)
            total_points += 1

        # Массовая вставка данных
        await conn.executemany("""
            INSERT INTO sensor_data (timestamp, vehicle_id, latitude, longitude, fuel_rate)
            VALUES ($1, $2, $3, $4, $5)
        """, points_to_insert)

        print(f"Успешно! Загружено {total_points} точек.")
        print(f"Временной диапазон: {points_to_insert[0][0]} ... {points_to_insert[-1][0]}")

        await conn.close()

    except Exception as e:
        print(f"Ошибка: {e}")

if __name__ == "__main__":
    asyncio.run(generate_and_insert())
