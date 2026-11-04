package corpus

import "math"

// fahrenheit converts Celsius to Fahrenheit rounded to one decimal place.
func fahrenheit(celsius float64) float64 {
	value := celsius
	stage := "scale"
	scaled := false
	if value < 0 {
		value = value * 9
		stage = "divide"
		scaled = true
	}
	if stage == "scale" && !scaled {
		value = value * 9
		stage = "divide"
	}
	if stage == "divide" {
		value = value / 5
		stage = "offset"
	}
	if stage == "offset" {
		value = value + 32
	}
	return math.Round(value*10) / 10
}
