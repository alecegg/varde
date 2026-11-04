# Install and configure Varde

## Inspect first

Identify the harness and checkout; check the binary (`command -v varde`),
skill links, and stores (`varde setup paths --json`).

Retry a sandbox-denied call once with escalation. If it still fails, report the
missing capability and never widen persistent harness permissions.

## Install or upgrade

- Use an installed `varde` or the binary in a known Varde checkout. If missing,
  ask for the checkout location; do not guess a download URL.
- Sync with explicit skill and agent targets. Preview with `varde setup sync
  --dry-run` and apply, after approval, with the same targets.
- Sync flags and presets apply to that run only; `--save` persists them as the
  default `[sync]` settings.
- Hooks are installed per requested harness with `varde setup hooks install
  --harness <h>`; hooks do not install the skill.
- A hand-picked skill list that omits the orchestration skill drops
  orchestration and the inbox hook on the next sync.
- At the top of a git main checkout, sync adds a managed pointer block to
  `AGENTS.md` and may build repo-map packs. Grammar download fails in the
  sandbox; `--no-packs` skips the build.
- OpenCode below 2.0.18 warns and continues best effort.
- Review the effective model of each installed agent with the user. Later
  syncs keep `model` and Codex `model_reasoning_effort`; any other edit to an
  installed agent file is replaced.

## Configure only the requested setting

- Store paths: `varde setup paths set` at project scope; `--default` only for
  an authorized shared default; `--learn` always writes `[default]`. Environment and project overrides beat the
  default; inspect `varde setup paths --json` before changing them.
- Working memory belongs outside source repositories, in one shared root with a
  folder per project, preferably versioned. Changing paths neither moves
  artifacts nor enables versioning; arrange migration and commits separately.
- Scheduled commits and secret-scanned pushes (`varde setup autosave install`)
  only on request. Review working artifacts for private evidence before
  committing or sharing.
- Runner switch: `[runner] enabled` defaults off. While off, hook mail and
  `varde plan merge-gate` do nothing, so a merge of an unapproved plan is not
  blocked.
- The runner env override beats the file. `varde runner status` shows the
  effective value and source. Change it with `varde runner off|on|status`.
- Capture: profiles change previews and records, not privacy. `[capture]`
  never-capture rules exclude content from searchable and raw stores.
- Capture: `[redact]` masks searchable text only, not retained raw bytes.
  `[raw]` enables opt-in exact-byte retention, which also needs a capture
  request. Verify capture with synthetic input.

## Verify the result

Confirm installed skills match the selected source and links resolve to
canonical directories. Run `varde setup doctor --json` for hook and store
wiring and re-read `varde setup paths --json` for changed paths. Report what changed and
whether the intended configuration loaded; a successful command alone does not
establish activation.
