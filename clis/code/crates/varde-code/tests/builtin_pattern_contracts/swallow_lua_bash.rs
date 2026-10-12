use super::Case;

/// Fixture contracts for Lua/Bash error-swallowing rules.
///
/// Bash has no exceptions, so a swallowed failure is a discarded command
/// status: `<cmd> || true` / `<cmd> || :` (the two no-op commands), optionally
/// with a stderr redirect (`<cmd> 2>/dev/null || :`). Two rules cover the plain
/// and the stderr-redirected left-hand form; both constrain the right-hand
/// command with `$NOOP = "^(true|:)$"`.
///
/// Both rules ship at `warning`, not `error`: `|| true` is the shell's
/// explicit ignore idiom, so most hits are deliberate cleanup/probe discards.
/// The fixtures therefore treat `|| exit`, `|| return`, a logging call and a
/// `|| { ...; }` block as valid.
///
/// Lua remains an accepted limit. `varde map find_pattern` with
/// `pcall($$$ARGS)` over Lua returns both contexts as the same `function_call`
/// node, with no parent kind in its result. The rule format exposes only a
/// structural pattern and regex constraints over metavariable text; it has no
/// parent `inside`/`kind` selector. A rule would therefore flag both examples:
///
/// ```lua
/// -- invalid: result discarded, but indistinguishable structurally
/// pcall(function() error("boom") end)
/// -- valid: result captured and available for handling
/// local ok, err = pcall(function() error("boom") end)
/// ```
///
/// These are documented positive/negative Lua examples, not a `Case`: the
/// contract harness requires every `Case` to name a shipped rule, and this
/// accepted limit deliberately ships none.
///
/// invalid: a plain command or a stderr-redirected command whose failure is
/// discarded with `|| true` or `|| :`.
///
/// valid: a handler that exits, returns, logs or runs a block; the same
/// shapes with a stderr redirect. Every snippet parses as Bash.
pub fn cases() -> Vec<Case> {
    vec![
        Case::new(
            "error-swallow-bash",
            &["bash"],
            vec![
                "rm -rf /tmp/foo || true".to_string(),
                "shift || true".to_string(),
                "type -P git || true".to_string(),
                "ls -la /tmp || :".to_string(),
                "_completion-helper-necessary docker || :".to_string(),
            ],
            vec![
                "rm -rf /tmp/bar || exit 1".to_string(),
                "rm -rf /tmp/baz || { echo \"failed\"; exit 1; }".to_string(),
                "rm -rf /tmp/qux || log_error \"failed\"".to_string(),
                "shift || return 1".to_string(),
                "type -P git || die \"git is required\"".to_string(),
            ],
        ),
        Case::new(
            "error-swallow-bash-redirect",
            &["bash"],
            vec![
                "unalias \"${1-}\" 2>/dev/null || true".to_string(),
                "complete -r op 2> /dev/null || true".to_string(),
                "nvm_print_color_code \"${1}\" 2>/dev/null || :".to_string(),
            ],
            vec![
                "unalias \"${1-}\" 2>/dev/null || exit 1".to_string(),
                "complete -r op 2> /dev/null || { echo \"failed\"; return 1; }".to_string(),
                "nvm_print_color_code \"${1}\" 2>/dev/null || log_error \"failed\"".to_string(),
            ],
        ),
    ]
}
