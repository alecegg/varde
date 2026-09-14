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
    let mut in_fence = false;
    let mut fence_marker = '`';
    let mut fence_len = 0usize;
    let mut line_start = 0usize;
    for line in body.split_inclusive('\n') {
        let line_end = line_start + line.len();
        let content = line.strip_suffix('\n').unwrap_or(line);
        let trimmed = content.trim_start();
        let marker = trimmed.chars().next();
        if !in_fence {
            if let Some(marker) = marker
                && (marker == '`' || marker == '~')
                && trimmed.chars().take_while(|&c| c == marker).count() >= 3
            {
                in_fence = true;
                fence_marker = marker;
                fence_len = trimmed.chars().take_while(|&c| c == marker).count();
                mask[line_start..line_end].fill(true);
                line_start = line_end;
                continue;
            }
        } else if marker == Some(fence_marker) {
            let run_len = trimmed.chars().take_while(|&c| c == fence_marker).count();
            let after_run = &trimmed[run_len..];
            if run_len >= fence_len && after_run.trim().is_empty() {
                in_fence = false;
                mask[line_start..line_end].fill(true);
                line_start = line_end;
                continue;
            }
        }
        if in_fence {
            mask[line_start..line_end].fill(true);
        } else {
            // Inline code spans (CommonMark): a span opens with a backtick
            // run of length N and closes with a run of exactly N backticks;
            // runs of other lengths inside are literal text.
            let bytes = line.as_bytes();
            let mut in_code = false;
            let mut open_len = 0usize;
            let mut i = 0;
            while i < bytes.len() {
                if bytes[i] == b'`' {
                    let mut j = i;
                    while j < bytes.len() && bytes[j] == b'`' {
                        j += 1;
                    }
                    let run = j - i;
                    if !in_code {
                        in_code = true;
                        open_len = run;
                    } else if run == open_len {
                        in_code = false;
                    }
                    i = j;
                } else {
                    if in_code {
                        mask[line_start + i] = true;
                    }
                    i += 1;
                }
            }
        }
        line_start = line_end;
    }
    mask
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
