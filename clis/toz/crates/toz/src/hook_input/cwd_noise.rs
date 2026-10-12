//! Strip the harness working-directory reset line from hook result text.
//!
//! Claude Code appends a `Shell cwd was reset to <dir>` note to the Bash
//! tool's stderr whenever a command leaves the shell in a different directory.
//! It repeats on almost every captured call, so the hook drops it before
//! measuring or rendering. Both carriers are stripped; the test below anchors
//! the carrier to a recorded PostToolUse payload, which shows the note on
//! stderr, preceded by a newline.

/// Start of a harness noise line; `^Shell cwd was reset to .*$`.
const NOISE_PREFIX: &str = "Shell cwd was reset to ";

/// Return `text` with harness noise lines removed.
///
/// Whole lines starting with [`NOISE_PREFIX`] are dropped with their line
/// terminator; every other byte is preserved. Text whose only content is such
/// lines becomes empty, with no leftover newline.
pub fn strip(text: &str) -> String {
    if !text.contains(NOISE_PREFIX) {
        return text.to_string();
    }
    let mut stripped = String::with_capacity(text.len());
    for segment in text.split_inclusive('\n') {
        let (content, terminator) = match segment.strip_suffix('\n') {
            Some(content) => (content, "\n"),
            None => (segment, ""),
        };
        let line = content.strip_suffix('\r').unwrap_or(content);
        if line.starts_with(NOISE_PREFIX) {
            continue;
        }
        stripped.push_str(content);
        stripped.push_str(terminator);
    }
    if stripped.chars().all(|c| c == '\n' || c == '\r') {
        String::new()
    } else {
        stripped
    }
}

#[cfg(test)]
mod tests {
    use super::strip;

    /// Recorded Claude Code PostToolUse `tool_response.stderr`: the reset note
    /// arrives on stderr, preceded by the newline the harness adds.
    const RECORDED_STDERR: &str = "\nShell cwd was reset to /tmp/project";

    #[test]
    fn recorded_stderr_carrier_is_emptied() {
        assert_eq!(strip(RECORDED_STDERR), "");
    }

    #[test]
    fn line_alone_is_empty() {
        assert_eq!(strip("Shell cwd was reset to /tmp/reset-dir"), "");
    }

    #[test]
    fn keeps_other_lines_byte_identical() {
        let text = "build output ok\nShell cwd was reset to /tmp\nwarning: unused variable x\n";
        assert_eq!(strip(text), "build output ok\nwarning: unused variable x\n");
    }

    #[test]
    fn removes_every_occurrence() {
        let text = "Shell cwd was reset to /a\nShell cwd was reset to /b\n";
        assert_eq!(strip(text), "");
    }

    #[test]
    fn removes_crlf_line() {
        let text = "first\r\nShell cwd was reset to /tmp\r\nsecond";
        assert_eq!(strip(text), "first\r\nsecond");
    }

    #[test]
    fn leaves_text_without_the_line_unchanged() {
        assert_eq!(strip("no noise here\n\n"), "no noise here\n\n");
        assert_eq!(strip(""), "");
        assert_eq!(strip("\n\n"), "\n\n");
    }

    #[test]
    fn keeps_a_line_that_merely_contains_the_phrase() {
        let text = "echo Shell cwd was reset to /tmp";
        assert_eq!(strip(text), text);
    }
}
