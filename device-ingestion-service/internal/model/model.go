package model

import (
	"encoding/json"
	"time"
)

type SensorData struct {
	Timestamp           time.Time `json:"timestamp"`
	VehicleID           string    `json:"vehicle_id"`
	VehicleGPSLatitude  float64   `json:"vehicle_gps_latitude"`
	VehicleGPSLongitude float64   `json:"vehicle_gps_longitude"`
	FuelConsumptionRate float64   `json:"fuel_consumption_rate"`
}

const TimeLayout = "2006-01-02 15:04:05"

func (s *SensorData) UnmarshalJSON(data []byte) error {
	type Alias SensorData
	aux := &struct {
		Timestamp string `json:"timestamp"`
		*Alias
	}{
		Alias: (*Alias)(s),
	}

	if err := json.Unmarshal(data, aux); err != nil {
		return err
	}

	var err error
	s.Timestamp, err = time.Parse(TimeLayout, aux.Timestamp)
	if err != nil {
		return err
	}

	return nil
}

// Validate проверяет корректность данных
func (s *SensorData) Validate() error {
	if s.VehicleID == "" {
		return ErrEmptyVehicleID
	}
	if s.VehicleGPSLatitude < -90 || s.VehicleGPSLatitude > 90 {
		return ErrInvalidLatitude
	}
	if s.VehicleGPSLongitude < -180 || s.VehicleGPSLongitude > 180 {
		return ErrInvalidLongitude
	}
	if s.FuelConsumptionRate < 0 {
		return ErrInvalidFuelRate
	}
	return nil
}
