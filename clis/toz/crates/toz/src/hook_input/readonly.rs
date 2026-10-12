//! Classify shell commands that only read from the working tree, so the hook
//! gives them the 16 KiB read threshold instead of the Bash default.
//!
//! `is_readonly` feeds `is_file_read` in `commands.rs`. Shell syntax is parsed
//! conservatively: every top-level command must be a known read-only command,
//! and any redirection, command substitution, background job, or unrecognized
//! word fails open to the shell default.

/// True when every top-level command in `command` is read-only.
pub fn is_readonly(command: &str) -> bool {
    // `N>&M` duplicates a descriptor; it writes no file, so drop it before the
    // redirection scan. Anything else with `>`/`<` is a write (or input we
    // cannot vouch for) and fails open.
    let command = command.replace("2>&1", "");
    if command.contains("$(") || command.contains('`') {
        return false;
    }
    if command.contains('>') || command.contains('<') {
        return false;
    }
    let command = command.replace("&&", "\n").replace("||", "\n");
    if command.contains('&') {
        return false; // background job: it may outlive and write
    }
    command
        .split(|c| matches!(c, ';' | '|' | '\n'))
        .all(|segment| is_readonly_words(&segment.split_whitespace().collect::<Vec<_>>()))
}

/// Classify one already-split command (a `do`/`done` keyword or a command).
fn is_readonly_words(words: &[&str]) -> bool {
    let words = match words.first() {
        Some(&"do" | &"done") => &words[1..],
        _ => words,
    };
    let Some((&command, args)) = words.split_first() else {
        return true; // empty segment, or a bare `done`
    };
    match command {
        // A `for` header holds only the loop variable and its data; the body
        // commands are separate segments.
        "for" => true,
        // `while`/`until` conditions do run, so classify them as commands.
        "while" | "until" => is_readonly_words(args),
        // Harmless here: neither writes a file.
        "cd" | "echo" => true,
        "cat" | "head" | "tail" | "nl" | "grep" | "rg" | "ls" | "wc" => true,
        "sed" => {
            args.contains(&"-n")
                && !args.iter().any(|arg| {
                    arg.starts_with("-i")
                        || arg.starts_with("--in-place")
                        || is_sed_write_script(arg)
                })
        }
        "find" => !args.iter().any(|arg| is_find_write(arg)),
        "git" => git_subcommand_is_readonly(args),
        _ => false,
    }
}

/// A `sed` script argument that writes a file: a `w`/`W` command at a clause
/// boundary, or a `w` flag on a substitution (`s/.../.../w file`). Quotes and a
/// leading address are allowed; over-rejecting only lowers the threshold.
fn is_sed_write_script(script: &str) -> bool {
    let script = script.trim_matches(['\'', '"']);
    if script.contains("/w ") || script.ends_with("/w") {
        return true;
    }
    script.split([';', '\n']).any(|clause| {
        let clause = clause.trim_start_matches(|c: char| {
            c.is_ascii_digit() || matches!(c, '$' | ',' | '~' | '+' | '-')
        });
        matches!(clause.split_whitespace().next(), Some("w" | "W"))
    })
}

/// `find` primaries that run commands or delete/write files.
fn is_find_write(arg: &str) -> bool {
    matches!(
        arg,
        "-exec" | "-execdir" | "-ok" | "-okdir" | "-delete" | "-fls"
    ) || arg.starts_with("-fprint")
}

/// True when `args` name a read-only `git` subcommand. `git` may take
/// value-carrying options (`-C`, `-c`, ...) before the subcommand.
fn git_subcommand_is_readonly(args: &[&str]) -> bool {
    let mut index = 0;
    while index < args.len() {
        let arg = args[index];
        if matches!(arg, "-C" | "-c" | "--git-dir" | "--work-tree") {
            index += 2;
            continue;
        }
        if arg.starts_with('-') {
            index += 1;
            continue;
        }
        // `git diff --output=<file>` writes a file despite the read subcommand.
        return matches!(arg, "show" | "diff" | "log" | "status")
            && !args.iter().any(|option| option.starts_with("--output"));
    }
    false
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn read_only_pipelines_and_loops_are_readonly() {
        for command in [
            "grep -n x f | sed -n '1,40p'",
            "for f in a b; do sed -n '1,40p' \"$f\"; done",
            "git diff --stat; cat f",
            "cat a b",
            "cat f 2>&1",
            "cd /tmp && cat f",
            "git -C /tmp show HEAD",
        ] {
            assert!(is_readonly(command), "{command:?} should be read-only");
        }
    }

    #[test]
    fn every_listed_read_command_is_readonly() {
        for command in [
            "cat a",
            "head -5 a",
            "tail -5 a",
            "nl a",
            "sed -n '1p' a",
            "sed -n 's/a/b/p' a",
            "grep x a",
            "rg x",
            "ls -la",
            "wc -l a",
            "find . -name '*.rs'",
            "git show HEAD",
            "git diff",
            "git log --oneline",
            "git status",
        ] {
            assert!(is_readonly(command), "{command:?} should be read-only");
        }
    }

    #[test]
    fn writes_substitutions_and_unknown_commands_are_not_readonly() {
        for command in [
            "rm",
            "cargo build",
            "cat f > out",
            "cat f >> out",
            "cat $(ls)",
            "cat `ls`",
            "cat f &",
            "for f in *; do rm \"$f\"; done",
            "cat f | tee out",
            "git diff --output=out",
            "sed -i 's/a/b/' f",
            "sed -n --in-place 's/a/b/p' f",
            "sed -n 'w out' f",
            "sed -n '1,5w out' f",
            "sed -n 's/a/b/w out' f",
            "find . -exec rm {} ;",
            "find . -delete",
            "while rm x; do cat y; done",
        ] {
            assert!(!is_readonly(command), "{command:?} should not be read-only");
        }
    }
}
