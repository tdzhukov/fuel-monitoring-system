CREATE INDEX IF NOT EXISTS idx_sensor_data_vehicle_time
    ON sensor_data (vehicle_id, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_sensor_data_vehicle_only
    ON sensor_data (vehicle_id);

CREATE INDEX IF NOT EXISTS idx_sensor_data_time_only
    ON sensor_data (timestamp DESC);

-- Политики хранения и компрессии
SELECT add_retention_policy('sensor_data', INTERVAL '90 days', if_not_exists => TRUE);

ALTER TABLE sensor_data SET (
    timescaledb.compress,
    timescaledb.compress_orderby = 'timestamp DESC',
    timescaledb.compress_segmentby = 'vehicle_id'
);

SELECT add_compression_policy('sensor_data', INTERVAL '7 days', if_not_exists => TRUE);
