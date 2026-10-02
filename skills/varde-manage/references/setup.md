# Install and configure Varde

## 1. Inspect the requested setup

Identify the target harness and checkout, then check:

- installed binaries (`command -v`, `--help`);
- the harness's skill links;
- store locations (`varde-workflow paths --json`).

Retry a sandbox-denied call once with escalation; if it still fails, report the
missing capability. Never widen persistent harness permissions to get past it.

## 2. Locate the installer

Use the root `varde` script of a known Varde checkout. If none is known, ask
for its location; never assume `varde` is on PATH or guess a download URL.

1. Read `./varde --help` and pick target flags (`--agents`, `--skills-dir`, or
   `--no-cli` when only wiring is requested).
2. Preview with `./varde sync --dry-run` plus those flags.
3. After approval, install with `./varde sync --yes` plus the same flags;
   without `--yes`, a non-TTY run can exit without installing.

## 3. Apply the authorized setup

| Scope | Action |
|---|---|
| Default or harness setup | Run the reviewed `./varde sync --yes` invocation. |
| Skill subset | Read `skills/install.sh -h`; prefer `-m` to `-f`, and give `-l` an absolute directory. Resolve preserved unowned entries instead of forcing them. |
| Toz adapters | `varde-toz install --help`; adapters do not install the skill. |

After `varde sync` installs agents for any harness, review their models. The
installer prints one line per file ("Installed varde-executor -> <path>").

1. List each installed agent with its effective model: the `model:` line
   (Claude, OpenCode, Pi), or `model =` and `model_reasoning_effort =` (Codex
   TOML), or "inherits the main session's model" when absent.
2. Ask the user to keep or change each one.
3. Apply changes by editing the installed agent file. Later `varde sync` runs
   keep `model` and Codex `model_reasoning_effort`; any other edit to an
   installed agent file is replaced.

## 4. Configure only the requested setting

| Setting | Where |
|---|---|
| Memory/store paths (working, knowledge, learn) | `varde-workflow paths set`; project scope for project settings, `--default` only for an authorized shared default; `--learn` always writes `[default]`. New setups follow Recommended working-memory setup. |
| Toz main config | `config.toml` in the config root (override with `VARDE_TOZ_CONFIG_DIR`). |
| Toz capture store | `varde-workflow paths set --toz`. |
| Capture privacy | Capture settings below. |

`varde-toz doctor --json` shows the config root and capture store.

## 5. Verify the result

1. Confirm that:
   - PATH selects the intended binaries and their help works;
   - installed skill contents match the selected source;
   - links resolve to real canonical directories.
2. Run `varde-toz doctor --json` for hook and store wiring; re-read
   `varde-workflow paths --json` for changed paths.

## Recommended working-memory setup

Keep working memory outside source repositories, in one shared root with a
folder per project, preferably versioned. For an authorized new shared setup:

```sh
varde-workflow paths set --default --working '~/varde-memory/{project}/working'
```

- `{project}` expands to the repository directory name; give same-named repos
  distinct `--project <root> --working <dir>` overrides.
- Environment and project overrides beat the default; inspect `varde-workflow
  paths --json` for each affected project before changing them.
- Changing paths neither moves artifacts nor enables versioning; arrange
  migration and commits separately.
- Review working artifacts for private evidence before committing or sharing.

## Capture settings

Profiles change previews and records, not privacy. In the installed config:

- `[capture]` never-capture rules exclude matching content from searchable and
  raw stores.
- `[redact]` masks searchable text only, not retained raw bytes.
- `[raw]` enables opt-in exact-byte retention, which also needs a capture
  request.

Verify changes with synthetic input.
