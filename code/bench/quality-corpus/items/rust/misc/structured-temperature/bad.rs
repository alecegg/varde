/// Convert Celsius to Fahrenheit rounded to one place.
pub fn fahrenheit(celsius: f64) -> f64 {
    let mut value = celsius;
    let mut pending = "scale";
    if value < 0.0 {
        value = value * 9.0;
        pending = "divide";
    }
    if pending == "scale" {
        value = value * 9.0;
        pending = "divide";
    }
    if pending == "divide" {
        value = value / 5.0;
        pending = "offset";
    }
    if pending == "offset" {
        value = value + 32.0;
    }
    (value * 10.0).round() / 10.0
}
