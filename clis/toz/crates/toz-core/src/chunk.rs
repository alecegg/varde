//! Chunking: split a captured body into titled, line-addressed sections.
//!
//! Types, the fixed-window fallback and shared helpers live here; the content-aware strategies
//! (diff, JSON, markdown, test output, logs) are in `strategies.rs`.

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Chunk {
    pub ordinal: usize,
    pub title: String,
    /// 1-based, inclusive.
    pub line_start: usize,
    pub line_end: usize,
    pub content_type: ContentType,
    pub body: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ContentType {
    Code,
    Prose,
}

impl ContentType {
    pub fn as_str(self) -> &'static str {
        match self {
            ContentType::Code => "code",
            ContentType::Prose => "prose",
        }
    }
}

pub trait Chunker {
    fn chunk(&self, text: &str) -> Vec<Chunk>;
}

/// Fixed-size line windows with overlap. Title is the first non-blank line of the window.
pub struct FixedWindow {
    pub lines: usize,
    pub overlap: usize,
}

impl Default for FixedWindow {
    fn default() -> Self {
        Self {
            lines: 80,
            overlap: 10,
        }
    }
}

impl Chunker for FixedWindow {
    fn chunk(&self, text: &str) -> Vec<Chunk> {
        let lines: Vec<&str> = text.lines().collect();
        if lines.is_empty() {
            return Vec::new();
        }
        let step = self.lines.saturating_sub(self.overlap).max(1);
        let mut out = Vec::new();
        let mut start = 0;
        let mut ordinal = 0;
        while start < lines.len() {
            let end = (start + self.lines).min(lines.len());
            let slice = &lines[start..end];
            let body = slice.join("\n");
            out.push(Chunk {
                ordinal,
                title: title_for(slice),
                line_start: start + 1,
                line_end: end,
                content_type: classify(slice),
                body,
            });
            ordinal += 1;
            if end == lines.len() {
                break;
            }
            start += step;
        }
        out
    }
}

/// Chunk a body with the strategy its content sniffs as (see `strategies`).
pub fn chunk_default(text: &str) -> Vec<Chunk> {
    let strategy = crate::strategies::detect(text);
    crate::strategies::chunk_with(strategy, text)
}

/// Chunk a body per a matched profile, or the sniffed default when there is none.
pub fn chunk_for(text: &str, profile: Option<&crate::profile::Profile>) -> Vec<Chunk> {
    match profile {
        Some(p) => crate::strategies::chunk_with_profile(text, p),
        None => chunk_default(text),
    }
}

pub fn title_for(lines: &[&str]) -> String {
    let first = lines
        .iter()
        .map(|l| l.trim())
        .find(|l| !l.is_empty())
        .unwrap_or("");
    truncate(first, 72)
}

pub fn truncate(s: &str, max: usize) -> String {
    if s.chars().count() <= max {
        return s.to_string();
    }
    let mut out: String = s.chars().take(max.saturating_sub(1)).collect();
    out.push('…');
    out
}

/// Like `truncate` but keeps both ends, so breadcrumb leaves and `(n/m)` suffixes survive.
pub fn truncate_middle(s: &str, max: usize) -> String {
    let n = s.chars().count();
    if n <= max {
        return s.to_string();
    }
    let tail = max / 3;
    let head = max.saturating_sub(tail + 1);
    let mut out: String = s.chars().take(head).collect();
    out.push('…');
    out.extend(s.chars().skip(n - tail));
    out
}

/// Heuristic: a line "looks like code" if it has leading indentation plus a bracket/operator, or
/// ends in a code-ish delimiter. If > 40% of non-blank lines qualify, the chunk is code.
pub fn classify(lines: &[&str]) -> ContentType {
    let mut total = 0usize;
    let mut codeish = 0usize;
    for l in lines {
        let t = l.trim_end();
        if t.trim().is_empty() {
            continue;
        }
        total += 1;
        let indented = t.starts_with("  ") || t.starts_with('\t');
        let has_sym = t.contains(['{', '}', ';', '(', ')', '=', '[', ']']);
        let ends_code = t.ends_with(['{', '}', ';', ',', ')']);
        if (indented && has_sym) || ends_code {
            codeish += 1;
        }
    }
    if total > 0 && codeish * 10 > total * 4 {
        ContentType::Code
    } else {
        ContentType::Prose
    }
}

