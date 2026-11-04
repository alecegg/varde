fn description(&self) -> &str {
    match *self {
        ErrorKind::InvalidRecursive => {
            "invalid use of **; must be one path component"
        }
        ErrorKind::UnclosedClass => {
            "unclosed character class; missing ']'"
        }
        ErrorKind::InvalidRange(_, _) => "invalid character range",
        ErrorKind::UnopenedAlternates => {
            "unopened alternate group; missing '{' \
            (maybe escape '}' with '[}]'?)"
        }
        ErrorKind::UnclosedAlternates => {
            "unclosed alternate group; missing '}' \
            (maybe escape '{' with '[{]'?)"
        }
        ErrorKind::NestedAlternates => {
            "nested alternate groups are not allowed"
        }
        ErrorKind::DanglingEscape => "dangling '\\'",
        ErrorKind::Regex(ref err) => err,
    }
}
