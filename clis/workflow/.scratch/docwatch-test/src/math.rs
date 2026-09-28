pub fn q3_revenue() -> i64 {
    // base 100k, growth 12% each of 3 months
    let base = 100_000;
    let mut total = 0;
    let mut month = base;
    for _ in 0..3 {
        month = month * 112 / 100;
        total += month;
    }
    total
}
