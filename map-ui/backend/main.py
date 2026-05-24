import os
from typing import List, Optional
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import asyncpg
import uvicorn

app = FastAPI(title="Fuel Monitor Map API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Конфигурация БД
DATABASE_URL = os.getenv("DATABASE_URL", "postgres://fuel:fuelpass@timescale:5432/fuel_db")

class TrackPoint(BaseModel):
    lat: float
    lon: float
    timestamp: str
    fuel_rate: Optional[float] = None

class VehicleTrack(BaseModel):
    vehicle_id: str
    points: List[TrackPoint]
    color: Optional[str] = "#3498db"

class VehicleInfo(BaseModel):
    vehicle_id: str
    point_count: int

# Пул подключений к БД
db_pool: Optional[asyncpg.Pool] = None

@app.on_event("startup")
async def startup():
    global db_pool
    try:
        db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
        print("Connected to TimescaleDB")
    except Exception as e:
        print(f"Database connection failed: {e}")

@app.on_event("shutdown")
async def shutdown():
    if db_pool:
        await db_pool.close()

@app.get("/api/vehicles", response_model=List[VehicleInfo])
async def get_vehicles(hours: int = Query(default=24, ge=1, le=720)):
    """Возвращает список всех автомобилей и количество точек у них за период"""
    if not db_pool:
        raise HTTPException(status_code=503, detail="Database not connected")

    query = """
        SELECT vehicle_id, COUNT(*) as point_count
        FROM sensor_data
        WHERE timestamp > NOW() - ($1 * interval '1 hour')
        GROUP BY vehicle_id
        ORDER BY vehicle_id ASC
    """

    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(query, hours)
            return [{"vehicle_id": row['vehicle_id'], "point_count": row['point_count']} for row in rows]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/tracks", response_model=List[VehicleTrack])
async def get_tracks(hours: int = Query(default=24, ge=1, le=720)):
    if not db_pool:
        raise HTTPException(status_code=503, detail="Database not connected")

    query = """
        SELECT vehicle_id, latitude, longitude, timestamp, fuel_rate
        FROM sensor_data
        WHERE timestamp > NOW() - ($1 * interval '1 hour')
        ORDER BY vehicle_id, timestamp ASC
    """

    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(query, hours)

            if not rows:
                return []

            tracks_map = {}
            colors = ["#2ecc71", "#3498db", "#9b59b6", "#e74c3c", "#f1c40f", "#1abc9c", "#e67e22"]

            for row in rows:
                vid = row['vehicle_id']
                if vid not in tracks_map:
                    color_idx = len(tracks_map) % len(colors)
                    tracks_map[vid] = {
                        "vehicle_id": vid,
                        "points": [],
                        "color": colors[color_idx]
                    }

                tracks_map[vid]["points"].append({
                    "lat": row['latitude'],
                    "lon": row['longitude'],
                    "timestamp": row['timestamp'].isoformat(),
                    "fuel_rate": float(row['fuel_rate']) if row['fuel_rate'] else None
                })

            # Фильтруем треки с менее чем 2 точками
            result = [t for t in tracks_map.values() if len(t["points"]) >= 2]
            return result

    except Exception as e:
        print(f"DB Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health():
    return {"status": "ok"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
