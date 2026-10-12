use super::Case;

/// Fixture contracts for Rust error-swallowing rules.
///
/// Three shapes ship at `warning` (see `error_swallow_rust.toml` for the measured
/// severity rationale):
///
/// - `error-swallow-rust-call`: `let _ = $CALL($$$ARGS);` binds a call result to
///   the wildcard pattern. A method call matches too, because `$CALL` captures
///   the whole callee node (`child.wait`). The `CALL` constraint excludes the
///   shapes fixtures pin as intentional: a lock or try-lock guard discard
///   (`mutex.lock()`, `Mutex::lock()`, `mutex.try_lock()`) and `drop(value)`,
///   which returns `()`. A discarded `.expect(..)` / `.unwrap()` panics on the
///   error path, so no error is silently lost and the whole `expect`/`unwrap`
///   chain is excluded even across a line break. Macros (`writeln!`),
///   `.await`, and non-call right-hand sides do not match the pattern, so they
///   are valid cases that document the limits rather than the exclusions.
///
/// - `error-swallow-rust-ok`: `$EXPR.ok();` is a bare statement that discards
///   the `Result` behind `.ok()`. Binding the `.ok()` value (including to `_`),
///   returning it, or using it inside a larger expression is valid because the
///   pattern only claims the standalone statement.
///
/// - `error-swallow-rust-empty-err`: an empty `if let Err(_) = expr {}` arm
///   selects and discards the error. Non-empty arms are outside this structural
///   shape; deciding whether arbitrary values are `Result`s needs type facts.
pub fn cases() -> Vec<Case> {
    vec![
        Case::new(
            "error-swallow-rust-call",
            &["rust"],
            vec![
                "fn main() { let _ = fetch(); }".to_string(),
                "fn main() { let _ = std::fs::remove_file(&path); }".to_string(),
                "fn main() { let _ = fs::remove_dir_all(&tmp); }".to_string(),
                "fn main() { let _ = child.wait(); }".to_string(),
                "fn main() { let _ = self.stop(); }".to_string(),
                "fn main() { let _ = cache.insert(key, value); }".to_string(),
                "fn main() { let _ = value.ok(); }".to_string(),
                // `unwrap_or_default` still hides the error behind a default.
                "fn main() { let _ = fetch().unwrap_or_default(); }".to_string(),
            ],
            vec![
                // Result bound and used.
                "fn main() { let value = fetch(); use_value(value); }".to_string(),
                // Propagated with `?`.
                "fn run() -> Result<(), Error> { let value = fetch()?; Ok(()) }".to_string(),
                // Matched instead of discarded.
                "fn main() { if let Ok(value) = fetch() { use_value(value); } }".to_string(),
                // Guard bound to a named variable, not the wildcard.
                "fn main() { let _guard = lock.lock(); }".to_string(),
                // Excluded: lock/try-lock guard discards carry no error.
                "fn main() { let _ = mutex.lock(); }".to_string(),
                "fn main() { let _ = mutex.try_lock(); }".to_string(),
                "fn main() { let _ = Mutex::lock(&mutex); }".to_string(),
                // Excluded: `drop` returns `()`.
                "fn main() { let _ = drop(value); }".to_string(),
                // Excluded: `expect`/`unwrap` panic on the error path.
                "fn main() { let _ = fetch().expect(\"must succeed\"); }".to_string(),
                "fn main() { let _ = fetch().unwrap(); }".to_string(),
                "fn main() { let _ = fetch()\n            .expect(\"must succeed\"); }".to_string(),
                // Not a call.
                "fn main() { let _ = value; }".to_string(),
                "fn main() { let _ = 42; }".to_string(),
                // Macro invocation, not a call expression.
                "fn main() { let _ = writeln!(out, \"text\"); }".to_string(),
                // `.await` makes the right-hand side an await expression.
                "async fn run() { let _ = fetch().await; }".to_string(),
            ],
        ),
        Case::new(
            "error-swallow-rust-ok",
            &["rust"],
            vec![
                "fn main() { std::fs::remove_file(&path).ok(); }".to_string(),
                "fn main() { value.fetch().ok(); }".to_string(),
                "fn main() { cache.set(item).ok(); }".to_string(),
                "fn main() { u32::try_from(count).ok(); }".to_string(),
            ],
            vec![
                // Bound to a named variable and used.
                "fn main() { let value = fetch().ok(); use_value(value); }".to_string(),
                // Bound to the wildcard: a `let` declaration, not a statement.
                "fn main() { let _ = fetch().ok(); }".to_string(),
                // Returned as the tail expression.
                "fn maybe() -> Option<i32> { fetch().ok() }".to_string(),
                // Returned explicitly.
                "fn maybe() -> Option<i32> { return fetch().ok(); }".to_string(),
                // Part of a larger expression.
                "fn main() { if fetch().ok().is_some() { work(); } }".to_string(),
                // Propagated with `?`.
                "fn maybe() -> Option<i32> { fetch().ok()?; None }".to_string(),
                // No `.ok()` call.
                "fn main() { fetch(); }".to_string(),
            ],
        ),
        Case::new(
            "error-swallow-rust-empty-err",
            &["rust"],
            vec![
                "fn main() { if let Err(_) = fetch() {} }".to_string(),
                "fn main() { if let Err(_) = do_work() { } }".to_string(),
            ],
            vec![
                "fn main() { if let Err(error) = fetch() { log(error); } }".to_string(),
                "fn main() { if let Ok(_) = fetch() {} }".to_string(),
                "fn main() { if fetch().is_err() {} }".to_string(),
            ],
        ),
    ]
}
