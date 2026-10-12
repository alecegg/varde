# Optional varde-code CLI

Use `varde-code` when it exists on `PATH`.
Otherwise use direct reads, grep, and file discovery.

Check once during each workflow:

```bash
command -v varde >/dev/null 2>&1
```

Whoever dispatches indexed queries must first establish persistent watcher
coverage:

```bash
varde setup watch --ensure --repo "$(pwd)"
varde setup watch --list
```

Confirm the repo is registered, alive, and ready. If setup or readiness fails,
use direct reads and grep and report degraded index capability. Never rebuild
or install the CLI automatically.

On `index_missing` or `index_stale`, use direct repository reads while the
watcher catches up. `find_pattern` parses live source; `detect_changes` and
`slice_state` are diagnostic exceptions.

Use command help before supplying unfamiliar JSON fields:

```bash
varde <command> --help
```
