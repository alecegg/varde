use super::Case;

/// Fixture contracts for Go error-swallowing rules.
///
/// Go has no exceptions, so a swallowed error is a blank-identifier discard.
/// Three rules cover the plan's shapes: `_ = err` (a captured error variable),
/// `_ = f(...)` (a discarded single-result call) and `_, _ = f(...)` (a
/// discarded two-result call). Unchecked returns (`f()` as a statement,
/// `v, _ := f()`) are not matched; they need type facts and belong to the
/// follow-up audit plan.
///
/// The call rules ship at `warning`, not `error`: Go's blank identifier is the
/// documented way to ignore a result, so a pattern cannot tell an error result
/// from a non-error one (`_ = ctx.PopPid()`, `_, _ = stack.Pop()`) without type
/// facts. The fixtures below therefore treat non-call discards, handled
/// results, map/range blanks and bare calls as valid.
///
/// invalid: a blank-identifier discard of a variable named `err`; a blank
/// discard of a call, including a method call; a two-blank discard of a call.
///
/// valid: `if err != nil` handling, a result bound and used, a bare call
/// statement, a function value (no call), a non-call right-hand side, a
/// map/range blank, and a single-value discard for the two-value rule. Every
/// snippet parses as Go; statements live inside `func f()`.
pub fn cases() -> Vec<Case> {
    vec![
        Case::new(
            "error-swallow-go",
            &["go"],
            vec![
                "package p\nfunc f() {\n\terr := g()\n\t_ = err\n}".to_string(),
                "package p\nfunc f() {\n\tif err != nil {\n\t\t_ = err\n\t}\n}".to_string(),
            ],
            vec![
                "package p\nfunc f() {\n\terr := g()\n\tif err != nil {\n\t\treturn\n\t}\n}"
                    .to_string(),
                "package p\nfunc f() {\n\t_ = other\n}".to_string(),
                "package p\nfunc f() {\n\t_ = errs\n}".to_string(),
                "package p\nfunc f() {\n\tfor _ = range values {\n\t}\n}".to_string(),
            ],
        ),
        Case::new(
            "error-swallow-go-call",
            &["go"],
            vec![
                "package p\nfunc f() {\n\t_ = doThing()\n}".to_string(),
                "package p\nfunc f() {\n\t_ = conn.Close()\n}".to_string(),
                "package p\nfunc f() {\n\t_ = doThing(1, 2)\n}".to_string(),
                "package p\nfunc f() {\n\t_ = obj.Method()\n}".to_string(),
            ],
            vec![
                "package p\nfunc f() {\n\t_ = err\n}".to_string(),
                "package p\nfunc f() {\n\t_, _ = doThing()\n}".to_string(),
                "package p\nfunc f() {\n\tdoThing()\n}".to_string(),
                "package p\nfunc f() {\n\t_ = doThing\n}".to_string(),
                "package p\nfunc f() {\n\tif err := doThing(); err != nil {\n\t\treturn\n\t}\n}"
                    .to_string(),
                "package p\nfunc f() {\n\terr := doThing()\n\t_ = err\n}".to_string(),
                "package p\nfunc f() {\n\tdefer func() {\n\t\tif err := c.Close(); err != nil {\n\t\t\tlog(err)\n\t\t}\n\t}()\n}"
                    .to_string(),
            ],
        ),
        Case::new(
            "error-swallow-go-two-value",
            &["go"],
            vec![
                "package p\nfunc f() {\n\t_, _ = doThing()\n}".to_string(),
                "package p\nfunc f() {\n\t_, _ = w.Write(buf)\n}".to_string(),
                "package p\nfunc f() {\n\t_, _ = io.Copy(w, r)\n}".to_string(),
            ],
            vec![
                "package p\nfunc f() {\n\t_, _ = m[key]\n}".to_string(),
                "package p\nfunc f() {\n\t_, _ = 1, 2\n}".to_string(),
                "package p\nfunc f() {\n\t_, _ = doThing\n}".to_string(),
                "package p\nfunc f() {\n\t_ = doThing()\n}".to_string(),
                "package p\nfunc f() {\n\tv, err := doThing()\n\t_ = v\n\t_ = err\n}".to_string(),
                "package p\nfunc f() {\n\t_, err := doThing()\n\t_ = err\n}".to_string(),
                "package p\nfunc f() {\n\tvar err error\n\t_, err = doThing()\n\tif err != nil {\n\t\treturn\n\t}\n}".to_string(),
                "package p\nfunc f() {\n\tfor _, _ = range values {\n\t}\n}".to_string(),
            ],
        ),
    ]
}
