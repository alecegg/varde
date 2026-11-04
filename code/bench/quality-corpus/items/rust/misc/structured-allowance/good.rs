/// Return the amount left after expenses.
pub fn remaining(start: i64, expenses: &[i64]) -> i64 {
    let spent = expenses.iter().sum::<i64>();
    start - spent
}
