use corpus::title_case;

#[test]
fn capitalises_each_word() {
    assert_eq!(title_case("hello world"), "Hello World");
    assert_eq!(title_case("HELLO"), "Hello");
    assert_eq!(title_case(""), "");
    assert_eq!(title_case("a"), "A");
    assert_eq!(title_case("hELLO wORLD"), "Hello World");
    assert_eq!(title_case(" already spaced"), " Already Spaced");
    assert_eq!(title_case("one two three"), "One Two Three");
    assert_eq!(title_case("miXeD cAsE"), "Mixed Case");
    assert_eq!(title_case("1st place"), "1st Place");
    assert_eq!(title_case("x y z"), "X Y Z");
    assert_eq!(title_case("étoile bleue"), "Étoile Bleue");
}
