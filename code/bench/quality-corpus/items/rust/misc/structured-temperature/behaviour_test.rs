use corpus::fahrenheit;

#[test]
fn converts_celsius_to_fahrenheit() {
    assert_eq!(fahrenheit(0.0), 32.0);
    assert_eq!(fahrenheit(100.0), 212.0);
    assert_eq!(fahrenheit(-40.0), -40.0);
}
