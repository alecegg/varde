//! Markdown link/code-fence parsing for `bundle_lint` (OKF v0.2 §6.1):
//! extracting bundle-internal link targets from Concept bodies while
//! skipping `](` markers that are literal text inside inline code spans or
//! fenced code blocks.
//!
//! Split out of `lint.rs` (per the `crud/` submodule pattern) so the
//! directory walk / orchestration in the parent file does not share a file
//! with the parsing state machine; a future edit to one concern cannot
//! accidentally affect the other.

/// The markdown inline-link marker `](` that separates link text from its
/// target (OKF v0.2 §6.1).
const LINK_MARKER: &str = "](";

/// Extract bundle-internal markdown link targets from a Concept body, per
/// OKF v0.2 §6.1: `[text](target)` forms, skipping external
/// (`http://`/`https://`) links, fragment-only (`#…`) references, images
/// (`![alt](…)`), and `](` markers inside inline code spans or fenced code
/// blocks (literal text, not links). Anchor fragments (`b.md#section`) and
/// angle-bracket targets (`<b.md>`) are stripped before resolving.
pub(crate) fn extract_links(body: &str) -> Vec<&str> {
    let mask = code_mask(body);
    let mut out = Vec::new();
    let mut i = 0;
    while let Some(rel) = body[i..].find(LINK_MARKER) {
        let start = i + rel;
        if mask[start] || is_image_link(body, start) {
            // Literal `](` inside code, or an image — not a link.
            i = start + LINK_MARKER.len();
            continue;
        }
        let target_start = start + LINK_MARKER.len();
        let rest = &body[target_start..];
        let end = rest.find(')').unwrap_or(rest.len());
        let mut target = &rest[..end];
        // Optional title form `path "title"`: cut at the title.
        if let Some(space) = target.find(' ')
            && target[space..].trim_start().starts_with('"')
        {
            target = &target[..space];
        }
        let target = target.trim();
        // Angle-bracket form `<path>` and anchor fragments `path#section`.
        let target = target
            .strip_prefix('<')
            .and_then(|t| t.strip_suffix('>'))
            .unwrap_or(target);
        let target = target.split('#').next().unwrap_or(target);
        let target = target.trim();
        if !target.is_empty()
            && !target.starts_with("http://")
            && !target.starts_with("https://")
            && !target.starts_with('#')
        {
            out.push(target);
        }
        i = target_start + end;
    }
    out
}

/// Whether the `](` marker at `marker_start` belongs to an image
/// (`![alt](…)`) rather than a link: walk back to the matching `[` of the
/// bracket pair and check whether it is preceded by `!`.
fn is_image_link(body: &str, marker_start: usize) -> bool {
    let mut depth = 0usize;
    for (idx, ch) in body[..marker_start].char_indices().rev() {
        match ch {
            ']' => depth += 1,
            '[' => {
                if depth == 0 {
                    return idx > 0 && body.as_bytes()[idx - 1] == b'!';
                }
                depth -= 1;
            }
            _ => {}
        }
    }
    false
}

/// Mark every byte position inside an inline code span (backtick-delimited)
/// or a fenced code block (```` ``` ```` or `~~~`), so link extraction can
/// skip `](` markers that are literal text.
///
/// Approximation, documented: a line whose content starts with 3+ backticks
/// or tildes opens a fenced block, closed by a line starting with a run of
/// at least the opening length followed only by whitespace (per CommonMark —
/// trailing non-whitespace content means the line is not a closer); a code
/// span left unclosed at the end of a line masks only that line. Over-masking
/// only risks missing a link; it never invents one.
fn code_mask(body: &str) -> Vec<bool> {
    let mut mask = vec![false; body.len()];
    let mut fence = FenceState::default();
    let mut line_start = 0usize;
    for line in body.split_inclusive('\n') {
        let line_end = line_start + line.len();
        if fence.mask_line(line) {
            mask[line_start..line_end].fill(true);
        } else {
            mask_inline_code(line, &mut mask[line_start..line_end]);
        }
        line_start = line_end;
    }
    mask
}

#[derive(Default)]
struct FenceState {
    marker: Option<char>,
    len: usize,
}

impl FenceState {
    fn mask_line(&mut self, line: &str) -> bool {
        let content = line.strip_suffix('\n').unwrap_or(line);
        let trimmed = content.trim_start();
        let marker = trimmed.chars().next();
        if let Some(open_marker) = self.marker {
            if marker == Some(open_marker) {
                let run_len = marker_run(trimmed, open_marker);
                if run_len >= self.len && trimmed[run_len..].trim().is_empty() {
                    self.marker = None;
                }
            }
            return true;
        }
        let Some(marker) = marker.filter(|value| matches!(value, '`' | '~')) else {
            return false;
        };
        let len = marker_run(trimmed, marker);
        if len < 3 {
            return false;
        }
        self.marker = Some(marker);
        self.len = len;
        true
    }
}

fn marker_run(value: &str, marker: char) -> usize {
    value.chars().take_while(|&ch| ch == marker).count()
}

fn mask_inline_code(line: &str, mask: &mut [bool]) {
    let bytes = line.as_bytes();
    let mut open_len = None;
    let mut index = 0;
    while index < bytes.len() {
        if bytes[index] != b'`' {
            mask[index] = open_len.is_some();
            index += 1;
            continue;
        }
        let mut end = index;
        while end < bytes.len() && bytes[end] == b'`' {
            end += 1;
        }
        let run = end - index;
        open_len = match open_len {
            None => Some(run),
            Some(len) if len == run => None,
            current => current,
        };
        index = end;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn closer_with_trailing_content_does_not_close_the_fence() {
        // A line that merely starts with a backtick run but has trailing
        // non-whitespace content (e.g. an info-string-like typo) is not a
        // valid CommonMark closer, so the fence — and the real link inside
        // it — must remain masked out.
        let body = "```\n``` stray text\n[real link](target.md)\n```\n";
        assert!(
            extract_links(body).is_empty(),
            "link before the true closer must stay masked"
        );
    }

    #[test]
    fn closer_with_trailing_whitespace_still_closes_the_fence() {
        let body = "```\ncode\n```   \n[real link](target.md)\n";
        assert_eq!(extract_links(body), vec!["target.md"]);
    }

    #[test]
    fn plain_closer_closes_the_fence() {
        let body = "```\ncode\n```\n[real link](target.md)\n";
        assert_eq!(extract_links(body), vec!["target.md"]);
    }
}
