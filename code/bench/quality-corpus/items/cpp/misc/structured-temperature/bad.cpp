#include <cmath>
#include <string>

/** Convert Celsius to Fahrenheit rounded to one place. */
double celsiusToFahrenheit(double celsius) {
    double value = celsius;
    std::string stage = "scale";
    if (celsius < 0) {
        value = value * 9.0;
        stage = "divide";
    }
    if (stage == "scale") {
        value = value * 9.0;
        stage = "divide";
    }
    if (stage == "divide") {
        value = value / 5.0;
        stage = "offset";
    }
    if (stage == "offset") {
        value = value + 32.0;
    }
    return std::round(value * 10.0) / 10.0;
}
