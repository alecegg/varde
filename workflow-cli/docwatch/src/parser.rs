//! Trigger-tag parser for markdown text.
//!
//! Detects unresolved `@c:` / `@cx:` trigger lines while skipping lines that
//! are already resolved (followed — possibly after blank lines — by a
//! `@c-reply:`/`@cx-reply:` marker, or ending in ` [done]`), and skipping any
//! line inside an open fenced code block (` ``` `) or inside a blockquote
//! (`>`).
//!
//! Conceptually matches the pattern:
//! `^(?P<indent>\s*)@(?P<agent>c|cx):\s*(?P<prompt>.+)$`

/// Which agent a trigger tag addresses.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Agent {
    /// `@c:` — Claude.
    Claude,
    /// `@cx:` — Codex.
    Codex,
}

impl Agent {
    /// The short tag string (`c` / `cx`) this agent corresponds to in
    /// trigger lines, reply markers, and error markers.
    pub fn tag(self) -> &'static str {
        match self {
            Agent::Claude => "c",
            Agent::Codex => "cx",
        }
    }
}

/// A single unresolved trigger found while scanning text.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PendingTask {
    pub agent: Agent,
    pub line_number: usize,
    pub indent: String,
    pub prompt: String,
}

/// Try to match a trigger tag at the start of a line (after leading
/// whitespace), returning the captured indent, agent, and prompt.
fn match_trigger(line: &str) -> Option<(String, Agent, String)> {
    let trimmed_start = line.trim_start_matches([' ', '\t']);
    let indent_len = line.len() - trimmed_start.len();
    let indent = &line[..indent_len];

    let rest = trimmed_start.strip_prefix('@')?;
    let (agent, rest) = if let Some(r) = rest.strip_prefix("cx:") {
        (Agent::Codex, r)
    } else {
        (Agent::Claude, rest.strip_prefix("c:")?)
    };

    let prompt = rest.trim_start_matches(' ');
    if prompt.is_empty() {
        return None;
    }

    Some((indent.to_string(), agent, prompt.to_string()))
}

/// A line is already resolved if it looks like a `-reply:` marker itself,
/// or if its content ends with ` [done]`.
fn is_resolved_marker(line: &str) -> bool {
    let trimmed = line.trim_start();
    trimmed.starts_with("@c-reply:") || trimmed.starts_with("@cx-reply:")
}

fn ends_with_done(line: &str) -> bool {
    line.trim_end().ends_with(" [done]")
}

