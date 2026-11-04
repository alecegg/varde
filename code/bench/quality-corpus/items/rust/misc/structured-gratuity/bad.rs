fn g(a: u64, b: u64) -> u64 {
    a * b / 100
}

/// Return the gratuity and total for a meal bill.
pub fn gratuity(bill: u64, percent: u64) -> (u64, u64) {
    let x = g(bill, percent);
    let y = bill + x;
    (x, y)
}
