pub fn title_case(text: &str) -> String {
    text.split(' ')
        .map(capitalised)
        .collect::<Vec<String>>()
        .join(" ")
}

fn capitalised(word: &str) -> String {
    let mut chars = word.chars();
    match chars.next() {
        Some(first) => first.to_uppercase().collect::<String>() + &chars.as_str().to_lowercase(),
        None => String::new(),
    }
}
