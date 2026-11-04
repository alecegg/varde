const SINGLE: usize = 1;

pub fn encode(text: &str) -> String {
    rendered(grouped(&units(text)))
}

fn units(text: &str) -> Vec<char> {
    text.chars().collect()
}

fn grouped(units: &[char]) -> Vec<(char, usize)> {
    let mut result = Vec::new();
    let mut index = 0;
    while index < units.len() {
        let (symbol, size) = take(units, index);
        result.push((symbol, size));
        index += size;
    }
    result
}

fn take(units: &[char], index: usize) -> (char, usize) {
    let symbol = units[index];
    let mut size = SINGLE;
    while repeats(units, index + size, symbol) {
        size += 1;
    }
    (symbol, size)
}

fn repeats(units: &[char], index: usize, symbol: char) -> bool {
    index < units.len() && units[index] == symbol
}

fn rendered(runs: Vec<(char, usize)>) -> String {
    runs.iter().map(|run| piece(*run)).collect()
}

fn piece(run: (char, usize)) -> String {
    format!("{}{}", run.0, count(run.1))
}

fn count(size: usize) -> String {
    size.to_string()
}
