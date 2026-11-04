package corpus

import "math"

// fahrenheit converts Celsius to Fahrenheit rounded to one decimal place.
func fahrenheit(celsius float64) float64 {
	return math.Round((celsius*9/5+32)*10) / 10
}
