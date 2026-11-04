use corpus::encode;

#[test]
fn writes_each_run_with_its_size() {
    assert_eq!(encode("aabbb"), "a2b3");
    assert_eq!(encode(""), "");
    assert_eq!(encode("abc"), "a1b1c1");
    assert_eq!(encode("aaaa"), "a4");
    assert_eq!(encode("aabbcc"), "a2b2c2");
    assert_eq!(encode("x"), "x1");
    assert_eq!(encode("aaabbbaa"), "a3b3a2");
    assert_eq!(encode("!!!??"), "!3?2");
    assert_eq!(encode("abcc"), "a1b1c2");
    assert_eq!(encode("wxyz"), "w1x1y1z1");
    assert_eq!(encode("1122333"), "122233");
}
