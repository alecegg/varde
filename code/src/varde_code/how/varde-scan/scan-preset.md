---
topic: varde-scan/scan-preset
version: 1
summary: Inspect setup and active rules before choosing a scan preset
---

Inspect setup and active rules, and review the preset and scope before writing; an existing overrides file requires explicit `--force` to replace:

```sh
varde scan setup --help
varde scan rules list --json '{"repoRoot":"<repo>"}'
```

`varde scan setup` changes rule overrides, so inspect the preset and scope before using it.
