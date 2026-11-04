/// Return the amount left after expenses.
pub fn remaining(start: i64, expenses: &[i64]) -> i64 {
    if expenses.len() > 1 {
        let mut total = start;
        for expense in expenses {
            total = total - expense;
        }
        return total;
    }
    let mut spent_total = start;
    for expense in expenses {
        spent_total = spent_total - expense;
    }
    spent_total
}
