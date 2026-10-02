# Author Toz output profiles

## 1. Get representative output

1. Establish the command or source to match and the desired preview or records,
   from the request or a capture.
2. Build bounded, redacted fixtures that keep critical errors and context;
   disclose missing evidence instead of copying a full session.

Prefer declarative sections and previews; script only what they cannot express.

## 2. Inspect active profiles

Run `varde-toz profile list --json` in the target project. Profiles merge by
`id` (project beats user beats built-in); reuse an id only for an intentional
override.

## 3. Draft and test with fixtures

1. Write cases for success, failure, and no-match, asserting preview text and
   records (an empty records array for an extraction negative).
2. Run `varde-toz profile test --file <file> --json`. The intended cases must
   appear and pass with load diagnostics resolved; exit zero with no cases
   verifies nothing.

File tests load as user scope, so a script may pass here yet fail to run in its
deployed project.

## 4. Install at the intended scope

- **Project (default):** the target repository's `.varde/toz-profiles.toml`.
- **User:** `<root>/toz/profiles.toml`, where root is `VARDE_CONFIG_DIR`, else
  `XDG_CONFIG_HOME/varde`, else `~/.config/varde`.

## 5. Verify deployment

- **Loaded:** in the target project, run `varde-toz profile list --json` and
  `varde-toz profile test --json`; check each profile's id, file, scope, script
  presence, cases, and diagnostics.
- **Trusted:** project scripts run only when the user's profiles file lists the
  canonical root in top-level `trusted_projects = ["/absolute/project", ...]`.
  Otherwise report the script inactive, and use declarative behavior or get
  authorization for the trust change.
- **Matched:** inspect a representative capture's preview and records
  (`varde-toz query --handle <H> --records <kind>`); fixtures do not prove the
  production glob matches.

## Profile fields

- `id`, plus exactly one selector: `match = { command = "<glob>" }` or
  `{ source = "<glob>" }`.
- Sections (optional): `sections = { heading = "<regex>" }`; use `start`
  (regex) or `jsonl_key` (field) instead of `heading`, exactly one.
- Top-level `merge_small` (bool, default true).
- Preview (optional): `preview = { kind = "toc" | "head", items_per_section = <n>,
  item = "<regex>" }`; only `kind` is required.

```toml
[[profile]]
id = "test-line-records"
match = { command = "cargo test*" }
script = '''
vardeToz.eachLine(line => {
  const m = /^test (\S+) \.\.\. (ok|FAILED|ignored)$/.exec(line);
  if (m) vardeToz.record("test", { name: m[1], status: m[2] });
});
print("test records extracted");
'''

[[profile.test]]
name = "keeps success and failure"
input = "test a::b ... ok\ntest c::d ... FAILED\n"
expect_records = { test = [{ name = "a::b", status = "ok" }, { name = "c::d", status = "FAILED" }] }
expect_preview_contains = ["test records extracted"]

[[profile.test]]
name = "ignores other lines"
input = "Compiling example\n"
expect_records = { test = [] }
```

Profile scripts run exec-free QuickJS (no `vardeToz.exec()`), limited to one
second, 64 MB heap, and 4 KB preview. Available:

- `vardeToz.eachLine(fn)`, `vardeToz.text()`, `vardeToz.handle`;
- `vardeToz.record(kind, object)`, `print(...)`.

A failing script falls back to an ordinary preview with diagnostics in
`varde-toz doctor`; a capture handle alone does not prove extraction succeeded.

## When a diagnosis report started this

- Get authorization before acting on the report's recommendation.
- Compare before/after output size and retrieval effort, and report whether
  critical details survived. Leave unmeasured tokens or time unknown. Link the
  originating report and friction item when supplied; installing a profile
  does not resolve that item.
