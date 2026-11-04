/// Convert Celsius to Fahrenheit rounded to one place.
pub fn fahrenheit(celsius: f64) -> f64 {
    let converted = celsius * 9.0 / 5.0 + 32.0;
    (converted * 10.0).round() / 10.0
}
