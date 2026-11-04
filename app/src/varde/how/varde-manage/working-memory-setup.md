---
topic: varde-manage/working-memory-setup
version: 1
summary: Set up a shared working-memory root and optional autosave
---

Keep working memory outside source repositories, in one shared root with a
folder per project, preferably versioned. For an authorized new shared setup:

```sh
varde setup paths set --default --working '~/varde-memory/{project}/working'
```

- `{project}` expands to the repository directory name; give same-named repos
  distinct `--project <root> --working <dir>` overrides.
- Inspect `varde setup paths --json` for each affected project before
  changing overrides.
- To opt into scheduled commits and secret-scanned pushes for a standalone Git
  store on macOS, run `varde setup autosave install --repo <dir>`.

Access needed for autosave:

- `run` (normal tick): write access to the store and an upstream for its
  branch. When commits are outgoing, it also needs network access and git
  credentials for the remote.
- `install`: reads the store and requires that upstream, even with `--dry-run`.
- `install` and `uninstall`: write access to `~/Library/LaunchAgents` and
  permission to run `launchctl`.
