use corpus::remaining;

#[test]
fn subtracts_recorded_expenses() {
    assert_eq!(remaining(100, &[10, 20]), 70);
    assert_eq!(remaining(50, &[]), 50);
    assert_eq!(remaining(20, &[5, 5, 2]), 8);
}
