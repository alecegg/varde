use super::Case;

/// Fixture contracts for Elixir/Haskell error-swallowing rules.
///
/// Elixir: a `rescue` clause returning `nil` and a `catch` clause returning
/// `:ok` are silent swallows; the rule pattern anchors on the enclosing
/// `try`/`def` construct because a bare clause has no top-level syntax. A
/// `_ = call(...)` discard is the explicit-ignore idiom and ships at `warning`;
/// a literal or variable RHS stays valid. A `with` pipeline that propagates is
/// valid.
///
/// Haskell: a `catch`/`handle` handler whose body is exactly `pure ()` or
/// `return ()` ignores the exception; logging, re-raising or returning the
/// error stays valid, and a named handler is not matched. `_ <- try ...`
/// discards the `Either`; binding the result or returning/logging the error
/// stays valid. Standalone `Left _ -> return ()` alternatives are an accepted
/// limit because the Haskell matcher rejects them as unparseable patterns.
pub fn cases() -> Vec<Case> {
    let elixir_rescue = Case::new(
        "error-swallow-elixir",
        &["elixir"],
        vec![
            "try do\n  risky()\nrescue\n  _ -> nil\nend".to_string(),
            "def f do\n  risky()\nrescue\n  _ -> nil\nend".to_string(),
            "def f(a, b) do\n  risky(a, b)\nrescue\n  _ -> nil\nend".to_string(),
            "defp f do\n  risky()\nrescue\n  _ -> nil\nend".to_string(),
            "defmacro f do\n  risky()\nrescue\n  _ -> nil\nend".to_string(),
        ],
        vec![
            "try do\n  risky()\nrescue\n  e -> Logger.error(e)\nend".to_string(),
            "try do\n  risky()\nrescue\n  e -> reraise e, __STACKTRACE__\nend".to_string(),
            "try do\n  risky()\nrescue\n  e -> raise e\nend".to_string(),
            "try do\n  risky()\nrescue\n  e -> {:error, e}\nend".to_string(),
            "with {:ok, x} <- risky() do\n  {:ok, x}\nend".to_string(),
            "try do\n  risky()\nrescue\n  _ -> :ok\nend".to_string(),
        ],
    );
    let elixir_catch = Case::new(
        "error-swallow-elixir-catch",
        &["elixir"],
        vec![
            "try do\n  risky()\ncatch\n  _, _ -> :ok\nend".to_string(),
            "def f do\n  risky()\ncatch\n  _, _ -> :ok\nend".to_string(),
            "defp f do\n  risky()\ncatch\n  _, _ -> :ok\nend".to_string(),
        ],
        vec![
            "try do\n  risky()\ncatch\n  kind, reason -> Logger.error({kind, reason})\nend"
                .to_string(),
            "try do\n  risky()\ncatch\n  :exit, reason -> {:error, reason}\nend".to_string(),
            "try do\n  risky()\ncatch\n  _, _ -> {:error, :failed}\nend".to_string(),
            "try do\n  risky()\nrescue\n  e -> {:error, e}\nend".to_string(),
        ],
    );
    let elixir_discard = Case::new(
        "error-swallow-elixir-discard",
        &["elixir"],
        vec![
            "_ = risky()".to_string(),
            "_ = Mod.risky(1, 2)".to_string(),
            "def f do\n  _ = risky()\n  :ok\nend".to_string(),
        ],
        vec![
            "_ = 5".to_string(),
            "_ = x".to_string(),
            "_ = %{a: 1}".to_string(),
            "result = risky()".to_string(),
            "_ = risky".to_string(),
            "case risky() do\n  {:ok, x} -> x\n  {:error, e} -> e\nend".to_string(),
            ":ok = risky()".to_string(),
        ],
    );
    let haskell_catch = Case::new(
        "error-swallow-haskell",
        &["haskell"],
        vec![
            "foo = catch bar (\\_ -> pure ())".to_string(),
            "foo = catch bar (\\_ -> return ())".to_string(),
            "foo = catch bar (\\(_ :: SomeException) -> pure ())".to_string(),
        ],
        vec![
            "foo = catch bar (\\e -> logError e)".to_string(),
            "foo = catch bar (\\e -> throwIO e)".to_string(),
            "foo = catch bar (\\e -> pure (Left e))".to_string(),
            "foo = catch bar handler".to_string(),
            "foo = catch bar (\\_ -> pure () >> pure ())".to_string(),
            "f act = catch act (\\e -> case e of\n    ThreadKilled -> throwIO e\n    _ -> return ())"
                .to_string(),
            "g act = catch act (\\e -> case e of\n    Overflow -> putStrLn \"overflow\"\n    _ -> return ())"
                .to_string(),
            "h act = catch act (\\e -> do\n    logError e\n    return ())"
                .to_string(),
        ],
    );
    let haskell_infix = Case::new(
        "error-swallow-haskell-infix",
        &["haskell"],
        vec![
            "foo = bar `catch` (\\_ -> pure ())".to_string(),
            "foo = bar `catch` (\\_ -> return ())".to_string(),
        ],
        vec![
            "foo = bar `catch` (\\e -> logError e)".to_string(),
            "foo = bar `catch` handler".to_string(),
            "foo = bar `catch` (\\e -> pure (Left e))".to_string(),
            "foo = bar `catch` (\\e -> case e of\n    Timeout -> throwIO e\n    _ -> return ())"
                .to_string(),
            "foo = bar `catch` (\\e -> do\n    logError e\n    return ())".to_string(),
        ],
    );
    let haskell_handle = Case::new(
        "error-swallow-haskell-handle",
        &["haskell"],
        vec![
            "foo = handle (\\_ -> pure ()) bar".to_string(),
            "foo = handle (\\_ -> return ()) bar".to_string(),
        ],
        vec![
            "foo = handle (\\e -> logError e) bar".to_string(),
            "foo = handle handler bar".to_string(),
            "foo = handle (\\e -> pure (Left e)) bar".to_string(),
            "foo = handle (\\e -> case e of\n    Timeout -> throwIO e\n    _ -> return ()) bar"
                .to_string(),
            "foo = handle (\\e -> do\n    logError e\n    return ()) bar".to_string(),
        ],
    );
    let haskell_try = Case::new(
        "error-swallow-haskell-try",
        &["haskell"],
        vec![
            "foo = do\n  _ <- try (pure ())\n  pure ()".to_string(),
            "foo = do\n  _ <- try (pure ())".to_string(),
        ],
        vec![
            "foo = do\n  result <- try (pure ())\n  either handle pure result".to_string(),
            "foo = try (pure ())".to_string(),
            "foo = do\n  _ <- risky()\n  pure ()".to_string(),
            "foo = do\n  putStrLn \"start\"\n  _ <- try (pure ())\n  pure ()".to_string(),
        ],
    );
    let haskell_try_late = Case::new(
        "error-swallow-haskell-try-late",
        &["haskell"],
        vec![
            "foo = do\n  putStrLn \"start\"\n  _ <- try (pure ())\n  pure ()".to_string(),
            "foo = do\n  putStrLn \"start\"\n  putStrLn \"more\"\n  _ <- try (pure ())\n  pure ()"
                .to_string(),
        ],
        vec![
            "foo = do\n  result <- try (pure ())\n  either handle pure result".to_string(),
            "foo = try (pure ())".to_string(),
            "foo = do\n  _ <- risky()\n  pure ()".to_string(),
            "foo = do\n  _ <- try (pure ())\n  pure ()".to_string(),
        ],
    );
    vec![
        elixir_rescue,
        elixir_catch,
        elixir_discard,
        haskell_catch,
        haskell_infix,
        haskell_handle,
        haskell_try,
        haskell_try_late,
    ]
}
