# Diagnose a session

Use this route only when the user asks to diagnose an existing session or
bounded history, not after a failed evaluation or a possible recurrence.

## Resolve private storage

1. Use the caller-supplied absolute working-store path, else absolute
   `data.working` from one `varde-workflow paths --json` run.
2. On failure, retry unchanged once with escalated access, then ask for the
   path before writing.

`<resolved-working>` is that path. Name each report `<report-id>` as
`<YYYY-MM-DD>-<slug>`; `<new-private-path>` is
`<resolved-working>/diagnoses/<report-id>`. Keep snapshots and reports there, never in committed knowledge; reports stay in the working store until explicitly removed.

## Inspect bounded evidence

```sh
varde-learn diagnose inspect --harness codex --session <THREAD_ID> \
  --snapshot-out <new-private-path>/bundle.json --json
```

- Select with `--harness {codex,claude,opencode}` and exactly one of
  `--current`, `--session <ID>`, or `--path <FILE>`.
- `--current` needs a verified harness identity. Claude supplies it only as
  command-hook JSON on stdin, which an agent session cannot provide; OpenCode
  does not expose a verified current caller identity. In those cases, ask for
  `--session <ID>` or `--path <FILE>`.
- If current identity is unavailable or ambiguous, stop and report the typed
  blocker; never substitute an environment variable or a guessed path.
- Select the analysis procedure from `data.overlap` (`current`, `not_current`,
  or `unknown`), never from the selector: a path or ID can alias the invoking
  session. When `data.overlap` is `current` or `unknown`, read
  `references/diagnose-current.md` and follow it before saving the report.

Page a saved bundle without a live selector:

```sh
varde-learn diagnose inspect --snapshot-in <bundle.json> \
  --offset 100 --limit 100 --json
```

Coverage warnings mean partial coverage; never call it complete. They flag
sources that are:

- partial or malformed;
- compacted;
- unsupported or oversized;
- changing.

## Toz output friction

When evidence shows noisy output, repeated retrieval, missing details, or
ineffective previews, also follow `references/diagnose-toz.md`.

## Save the report

Create `<resolved-working>/diagnoses/<report-id>/report.md`. Save report.md
before capture. Omit a section only when it does not apply:

```markdown
# Session diagnosis

## Complaint or triage question
<User's question or bounded scope>

## Coverage and limits
<Harness, target identity, overlap, cutoff, page/source coverage, warnings>

## Observations
- <What an anchored source record shows; cite source and native anchor>

## Hypotheses
- <Possible explanation; confidence; supporting evidence; alternatives>

## Bounded recommendations
- <Small next check or change, with expected evidence>

## Capture results
- <Incident kind: created/already-recorded, item ID, occurrence ID, or error>

## Uncaptured findings
- <Candidate and concrete reason it was not eligible>
```

Report rules:

- For bounded triage, cover failures, repeated work, workflow deviations, and
  available time/token signals.
- Recommend without applying changes or status updates.
- Leave uncaptured, with its reason, any candidate with:
  - a missing timestamp or cwd;
  - unresolved identity;
  - a rewritten or otherwise uncertain anchor;
  - overlap the cutoff cannot exclude;
  - inherited history;
  - an unknown duplicate;
  - an ambiguous item match.

## Capture only eligible incidents

After saving the report, load `references/diagnose-capture.md` only to record
eligible historical incidents. Report-only diagnosis stops here.
