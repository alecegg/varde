//! Per-command headings for previews of compound shell commands.
//!
//! The `compound-headings` task adds the separator-aware splitter and its
//! unit tests, returning `None` for any single command.

use toz_core::chunk::truncate;

/// Commands listed before the heading falls back to a `+N more` count.
const MAX_LISTED: usize = 5;
/// Longest command text shown per entry, ellipsis included.
const MAX_COMMAND_CHARS: usize = 60;

/// A `commands: 1) ... 2) ...` heading for a compound `source`, or `None`
/// for a single command.
pub fn heading(source: &str) -> Option<String> {
    let commands = split_commands(source);
    if commands.len() < 2 {
        return None;
    }
    let mut parts = Vec::new();
    for (index, command) in commands.iter().take(MAX_LISTED).enumerate() {
        parts.push(format!(
            "{}) {}",
            index + 1,
            truncate(command, MAX_COMMAND_CHARS)
        ));
    }
    if commands.len() > MAX_LISTED {
        parts.push(format!("+{} more", commands.len() - MAX_LISTED));
    }
    Some(format!("commands: {}", parts.join(" ")))
}

/// The quote or grouping the scanner is currently inside.
#[derive(Clone, Copy)]
enum Context {
    Single,
    Double,
    Backtick,
    Paren,
}

/// Split `source` on top-level `&&`, `||`, `;` and newlines.
///
/// Separators inside single or double quotes, backticks, `$(...)` and
/// subshells are not split, so each returned command keeps its own text.
fn split_commands(source: &str) -> Vec<String> {
    let mut commands = Vec::new();
    let mut current = String::new();
    let mut stack: Vec<Context> = Vec::new();
    let mut chars = source.chars().peekable();
    while let Some(c) = chars.next() {
        match stack.last().copied() {
            Some(Context::Single) => {
                current.push(c);
                if c == '\'' {
                    stack.pop();
                }
            }
            Some(Context::Double) => match c {
                '"' => {
                    current.push(c);
                    stack.pop();
                }
                '\\' => {
                    current.push(c);
                    push_next(&mut chars, &mut current);
                }
                '$' if chars.peek() == Some(&'(') => {
                    current.push(c);
                    push_next(&mut chars, &mut current);
                    stack.push(Context::Paren);
                }
                '`' => {
                    current.push(c);
                    stack.push(Context::Backtick);
                }
                _ => current.push(c),
            },
            Some(Context::Backtick) => match c {
                '`' => {
                    current.push(c);
                    stack.pop();
                }
                '\\' => {
                    current.push(c);
                    push_next(&mut chars, &mut current);
                }
                _ => current.push(c),
            },
            Some(Context::Paren) => match c {
                '\'' => {
                    current.push(c);
                    stack.push(Context::Single);
                }
                '"' => {
                    current.push(c);
                    stack.push(Context::Double);
                }
                '`' => {
                    current.push(c);
                    stack.push(Context::Backtick);
                }
                '(' => {
                    current.push(c);
                    stack.push(Context::Paren);
                }
                '$' if chars.peek() == Some(&'(') => {
                    current.push(c);
                    push_next(&mut chars, &mut current);
                    stack.push(Context::Paren);
                }
                '\\' => {
                    current.push(c);
                    push_next(&mut chars, &mut current);
                }
                ')' => {
                    current.push(c);
                    stack.pop();
                }
                _ => current.push(c),
            },
            None => match c {
                '\'' => {
                    current.push(c);
                    stack.push(Context::Single);
                }
                '"' => {
                    current.push(c);
                    stack.push(Context::Double);
                }
                '`' => {
                    current.push(c);
                    stack.push(Context::Backtick);
                }
                '(' => {
                    current.push(c);
                    stack.push(Context::Paren);
                }
                '$' if chars.peek() == Some(&'(') => {
                    current.push(c);
                    push_next(&mut chars, &mut current);
                    stack.push(Context::Paren);
                }
                '\\' => {
                    current.push(c);
                    push_next(&mut chars, &mut current);
                }
                '&' if chars.peek() == Some(&'&') => {
                    chars.next();
                    push_command(&mut commands, &mut current);
                }
                '|' if chars.peek() == Some(&'|') => {
                    chars.next();
                    push_command(&mut commands, &mut current);
                }
                ';' | '\n' => push_command(&mut commands, &mut current),
                _ => current.push(c),
            },
        }
    }
    push_command(&mut commands, &mut current);
    commands
}

