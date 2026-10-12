//! Decide whether a shell command already bounds its own output.
//!
//! `is_scoped` looks at the last segment of a compound command (`&&`, `;`,
//! `||`, newline) and the last stage of its pipeline: when that stage is a
//! bounding program (`head`, `tail`, `grep`, `rg`, `wc`, `cut`, `awk`), or a
//! program whose own flags bound output (`sed -n`, `git log -n 5`), the hook
//! passes the result through instead of capturing it.
//!
//! Every uncertainty fails open (returns false, so the result is captured as
//! today): command substitution, redirections to or from files, a background
//! `&`, or unbalanced quotes. The hook's 64 KiB inline cap is unchanged; the
//! capture path still applies it to anything this returns false for.

/// True when `source`'s command already limits its output, so the hook passes
/// it through instead of capturing it.
pub fn is_scoped(source: &str) -> bool {
    if has_doubt(source) {
        return false;
    }
    let Some(last_segment) = after_last_separator(source, &[";", "\n", "&&", "||"]) else {
        return false;
    };
    let Some(last_stage) = after_last_separator(last_segment, &["|"]) else {
        return false;
    };
    let Some(words) = split_words(last_stage) else {
        return false;
    };
    bounds_output(&words)
}

/// Programs whose ordinary output is already a bounded summary.
const BOUNDING_PROGRAMS: [&str; 7] = ["head", "tail", "grep", "rg", "wc", "cut", "awk"];

fn bounds_output(words: &[String]) -> bool {
    let Some((program, args)) = words.split_first() else {
        return false;
    };
    let program = program.rsplit('/').next().unwrap_or(program);
    if BOUNDING_PROGRAMS.contains(&program) {
        return true;
    }
    match program {
        "sed" => args.iter().any(|arg| arg == "-n"),
        "git" => git_args_bound_output(args),
        _ => false,
    }
}

/// `git log` bounds its output with `-n 5`, `-5` or `--max-count=5`; other
/// git subcommands use those flags for something else.
fn git_args_bound_output(args: &[String]) -> bool {
    let Some(subcommand) = args.iter().position(|arg| !arg.starts_with('-')) else {
        return false;
    };
    if args.get(subcommand).map(String::as_str) != Some("log") {
        return false;
    }
    args[subcommand + 1..].iter().any(|arg| {
        arg == "-n"
            || arg == "--max-count"
            || arg.starts_with("--max-count=")
            || (arg.starts_with('-')
                && arg.len() > 1
                && arg[1..].chars().all(|c| c.is_ascii_digit()))
    })
}

/// True when the command form is too uncertain to classify: command
/// substitution, a redirection to or from a file, a background `&`, or
/// unbalanced quotes.
fn has_doubt(source: &str) -> bool {
    let bytes = source.as_bytes();
    let mut quote: Option<u8> = None;
    let mut i = 0;
    while i < bytes.len() {
        let c = bytes[i];
        if let Some(q) = quote {
            if c == b'\\' && q == b'"' {
                i += 2;
                continue;
            }
            if q == b'"' && (c == b'`' || (c == b'$' && bytes.get(i + 1) == Some(&b'('))) {
                return true;
            }
            if c == q {
                quote = None;
            }
            i += 1;
            continue;
        }
        match c {
            b'\'' | b'"' => {
                quote = Some(c);
                i += 1;
            }
            b'\\' => i += 2,
            b'$' if bytes.get(i + 1) == Some(&b'(') => return true,
            b'`' => return true,
            b'<' | b'>' => return true,
            b'&' => {
                if bytes.get(i + 1) == Some(&b'&') {
                    i += 2;
                } else {
                    return true;
                }
            }
            _ => i += 1,
        }
    }
    quote.is_some()
}

/// The part of `text` after the last top-level occurrence of any separator,
/// ignoring separators inside quotes. `None` when quotes are unbalanced.
fn after_last_separator<'a>(text: &'a str, separators: &[&str]) -> Option<&'a str> {
    let bytes = text.as_bytes();
    let mut quote: Option<u8> = None;
    let mut last = 0;
    let mut i = 0;
    while i < bytes.len() {
        let c = bytes[i];
        if let Some(q) = quote {
            if c == b'\\' && q == b'"' {
                i += 2;
                continue;
            }
            if c == q {
                quote = None;
            }
            i += 1;
            continue;
        }
        if c == b'\'' || c == b'"' {
            quote = Some(c);
            i += 1;
            continue;
        }
        if c == b'\\' {
            i += 2;
            continue;
        }
        match separators
            .iter()
            .find(|separator| bytes[i..].starts_with(separator.as_bytes()))
        {
            Some(separator) => {
                i += separator.len();
                last = i;
            }
            None => i += 1,
        }
    }
    if quote.is_some() {
        return None;
    }
    Some(&text[last..])
}

