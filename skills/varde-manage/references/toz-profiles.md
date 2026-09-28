# Author Toz output profiles

1. **Get representative output.** Use examples from the request or a capture.
   A diagnosis report can supply capture handles, session links, coverage gaps
   and measured baselines; its recommendation requires authorization before
   profile edits. Preserve critical errors and context. Use bounded redacted
   fixtures and disclose missing evidence rather than copying a full session.
   Establish the command/source to match and the desired preview or records.
   Prefer declarative sections and previews; add a script only for extraction
   or summaries those fields cannot express.
2. **Inspect active profiles.** Run `varde-toz profile list --json` in the target
   project. Profiles merge by `id`: project beats user, which beats built-in.
   Reuse an id for an intentional override; otherwise choose a distinct id.
3. **Draft with fixtures.** Use the fields below. Include representative success,
   failure, and unrelated/no-match output as appropriate. Assert expected preview
   text and records, including an empty records array for an extraction negative.
4. **Test the file.** Run `varde-toz profile test --file <file> --json`.
   Require the intended cases to appear and pass, and resolve load diagnostics:
   exit zero with no cases is not verification. File tests load as user scope,
   so a script may pass even when its deployed project version cannot execute.
5. **Install at the intended scope.** Default to the target repository's
   .varde/toz-profiles.toml. User profiles live at ~/.config/varde/toz/profiles.toml,
   resolved through `VARDE_CONFIG_DIR`, then `XDG_CONFIG_HOME/varde`, then that
   default. Preserve other entries and top-level settings.
6. **Verify deployment.** Run `varde-toz profile list --json` and
   `varde-toz profile test --json` in the target project. Check id, file, scope,
   script presence, cases, and diagnostics. Project scripts execute only when
   the user's profiles file has the canonical root in top-level
   `trusted_projects = ["/absolute/project", ...]`. If absent, report that the
   script is inactive and use declarative behavior or obtain authorization for
   that trust change. Finally inspect a representative capture's preview and
   `varde-toz query --handle <H> --records <kind>` when extraction is intended;
   fixture tests alone do not prove the production command/source glob matches.
   For diagnosis-driven improvements, compare equivalent before/after output
   sizes and retrieval effort, and report whether critical details survived.
   Leave unavailable token or time measurements unknown. Link the result to
   the originating report and friction item when supplied; profile installation
   does not resolve or promote that item.

## Profile fields

Each `[[profile]]` has `id` and exactly one match selector:
`match = { command = "<glob>" }` or `{ source = "<glob>" }`.
Optional sections choose one of `heading` (regex), `start` (regex), or
`jsonl_key` (field). `merge_small` defaults to true. Preview fields are
`kind = "toc" | "head"`, `items_per_section`, and `item` (regex).

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

Profile scripts use exec-free QuickJS: `vardeToz.eachLine(fn)`, `vardeToz.text()`,
`vardeToz.handle`, `vardeToz.record(kind, object)`, and `print(...)`.
There is no `vardeToz.exec()` here. Limits are one second, 64 MB heap, and 4 KB
preview. Script failures fall back to an ordinary preview with diagnostics in
`varde-toz doctor`; a capture handle alone does not prove extraction succeeded.
