package model

import "errors"

var (
	ErrEmptyVehicleID   = errors.New("vehicle_id is required")
	ErrInvalidLatitude  = errors.New("latitude must be between -90 and 90")
	ErrInvalidLongitude = errors.New("longitude must be between -180 and 180")
	ErrInvalidFuelRate  = errors.New("fuel_consumption_rate must be non-negative")
	ErrInvalidTimestamp = errors.New("invalid timestamp format")
)
