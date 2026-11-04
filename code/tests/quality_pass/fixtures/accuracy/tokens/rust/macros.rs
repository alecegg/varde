macro_rules! double {
    ($value:expr) => {
        $value * 2
    };
}

pub fn describe(name: &str, value: i64) -> String {
    format!("{}={}", name, double!(value))
}

pub fn report(values: &[i64]) -> String {
    let rendered = values
        .iter()
        .map(|value| value.to_string())
        .collect::<Vec<_>>()
        .join(",");
    println!("values: {}", rendered);
    assert!(!rendered.is_empty());
    rendered
}

pub fn thresholds() -> Vec<i64> {
    let raw = r"10,20,30";
    raw.split(',')
        .filter_map(|part| part.parse::<i64>().ok())
        .collect()
}
