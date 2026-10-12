<!-- kind: reference -->
# Scan setup and recovery

Load only for these cases:

- choosing a scan preset;
- handling incomplete analysis; or
- resolving index readiness.

## Choose a preset

Inspect setup and active rules, and review the preset and scope before writing; an existing overrides file requires explicit `--force` to replace:

```sh
varde scan setup --help
varde scan rules list --json '{"repoRoot":"<repo>"}'
```



## Recover an incomplete scan

- Read diagnostics and repair their cause before claiming the scan is complete.
- For intentionally malformed fixtures, use repository `.ignore` entries and
  record the excluded scope. Suppressions do not clear diagnostics.
- For `index_missing` or `index_stale`, load `varde-code`: use your skill
  tool, or read `../../varde-code/SKILL.md`, and follow its
  coordinator/worker guidance. A worker must not build the index. If
  readiness cannot be restored, report the scan as unavailable and state the
  lost capability.
