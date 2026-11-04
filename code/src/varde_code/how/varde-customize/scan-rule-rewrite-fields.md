---
topic: varde-customize/scan-rule-rewrite-fields
version: 1
summary: Scan rule fix, rewrite, languages and naming fields, part 2 of 4, with a constraints example
---

## Optional rule fields, continued

- `fix` - free-text guidance, never applied automatically.
- `rewrite` - pattern only: a `$VAR`/`$$$VAR` template applied by
  `scan --apply`. Every variable in it must appear in `pattern`, or the loader
  rejects the rule.
- `languages` - pattern only, e.g. `"javascript"`, `"typescript"`, `"tsx"`,
  `"python"`, `"rust"`, `"go"`. Omitted or empty runs on every parseable file;
  an explicit list must parse the pattern in every language.
- `name`, `description`, `remediation` - not validated; set them like the
  built-ins. Rule listings show `name` and `description`; scan output shows
  `remediation` in its rule legend.

```toml
[rule.constraints]
NAME = ["^get", "!^getDeprecated$"]
VALUE = "^[0-9]+$"
```
