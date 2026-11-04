---
topic: varde-customize/scan-rule-tests
version: 1
summary: Scan rule test entries and scopes, part 4 of 4, fields in scan-rule-format
---

## Test entries

Every `[[rule.test]]` needs `name`.

**Pattern rules:** `invalid` snippets must match, `valid` snippets must not.
With `rewrite`, add `expect_rewrite` mapping input to expected output.

```toml
[[rule.test]]
name = "flags a plain assignment"
invalid = ["api_key = \"sk_live_1234567890abcdef\""]
valid = ["api_key = os.environ[\"API_KEY\"]"]

[rule.test.expect_rewrite]
"old_call(x)" = "new_call(x)"
```

**SQL rules:** an inline `[rule.test.fixture]` tree (`"big.py" = "..."`) is
indexed (with verification when declared); `[[rule.test.expect_rows]]` entries
(`file`, `line`) compare final rows as an order-insensitive multiset.

## Scopes and precedence

Rules merge by `id`, silently, in this order of precedence:

1. Repo: `<repo_root>/.varde-code/rules/`.
2. User: `$VARDE_CODE_USER_RULES_DIR`, else `~/.config/varde-code/rules/`.
3. Built-ins embedded in the binary.