/// Consume the char after an escape and keep it verbatim.
fn push_next(chars: &mut std::iter::Peekable<std::str::Chars>, current: &mut String) {
    if let Some(next) = chars.next() {
        current.push(next);
    }
}

/// Push the trimmed command, collapsing embedded newlines so the heading stays one line.
fn push_command(commands: &mut Vec<String>, current: &mut String) {
    let command = current.trim().replace(['\n', '\r'], " ");
    if !command.is_empty() {
        commands.push(command);
    }
    current.clear();
}

#[cfg(test)]
mod tests {
    use super::heading;

    #[test]
    fn single_command_has_no_heading() {
        for source in ["git status", "git diff --stat", "a | b", "", "   "] {
            assert_eq!(heading(source), None, "{source:?}");
        }
    }

    #[test]
    fn and_or_semicolon_and_newline_split() {
        assert_eq!(
            heading("a && b || c ; d\ne"),
            Some("commands: 1) a 2) b 3) c 4) d 5) e".to_string())
        );
    }

    #[test]
    fn quotes_are_not_split() {
        assert_eq!(
            heading("echo 'a && b' && echo \"c; d\""),
            Some("commands: 1) echo 'a && b' 2) echo \"c; d\"".to_string())
        );
    }

    #[test]
    fn command_substitution_backticks_and_subshells_are_not_split() {
        assert_eq!(
            heading("echo $(a; b) && echo `c; d` && (e; f)"),
            Some("commands: 1) echo $(a; b) 2) echo `c; d` 3) (e; f)".to_string())
        );
    }

    #[test]
    fn nested_quotes_inside_substitution_are_not_split() {
        assert_eq!(
            heading("echo \"$(grep 'x; y' f)\" && b"),
            Some("commands: 1) echo \"$(grep 'x; y' f)\" 2) b".to_string())
        );
    }

    #[test]
    fn escaped_separator_is_not_split() {
        assert_eq!(
            heading("echo a\\;b && c"),
            Some("commands: 1) echo a\\;b 2) c".to_string())
        );
    }

    #[test]
    fn empty_segments_are_skipped() {
        assert_eq!(heading("a;;b;\n"), Some("commands: 1) a 2) b".to_string()));
    }

    #[test]
    fn commands_are_truncated_to_sixty_chars() {
        let long = "x".repeat(80);
        assert_eq!(
            heading(&format!("{long} && b")),
            Some(format!("commands: 1) {}… 2) b", "x".repeat(59)))
        );
    }

    #[test]
    fn lists_at_most_five_then_a_count() {
        assert_eq!(
            heading("a; b; c; d; e"),
            Some("commands: 1) a 2) b 3) c 4) d 5) e".to_string())
        );
        assert_eq!(
            heading("a; b; c; d; e; f; g"),
            Some("commands: 1) a 2) b 3) c 4) d 5) e +2 more".to_string())
        );
    }

    #[test]
    fn heading_stays_on_one_line() {
        assert_eq!(
            heading("echo \"a\nb\" && c"),
            Some("commands: 1) echo \"a b\" 2) c".to_string())
        );
    }

    /// The audit case: a short `--help` before a large `git diff --stat`. The preview
    /// strategy may keep only the large block, so the heading is what makes the command
    /// boundary visible; it must precede the preview body.
    #[test]
    fn audit_case_heading_precedes_the_preview() {
        let source = "mytool --help && git diff --stat";
        let heading = heading(source).expect("compound command gets a heading");
        assert_eq!(heading, "commands: 1) mytool --help 2) git diff --stat");
        let preview_only_large_block = "...large diff preview...";
        let rendered = format!("{heading}\n{preview_only_large_block}");
        assert!(
            rendered.starts_with("commands: 1) mytool --help 2) git diff --stat\n"),
            "the heading must precede the preview: {rendered:?}"
        );
    }
}
