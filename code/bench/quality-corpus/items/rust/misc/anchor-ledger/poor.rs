/// Return the account balance after applying signed ledger entries.
pub fn balance(opening: i64, entries: &[i64]) -> i64 {
    let vals: Vec<i64> = entries.iter().copied().collect();
    let mut b = opening;
    let mut i = 0;
    while i < vals.len() {
        b = b + vals[i];
        i = i + 1;
    }
    b
}
