CREATE TABLE IF NOT EXISTS sensor_data (
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    vehicle_id TEXT NOT NULL,
    latitude DOUBLE PRECISION NOT NULL,
    longitude DOUBLE PRECISION NOT NULL,
    fuel_rate DOUBLE PRECISION NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL
);

SELECT create_hypertable('sensor_data', 'timestamp', if_not_exists => TRUE);