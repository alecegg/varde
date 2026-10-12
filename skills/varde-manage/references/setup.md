# Install and configure Varde

## 1. Inspect the requested setup

Identify the harness and checkout. Check:

- binary (`command -v varde`, `varde --help`);
- the harness's skill links;
- stores (`varde setup paths --json`).

Retry a sandbox-denied call once with escalation; if it still fails, report the
missing capability. Never widen persistent harness permissions to get past it.

## 2. Locate the installer

Use an installed `varde` or the binary in a known Varde checkout. If missing, ask for
the checkout location; do not guess a download URL.

1. Read `varde setup sync --help`; choose explicit targets.
2. Preview the explicit targets:

   ```sh
   varde setup sync --skills-dir <skills-dir> --agents-dir <agents-dir> --dry-run
   ```

3. After approval, run with the same targets:

   ```sh
   varde setup sync --skills-dir <skills-dir> --agents-dir <agents-dir>
   ```

## 3. Apply the authorized setup

| Scope | Action |
|---|---|
| Default or harness setup | Run the reviewed `varde setup sync` invocation. |
| Skill subset or preset | Add `--skills` or `--preset`; flags combine. See presets below. `--skills all` restores all skills. |
| Harness hooks | Run `varde setup hooks install --harness <h>` per requested harness; hooks do not install the skill. |

### Presets

| Preset | Includes |
|---|---|
| `toz` | Captured output. |
| `docs` | Doc tools. |
| `knowledge` | Project knowledge. |
| `learn` | Diagnosis, friction, evals. |
| `scan` | Code, scans, rules. |
| `workflow` | Plan, build, review, docs. |
| `full` | All skills. |

Sync selects managed instruction sections and hook features from the selected
skills' `requires` closure (or all skills when no selection is saved).

For configured instruction targets and synced harnesses, `workflow`, `full`,
and default all-skills installs retain orchestration; a hand-picked list without
`varde-change` drops orchestration and the inbox hook on the next sync.

When sync installs agents, review their models. It prints each file as
"Installed varde-builder -> <path>".

Selecting `varde-learn` adds learn guidance to the optional Varde section of
the shared instruction block; deselecting it removes that section.

1. List each installed agent with its effective model: the `model:` line
   (Claude, OpenCode, Pi), or `model =` and `model_reasoning_effort =` (Codex
   TOML), or "inherits the main session's model" when absent.
2. Ask the user to keep or change each one.
3. Apply changes by editing the installed agent file. Later `varde setup sync` runs
   keep `model` and Codex `model_reasoning_effort`; any other edit to an
   installed agent file is replaced.

## 4. Configure only the requested setting

| Setting | Where |
|---|---|
| Memory/store paths (working, knowledge, learn) | `varde setup paths set`; project scope for project settings, `--default` only for an authorized shared default; `--learn` always writes `[default]`. New setups follow Recommended working-memory setup. |
| Toz main config | `config.toml` in the config root (override with `VARDE_TOZ_CONFIG_DIR`). |
| Toz capture store | `varde setup paths set --toz`. |
| Capture privacy | Capture settings below. |

## 5. Verify the result

1. Confirm installed skills match the selected source and links resolve to
   canonical directories.
2. Run `varde setup doctor --json` for hook and store wiring; re-read `varde setup paths --json` for changed paths.

## Recommended working-memory setup

Keep working memory outside source repositories, in one shared root with a
folder per project, preferably versioned. For an authorized new shared setup:

```sh
varde setup paths set --default --working '~/varde-memory/{project}/working'
```

- `{project}` expands to the repository directory name; give same-named repos
  distinct `--project <root> --working <dir>` overrides.
- Environment and project overrides beat the default; inspect `varde setup
  paths --json` for each affected project before changing them.
- Changing paths neither moves artifacts nor enables versioning; arrange
  migration and commits separately.
- To opt into scheduled commits and secret-scanned pushes for a standalone Git
  store on macOS, run `varde setup autosave install --repo <dir>`.
  - Access needed: `run` (normal tick) needs write access to the store and an
    upstream for its branch; `install` reads the store and also requires that
    upstream, even with `--dry-run`; when commits are outgoing, `run` needs
    network access and git credentials for the remote; `install` and
    `uninstall` need write access to `~/Library/LaunchAgents` and permission
    to run `launchctl`
- Review working artifacts for private evidence before committing or sharing.

## Capture settings

Profiles change previews and records, not privacy. In the installed config:

- `[capture]` never-capture rules exclude matching content from searchable and
  raw stores.
- `[redact]` masks searchable text only, not retained raw bytes.
- `[raw]` enables opt-in exact-byte retention, which also needs a capture
  request.

Verify changes with synthetic input.
