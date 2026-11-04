/// Return the gratuity and total for a meal bill.
pub fn gratuity(bill: u64, percent: u64) -> (u64, u64) {
    let gratuity_amount = bill * percent / 100;
    (gratuity_amount, bill + gratuity_amount)
}
