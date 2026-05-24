DROP INDEX IF EXISTS idx_sensor_data_vehicle_time;
DROP INDEX IF EXISTS idx_sensor_data_vehicle_only;
DROP INDEX IF EXISTS idx_sensor_data_time_only;

SELECT remove_retention_policy('sensor_data', if_exists => TRUE);
SELECT remove_compression_policy('sensor_data', if_exists => TRUE);
