# Optional varde-code CLI

`varde-code` is a standalone, pre-alpha Rust CLI installed on PATH as
`varde-code` (CLI-only — no MCP server surface). It's optional: use it when
available and fall back to plain Read/Grep/Glob when it isn't. Check once
per session whether it's installed:

```bash
command -v varde-code >/dev/null 2>&1
```
