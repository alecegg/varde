---
topic: varde-customize/profile-scripts
version: 1
summary: Write a Toz profile script that extracts records
---

Script only what declarative sections and previews cannot express. Scripts run
exec-free QuickJS (no `vardeToz.exec()`), limited to one second, 64 MB heap,
and a 4 KB preview. Available: `vardeToz.eachLine(fn)`, `vardeToz.text()`,
`vardeToz.handle`, `vardeToz.record(kind, object)`, `print(...)`.

```toml
[[profile]]
id = "test-line-records"
match = { command = "uv run pytest -v*" }
script = '''
vardeToz.eachLine(line => {
  const m = /^(.+\.py)::(\S+)\s+(PASSED|FAILED)\s+\[\s*\d+%\]$/.exec(line);
  if (m) vardeToz.record("test", { name: m[2], status: m[3] });
});
print("pytest results extracted");
'''

[[profile.test]]
name = "records verbose pytest results"
input = "tests/test_cli.py::test_version PASSED [100%]\n"
expect_records = { test = [{ name = "test_version", status = "PASSED" }] }
expect_preview_contains = ["pytest results extracted"]
```

A failing script falls back to an ordinary preview with diagnostics in
`varde setup doctor`; a capture handle alone does not prove extraction
succeeded.