/// Scan markdown text for unresolved `@c:`/`@cx:` trigger lines.
///
/// Skips lines inside fenced code blocks (delimited by ` ``` `), lines
/// inside blockquotes (lines starting with optional whitespace then `>`),
/// lines immediately followed by a `-reply:` marker line, and lines ending
/// in ` [done]`.
pub fn scan(text: &str) -> Vec<PendingTask> {
    let lines: Vec<&str> = text.lines().collect();
    let mut results = Vec::new();
    let mut in_fence = false;

    for (idx, line) in lines.iter().enumerate() {
        let trimmed = line.trim_start();

        if trimmed.starts_with("```") {
            in_fence = !in_fence;
            continue;
        }

        if in_fence {
            continue;
        }

        if trimmed.starts_with('>') {
            continue;
        }

        if ends_with_done(line) {
            continue;
        }

        let Some((indent, agent, prompt)) = match_trigger(line) else {
            continue;
        };

        // Resolved if the *next* non-empty line is a reply marker.
        let resolved = lines[idx + 1..]
            .iter()
            .find(|line| !line.trim().is_empty())
            .is_some_and(|line| is_resolved_marker(line));
        if resolved {
            continue;
        }

        results.push(PendingTask {
            agent,
            line_number: idx + 1,
            indent,
            prompt,
        });
    }

    results
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn detects_unresolved_c_trigger() {
        let text = "@c: what should we do here?\n";
        let found = scan(text);
        assert_eq!(found.len(), 1);
        assert_eq!(found[0].agent, Agent::Claude);
        assert_eq!(found[0].line_number, 1);
        assert_eq!(found[0].indent, "");
        assert_eq!(found[0].prompt, "what should we do here?");
    }

    #[test]
    fn detects_unresolved_cx_trigger() {
        let text = "@cx: run the migration\n";
        let found = scan(text);
        assert_eq!(found.len(), 1);
        assert_eq!(found[0].agent, Agent::Codex);
        assert_eq!(found[0].prompt, "run the migration");
    }

    #[test]
    fn skips_trigger_resolved_by_reply_marker() {
        let text = "@c: is this ok?\n@c-reply: yes, looks good\n";
        let found = scan(text);
        assert!(found.is_empty(), "expected no pending tasks, got {found:?}");
    }

    #[test]
    fn skips_trigger_resolved_by_cx_reply_marker() {
        let text = "@cx: is this ok?\n@cx-reply: yes\n";
        let found = scan(text);
        assert!(found.is_empty());
    }

    #[test]
    fn skips_trigger_resolved_by_reply_marker_after_blank_lines() {
        // Regression test: a blank line separating the trigger from its
        // reply must not make the trigger look unresolved.
        let text = "@c: is this ok?\n\n@c-reply: yes, looks good\n";
        let found = scan(text);
        assert!(found.is_empty(), "expected no pending tasks, got {found:?}");
    }

    #[test]
    fn skips_trigger_resolved_by_reply_marker_after_multiple_blank_lines() {
        let text = "@cx: is this ok?\n\n\n\n@cx-reply: yes\n";
        let found = scan(text);
        assert!(found.is_empty(), "expected no pending tasks, got {found:?}");
    }

    #[test]
    fn does_not_resolve_across_unrelated_content() {
        // A blank line followed by non-reply content must not be mistaken
        // for resolution.
        let text = "@c: is this ok?\n\nsome unrelated follow-up note\n";
        let found = scan(text);
        assert_eq!(found.len(), 1, "expected the trigger to remain pending");
    }

    #[test]
    fn error_marker_is_never_matched_as_a_trigger() {
        // Pins the loop-termination invariant `write_error_line` in
        // docwatch::watcher relies on: rewriting a trigger to
        // `@<tag>-error:` must never be re-scanned as a new pending
        // trigger, or the retry cycle would never terminate.
        let text = "@c-error: something went wrong\n@cx-error: also failed\n";
        let found = scan(text);
        assert!(found.is_empty(), "expected no pending tasks, got {found:?}");
    }

    #[test]
    fn skips_trigger_ending_in_done_marker() {
        let text = "@c: already handled [done]\n";
        let found = scan(text);
        assert!(found.is_empty());
    }

    #[test]
    fn skips_trigger_inside_fenced_code_block() {
        let text = "```\n@cx: this is just an example, not a real trigger\n```\n";
        let found = scan(text);
        assert!(found.is_empty(), "expected no pending tasks, got {found:?}");
    }

    #[test]
    fn detects_trigger_after_fence_closes() {
        let text = "```\nexample\n```\n@c: real trigger after the fence\n";
        let found = scan(text);
        assert_eq!(found.len(), 1);
        assert_eq!(found[0].prompt, "real trigger after the fence");
    }

    #[test]
    fn skips_trigger_inside_blockquote() {
        let text = "> @cx: quoted, not a live trigger\n";
        let found = scan(text);
        assert!(found.is_empty());
    }

    #[test]
    fn detects_indented_trigger_in_list_not_in_fence() {
        let text = "- some list item\n  @c: nested question in a list\n";
        let found = scan(text);
        assert_eq!(found.len(), 1);
        assert_eq!(found[0].indent, "  ");
        assert_eq!(found[0].prompt, "nested question in a list");
    }

    #[test]
    fn captures_multiline_mentions_with_correct_line_numbers() {
        let text = "intro line\n@c: first question\nsome other content\n@cx: second question\n";
        let found = scan(text);
        assert_eq!(found.len(), 2);
        assert_eq!(found[0].line_number, 2);
        assert_eq!(found[1].line_number, 4);
    }
}
