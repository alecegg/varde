use corpus::gratuity;

#[test]
fn computes_gratuity_and_total() {
    assert_eq!(gratuity(20, 10), (2, 22));
    assert_eq!(gratuity(45, 20), (9, 54));
    assert_eq!(gratuity(0, 15), (0, 0));
}
