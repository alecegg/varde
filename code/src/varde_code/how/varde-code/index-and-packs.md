---
topic: varde-code/index-and-packs
version: 1
summary: Orient in a worktree without an index, build an index or packs as coordinator, prune orphans
---

- Orient: read `docs/repo-map/README.md`, then the module pack for the folder. `varde map packs status --check` reports missing or stale packs.
- Hooks use an index only if one exists. `varde setup watch --ensure` or `varde map build` creates it.
- Build on demand from the main checkout:

```sh
varde map build --repo-root <main-checkout>
```

- `varde map packs build` writes the repo map; `varde map packs build <folder>` writes one module pack. Run on main and commit.
- Cleanup: `varde map prune --json '{}'` dry-runs; `"apply": true` deletes orphaned index folders, and `unknownOlderThanDays` also removes unrecorded folders past that age.
