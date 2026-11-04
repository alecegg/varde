#include <cmath>

/** Convert Celsius to Fahrenheit rounded to one place. */
double celsiusToFahrenheit(double celsius) {
    return std::round((celsius * 9.0 / 5.0 + 32.0) * 10.0) / 10.0;
}
