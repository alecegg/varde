---
topic: varde-manage/sync-workflow
version: 1
summary: Sync steps 1-5, part 1 of 3, approval before apply, scope and repo-map prompt in later parts
---

## Sync steps

1. Use an installed `varde` or the binary in a known Varde checkout. If it is
   missing, ask for the checkout location; do not guess a download URL.
2. To upgrade from a local checkout with an unchanged version, run
   `uv tool install --reinstall --from <checkout> varde`.
3. Read `varde setup sync --help`; choose explicit targets.
4. Preview the explicit targets:

   ```sh
   varde setup sync --skills-dir <skills-dir> --agents-dir <agents-dir> --dry-run
   ```

5. After approval, run with the same targets:

   ```sh
   varde setup sync --skills-dir <skills-dir> --agents-dir <agents-dir>
   ```

   Sync flags and presets apply to that run only. Add `--save` to persist them
   as the default `[sync]` settings; `--save --dry-run` only previews the
   settings and does not write them.
