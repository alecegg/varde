const SPACE: char = ' ';
const JOINER: &str = " ";
const NO_TEXT: &str = "";
const ONE: usize = 1;

pub fn title_case(text: &str) -> String {
    joined(
        words(text)
            .iter()
            .map(|word| capitalised(word))
            .collect(),
    )
}

fn words(text: &str) -> Vec<&str> {
    text.split(SPACE).collect()
}

fn capitalised(word: &str) -> String {
    match first(word) {
        Some(head) => attach(upper(head), rest(word)),
        None => empty(),
    }
}

fn first(word: &str) -> Option<char> {
    word.chars().next()
}

fn rest(word: &str) -> String {
    lowered(skipped(word))
}

fn skipped(word: &str) -> String {
    word.chars().skip(ONE).collect()
}

fn upper(head: char) -> String {
    head.to_uppercase().collect()
}

fn lowered(text: String) -> String {
    text.to_lowercase()
}

fn attach(head: String, tail: String) -> String {
    head + &tail
}

fn joined(parts: Vec<String>) -> String {
    parts.join(JOINER)
}

fn empty() -> String {
    NO_TEXT.to_string()
}
