# Install and configure Varde

1. **Inspect the requested setup.** Identify the target harness and checkout.
   Check installed binaries with `command -v` and their `--help`; inspect the
   harness's skill links. `varde-workflow paths --json` reports configured
   working, knowledge, learn, and Toz locations. Retry a sandbox-denied optional
   tool once with escalation, then report the missing capability if unavailable.
2. **Locate the installer.** Use the actual Varde checkout's root `varde` script
   and inspect its help. If no checkout is known, ask for its location or source;
   do not assume `varde` is on PATH or guess a download URL. From that root,
   `./varde sync --dry-run` previews the default setup; include the same target
   flags on the real run. Use `--agents` for supported harnesses, `--skills-dir`
   for an explicit skill directory, and `--no-cli` when only wiring is requested.
3. **Apply the authorized setup.** Run the reviewed sync invocation. The root
   installer owns canonical real directories under the user's shared agents
   skills directory and links them into harnesses. For a subset, use the
   checkout's skills installer with `-s` and `-m` to refresh managed installs;
   its `-l` option links from a canonical directory. Inspect help before manual
   installation. Resolve preserved unowned entries without blindly forcing them.
   Toz adapters are separate: `varde-toz install --help` lists supported harnesses
   and options; adapter installation does not install the skill.
4. **Configure only the requested setting.** Inspect the existing config and
   installed help first. Use `varde-workflow paths set` for memory/store paths,
   following the working-memory recommendation below for new setups. Use project
   scope for project-specific settings and `--default` for an authorized shared
   default; preserve existing overrides. Toz's main config is config.toml under `VARDE_TOZ_CONFIG_DIR`
   (legacy `TOZ_CONFIG_DIR` fallback), otherwise `XDG_CONFIG_HOME/varde-toz`
   or ~/.config/varde-toz. A distinct existing legacy tool-output-zone root
   is reused. This config root is separate from the capture store path:
   `varde-workflow paths set --toz` changes the store, not the main config.
   Inspect the distinct locations in `varde-toz doctor --json`. Output profiles use a separate Varde config
   root, described in `references/toz-profiles.md` when profile work is requested.
5. **Verify the result.** Confirm PATH selects the intended binaries, their
   help works, installed skill contents match the selected source, and links
   resolve to real canonical directories. Run `varde-toz doctor --json` for
   hooks/store wiring and re-read `varde-workflow paths --json` for changed paths.
   Report diagnostics and any preserved or failed install separately from success.

## Recommended working-memory setup

Keep working memory (plans, tasks, handoffs, reviews, and journals) outside
source repositories, under one shared storage root for the user's projects and
harnesses. Give each project a distinct folder. Prefer a separate Git repository
or storage with version history so earlier working artifacts can be recovered.
Project knowledge can remain committed in each source repository.

For an authorized new shared setup, configure a user default, for example:

```sh
varde-workflow paths set --default --working '~/varde-memory/{project}/working'
```

`{project}` expands to the repository directory name. Give same-named repos
distinct project overrides with `--project <root> --working <dir>`.
Environment and project overrides take precedence over this default; inspect
`varde-workflow paths --json` for each affected project before changing them.
The CLI's built-in locations remain in the project tree when no override applies.

Changing paths does not move existing artifacts or enable versioning. Arrange
migration and Git commits or storage history separately within the authorized
setup. Review working artifacts for private evidence before committing or sharing
them; version history need not be public or team-shared.

## Capture settings versus output profiles

Profiles change previews and records; they do not define privacy policy. For
capture-setting requests, inspect the installed configuration format:

- `[capture]` never-capture rules exclude matching content from searchable and
  raw stores.
- `[redact]` masks searchable text; it does not make retained raw bytes redacted.
- `[raw]` enables opt-in exact-byte retention, which also needs a capture request.

Use synthetic input to verify requested changes. Preserve existing retention,
redaction, raw-output, trust, and sandbox settings unless the request changes
them. A sandbox-denied store write calls for a targeted retry or reported
limitation; do not silently widen persistent harness permissions.
