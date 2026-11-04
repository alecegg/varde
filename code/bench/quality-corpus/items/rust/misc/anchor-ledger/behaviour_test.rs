use corpus::balance;

#[test]
fn applies_signed_entries() {
    assert_eq!(balance(10, &[5, -3]), 12);
    assert_eq!(balance(0, &[]), 0);
    assert_eq!(balance(100, &[-20, -30]), 50);
}
