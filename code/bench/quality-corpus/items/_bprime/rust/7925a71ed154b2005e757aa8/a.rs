pub fn encode(text: &str) -> String {
    let mut result = String::new();
    let mut chars = text.chars().peekable();
    while let Some(symbol) = chars.next() {
        let mut count = 1;
        while chars.peek() == Some(&symbol) {
            chars.next();
            count += 1;
        }
        result.push(symbol);
        result.push_str(&count.to_string());
    }
    result
}
