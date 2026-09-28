//! Distinctive-vocabulary hints for previews: the words most worth searching for in a capture.
//!
//! Scored like context-mode's `getDistinctiveTerms` (IDF across the capture's chunks, bonus for
//! identifier-looking tokens), restricted to words that appear in a few chunks but not most, so
//! the list points at *specific* content rather than boilerplate.

use std::collections::HashMap;

const STOPWORDS: &[&str] = &[
    "the", "and", "for", "are", "but", "not", "you", "all", "any", "can", "had", "her", "was",
    "one", "our", "out", "has", "have", "this", "that", "with", "from", "they", "will", "would",
    "there", "their", "what", "about", "which", "when", "make", "like", "time", "just", "into",
    "than", "them", "then", "these", "some", "could", "other", "also", "more", "most", "such",
    "only", "over", "very", "your", "each", "does", "done", "true", "false", "null", "none",
    "self", "let", "mut", "pub", "use", "const", "static", "return", "else", "while", "loop",
    "match", "impl", "struct", "enum", "type", "where", "async", "await", "move", "ref", "dyn",
    "string", "str", "int", "bool", "vec", "option", "result", "error", "warning", "info", "debug",
    "trace", "line", "lines", "file", "files", "new", "old", "get", "set", "value", "values",
    "name", "names", "key", "keys", "data", "item", "items", "list", "test", "tests", "running",
    "passed", "failed", "ignored", "measured", "filtered", "finished", "import", "export",
    "default", "function", "class", "def", "var", "end", "begin", "print", "println", "format",
    "todo", "fixme", "note", "see", "via", "per", "etc",
];

/// Top `max` terms for a capture split into `chunks` (each chunk's body).
pub fn distinctive(chunks: &[&str], max: usize) -> Vec<String> {
    if chunks.len() < 3 {
        return Vec::new();
    }
    let total = chunks.len() as f64;
    let min_docs = 2usize;
    let max_docs = ((chunks.len() as f64 * 0.4).ceil() as usize).max(3);
    let df = document_frequency(chunks);
    let mut scored: Vec<(String, f64)> = df
        .into_iter()
        .filter(|(_, n)| *n >= min_docs && *n <= max_docs)
        .map(|(w, n)| {
            let score = score_term(&w, n, total);
            (w, score)
        })
        .collect();
    scored.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap().then_with(|| a.0.cmp(&b.0)));
    // Case-insensitive dedup so `Error`/`error` don't both appear.
    let mut out: Vec<String> = Vec::new();
    let mut lower_seen = std::collections::HashSet::new();
    for (w, _) in scored {
        if lower_seen.insert(w.to_ascii_lowercase()) {
            out.push(w);
            if out.len() == max {
                break;
            }
        }
    }
    out
}

fn document_frequency(chunks: &[&str]) -> HashMap<String, usize> {
    let mut df: HashMap<String, usize> = HashMap::new();
    for body in chunks {
        let mut seen: std::collections::HashSet<String> = std::collections::HashSet::new();
        for word in body
            .split(|c: char| !(c.is_alphanumeric() || c == '_' || c == '-'))
            .filter(|w| w.len() >= 3 && w.len() <= 40)
        {
            let w = word.trim_matches('-');
            if w.len() < 3 || w.chars().all(|c| c.is_ascii_digit()) {
                continue;
            }
            let lower = w.to_ascii_lowercase();
            if STOPWORDS.contains(&lower.as_str()) {
                continue;
            }
            // Keep the original casing of identifiers so `SessionStart` reads as it appears.
            seen.insert(w.to_string());
        }
        for w in seen {
            *df.entry(w).or_default() += 1;
        }
    }
    df
}

fn score_term(w: &str, n: usize, total: f64) -> f64 {
    let idf = (total / n as f64).ln();
    let len_bonus = (w.len() as f64 / 20.0).min(0.5);
    let ident_bonus = if w.contains('_') || w.contains('-') {
        1.5
    } else if w.len() >= 12
        || w.chars().any(|c| c.is_ascii_uppercase()) && w.chars().any(|c| c.is_ascii_lowercase())
    {
        0.8
    } else {
        0.0
    };
    idf + len_bonus + ident_bonus
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn prefers_identifiers_that_appear_in_a_few_chunks() {
        let chunks = vec![
            "fn open_store() { let x = 1; }\nsome common words here",
            "fn open_store() called again\nsome common words here",
            "error: failed to bind socket_addr\nsome common words here",
            "warning: socket_addr reused\nsome common words here",
            "some common words here and nothing else",
            "some common words here and nothing else",
            "some common words here and nothing else",
            "some common words here and nothing else",
        ];
        let t = distinctive(&chunks, 5);
        assert!(t.contains(&"open_store".to_string()), "{t:?}");
        assert!(t.contains(&"socket_addr".to_string()), "{t:?}");
        assert!(
            !t.iter().any(|w| w == "common"),
            "boilerplate excluded: {t:?}"
        );
    }

    #[test]
    fn too_few_chunks_gives_nothing() {
        assert!(distinctive(&["a b c", "a b c"], 5).is_empty());
    }
}