/// Split `stage` into shell words with quotes removed. `None` when quotes are
/// unbalanced.
fn split_words(stage: &str) -> Option<Vec<String>> {
    let mut words = Vec::new();
    let mut current = String::new();
    let mut in_word = false;
    let mut quote: Option<char> = None;
    let mut chars = stage.chars().peekable();
    while let Some(c) = chars.next() {
        if let Some(q) = quote {
            if c == q {
                quote = None;
            } else if c == '\\' && q == '"' {
                if matches!(chars.peek(), Some('"' | '\\')) {
                    current.push(chars.next().unwrap());
                } else {
                    current.push('\\');
                }
            } else {
                current.push(c);
            }
            continue;
        }
        match c {
            '\'' | '"' => {
                quote = Some(c);
                in_word = true;
            }
            '\\' => {
                current.push(chars.next()?);
                in_word = true;
            }
            _ if c.is_whitespace() => {
                if in_word {
                    words.push(std::mem::take(&mut current));
                    in_word = false;
                }
            }
            _ => {
                current.push(c);
                in_word = true;
            }
        }
    }
    if quote.is_some() {
        return None;
    }
    if in_word {
        words.push(current);
    }
    Some(words)
}

#[cfg(test)]
mod tests {
    use super::is_scoped;

    #[test]
    fn programs_that_bound_their_own_output_are_scoped() {
        for source in [
            "head -40",
            "tail -5",
            "grep x f",
            "rg pattern",
            "wc -l",
            "cut -d: -f1",
            "awk '{print $1}'",
            "/usr/bin/head -40",
            "cat f | head -40",
            "cat f | grep x",
        ] {
            assert!(is_scoped(source), "{source:?} bounds its own output");
        }
    }

    #[test]
    fn unbounded_commands_are_not_scoped() {
        for source in [
            "cat f",
            "cargo build",
            "echo hi",
            "sed 's/a/b/' f",
            "ls -l",
            "head -40 | cat f",
            "",
            "   ",
        ] {
            assert!(!is_scoped(source), "{source:?} does not bound its output");
        }
    }

    #[test]
    fn sed_bounds_output_only_with_n() {
        assert!(is_scoped("sed -n '1,40p' f"));
        assert!(is_scoped("cat f | sed -n '1,40p'"));
        assert!(!is_scoped("sed 's/a/b/' f"));
    }

    #[test]
    fn bounding_flags_count_only_for_programs_that_bound_with_them() {
        for source in [
            "git log -n 5",
            "git log -5",
            "git log --max-count=5",
            "rg -m 3 x",
            "rg --max-count 5 x",
        ] {
            assert!(is_scoped(source), "{source:?} bounds its own output");
        }
        for source in [
            "cat -n bigfile",
            "ls -n",
            "journalctl -n 50",
            "mkdir -m 755 d",
        ] {
            assert!(!is_scoped(source), "{source:?} does not bound its output");
        }
        // The flag must be on the final stage, not an earlier one.
        assert!(!is_scoped("git log -n 5 | cat"));
    }

    #[test]
    fn compound_commands_use_their_last_segment() {
        assert!(is_scoped("cd /tmp && ls -la | head -50"));
        assert!(is_scoped("echo start; cat f | grep x"));
        assert!(is_scoped("cat f | head || tail -5"));
        assert!(is_scoped("printf a\ncat f | head"));
        assert!(!is_scoped("cat f | head && cat g"));
        assert!(!is_scoped("tail -5; cat g"));
    }

    #[test]
    fn separators_inside_quotes_do_not_split() {
        assert!(is_scoped("grep 'a|b' f"));
        assert!(is_scoped("grep \"a;b\" f | head"));
        assert!(!is_scoped("echo 'a|b'"));
        assert!(!is_scoped("echo 'a>b'"));
    }

    #[test]
    fn doubt_fails_open() {
        for source in [
            "echo $(date) | head",
            "echo `date` | head",
            "echo \"$(date)\" | head",
            "cat f > out | head",
            "cat f >> out | head",
            "cat f 2>&1 | head",
            "head < f",
            "grep 'unclosed | head",
            "echo \"unclosed | head",
            "head -40 &",
        ] {
            assert!(
                !is_scoped(source),
                "{source:?} is ambiguous, so capture as today"
            );
        }
    }
}
