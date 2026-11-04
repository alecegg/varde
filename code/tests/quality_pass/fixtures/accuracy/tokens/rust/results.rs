use std::collections::HashMap;

pub fn count_words(text: &str) -> HashMap<String, usize> {
    let mut counts = HashMap::new();
    for word in text.split_whitespace() {
        let key = word.to_lowercase();
        *counts.entry(key).or_insert(0) += 1;
    }
    counts
}

pub fn parse_value(raw: &str) -> Result<i64, String> {
    let trimmed = raw.trim();
    if trimmed.is_empty() {
        return Err("empty input".to_string());
    }
    trimmed
        .parse::<i64>()
        .map_err(|error| format!("bad number: {error}"))
}

pub fn first_positive(values: &[i64]) -> Option<i64> {
    values.iter().copied().find(|value| *value > 0)
}

pub fn sum_positive(values: &[i64]) -> i64 {
    values.iter().filter(|value| **value > 0).sum()
}
