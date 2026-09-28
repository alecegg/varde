# Optional varde-code CLI

Use `varde-code` when it exists on `PATH`.
Otherwise use direct reads, grep, and file discovery.

Check once during each workflow:

```bash
command -v varde-code >/dev/null 2>&1
```

The main agent must establish persistent watcher coverage before dispatching
indexed queries:

```bash
varde-code watch --ensure --repo "$(pwd)"
varde-code watch --list
```

Confirm the repo is registered, alive, and ready. If setup or readiness fails,
use direct reads and grep and report degraded index capability. Never rebuild
or install the CLI automatically.

On `index_missing` or `index_stale`, use direct repository reads while the
watcher catches up. `find_pattern` parses live source; `detect_changes` and
`slice_state` are diagnostic exceptions.

Use command help before supplying unfamiliar JSON fields:

```bash
varde-code <command> --help
```
