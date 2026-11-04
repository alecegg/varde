# Author Toz output profiles

## Outcomes

- The profile is grounded in the command or source to match and the desired
  preview or records. Fixtures are bounded, redacted, and keep critical errors
  and context; missing evidence is disclosed.
- Declarative sections and previews are preferred to a script.
- Profiles merge by `id` (project beats user beats built-in); an id is reused
  only for an intentional override.
- Cases cover success, failure, and no-match, asserting preview text and records.
- Installed at the intended scope: project (default, `.varde/toz-profiles.toml`)
  or user (`toz/profiles.toml` under the user config root).
- Project scripts run only when the user's profiles file lists the canonical
  root in top-level `trusted_projects`. Otherwise report the script inactive and
  use declarative behavior, or get authorization for the trust change.
- A diagnosis report's recommendation is acted on only with authorization.
  Report whether critical details survived; leave unmeasured tokens or time
  unknown. The originating report and friction item are linked when supplied; installing
  a profile does not resolve that item.

## Validation

- `varde setup profiles test --file <file> --json`: the intended cases appear
  and pass with load diagnostics resolved; exit zero with no cases verifies
  nothing. File tests load as user scope, so a script may pass yet fail in its
  deployed project.
- In the target project, `varde setup profiles list --json` and
  `varde setup profiles test --json` show each profile's id, file, scope, script
  presence, cases, and diagnostics.
- A representative capture's preview and records match
  (`varde run query --handle <H> --records <kind>`); fixtures do not prove the
  production glob matches.
