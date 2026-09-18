# Optional varde-code CLI

Use `varde-code` when it exists on `PATH`.
Otherwise use direct reads, grep, and file discovery.

Check once during each workflow:

```bash
command -v varde-code >/dev/null 2>&1
```

Indexed commands require one initial repository build:

```bash
varde-code build --repo-root "$(pwd)"
```

If any CLI call fails, use direct repository reads.
Do not install or rebuild the CLI automatically.

Use command help before supplying unfamiliar JSON fields:

```bash
varde-code <command> --help
```
