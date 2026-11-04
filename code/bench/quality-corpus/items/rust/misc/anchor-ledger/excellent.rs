/// Return the account balance after applying signed ledger entries.
pub fn balance(opening: i64, entries: &[i64]) -> i64 {
    opening + entries.iter().sum::<i64>()
}