/// Strip ANSI CSI/OSC escape sequences.
pub fn strip_ansi(input: &str) -> String {
    let mut out = String::with_capacity(input.len());
    let mut chars = input.chars().peekable();
    while let Some(c) = chars.next() {
        if c != '\x1b' {
            out.push(c);
            continue;
        }
        skip_escape(&mut chars);
    }
    out
}

fn skip_escape(chars: &mut std::iter::Peekable<std::str::Chars<'_>>) {
    match chars.peek() {
        Some('[') => {
            chars.next();
            // CSI: parameters/intermediates then a final byte 0x40..=0x7E
            for n in chars.by_ref() {
                if ('\x40'..='\x7e').contains(&n) {
                    break;
                }
            }
        }
        Some(']') => {
            chars.next();
            skip_osc(chars);
        }
        Some(_) => {
            chars.next();
        }
        None => {}
    }
}

fn skip_osc(chars: &mut std::iter::Peekable<std::str::Chars<'_>>) {
    // OSC: until BEL or ST (ESC \)
    let mut prev = '\0';
    for n in chars.by_ref() {
        if n == '\x07' || (prev == '\x1b' && n == '\\') {
            break;
        }
        prev = n;
    }
}

/// True if the bytes look like binary rather than text.
pub fn looks_binary(bytes: &[u8]) -> bool {
    let sample = &bytes[..bytes.len().min(8192)];
    if sample.contains(&0) {
        return true;
    }
    let non_text = sample
        .iter()
        .filter(|&&b| b < 0x20 && !matches!(b, b'\n' | b'\r' | b'\t' | 0x1b | 0x0c | 0x08))
        .count();
    !sample.is_empty() && non_text * 100 / sample.len() > 5
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn windows_overlap_and_cover() {
        let text: String = (1..=200).map(|i| format!("line {i}\n")).collect();
        let chunks = FixedWindow {
            lines: 80,
            overlap: 10,
        }
        .chunk(&text);
        assert_eq!(chunks.len(), 3);
        assert_eq!((chunks[0].line_start, chunks[0].line_end), (1, 80));
        assert_eq!((chunks[1].line_start, chunks[1].line_end), (71, 150));
        assert_eq!((chunks[2].line_start, chunks[2].line_end), (141, 200));
        assert_eq!(chunks[1].title, "line 71");
    }

    #[test]
    fn small_input_single_chunk() {
        let chunks = chunk_default("a\nb\n");
        assert_eq!(chunks.len(), 1);
        assert_eq!(chunks[0].line_end, 2);
    }

    #[test]
    fn empty_input_no_chunks() {
        assert!(chunk_default("").is_empty());
    }

    #[test]
    fn truncate_middle_keeps_tail() {
        assert_eq!(truncate_middle("short", 10), "short");
        let t = truncate_middle("Guide > Development > Web application frameworks (3/9)", 30);
        assert_eq!(t.chars().count(), 30);
        assert!(t.ends_with("orks (3/9)"), "{t}");
        assert!(t.starts_with("Guide > "), "{t}");
    }

    #[test]
    fn strips_ansi() {
        assert_eq!(strip_ansi("\x1b[1;32mok\x1b[0m done"), "ok done");
        assert_eq!(strip_ansi("\x1b]0;title\x07text"), "text");
    }

    #[test]
    fn classify_code_vs_prose() {
        let code = ["fn main() {", "    let x = 1;", "}"];
        assert_eq!(classify(&code), ContentType::Code);
        let prose = [
            "The quick brown fox",
            "jumps over the lazy dog",
            "and runs away",
        ];
        assert_eq!(classify(&prose), ContentType::Prose);
    }

    #[test]
    fn binary_detection() {
        assert!(looks_binary(b"\x00\x01\x02abc"));
        assert!(!looks_binary(b"plain text\nwith lines\n"));
    }
}
