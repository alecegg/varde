# Diagnose a session

Use this route only when the user asks to diagnose an existing session or
bounded history, not after a failed evaluation or a possible recurrence.

## Outcomes

- Reports and snapshots live under `<resolved-working>/diagnoses/<report-id>/` (`<report-id>` is `<YYYY-MM-DD>-<slug>`). They never enter committed knowledge and stay until explicitly removed.
- `<resolved-working>` is the caller-supplied absolute working-store path, else `data.working` from `varde setup paths --json`. If `varde setup paths --json` fails, retry once with escalated access, then ask for the path before writing.
- Evidence comes from `varde learn sessions show`: `--harness {codex,claude,opencode}`
  with exactly one of `--current`, `--session <ID>`, or `--path <FILE>`, frozen
  with `--snapshot-out` and paged with `--snapshot-in`. Coverage comes from
  `data.sources`, `data.children`, and `data.coverage`; warnings mean partial
  coverage, never complete. Unknown-event excerpts are inspected before
  interpretation; inherited events are not eligible for capture.
- `--current` is used only with a verified harness identity. When it is
  unavailable or ambiguous, stop, report the typed blocker, and ask for
  `--session <ID>` or `--path <FILE>`; never substitute an environment variable
  or guessed path.
- The analysis procedure follows `data.overlap` (`current`, `not_current`, or
  `unknown`), never the selector. When it is `current` or `unknown`, follow
  `references/diagnose-current.md` before saving the report.
- When evidence shows noisy output, repeated retrieval, missing details, or
  ineffective previews, also follow `references/diagnose-toz.md`.
- Save `<resolved-working>/diagnoses/<report-id>/report.md` before capture. Sections (omit one only when inapplicable):
  - Complaint or triage question
  - Coverage and limits
  - Observations (anchored to source and native anchor)
  - Hypotheses (with confidence and alternatives)
  - Bounded recommendations
  - Capture results
  - Uncaptured findings

## Report rules

- Bounded triage covers failures, repeated work, workflow deviations, and
  available time/token signals.
- Recommend without applying changes or status updates.
- For each proposed change, use the removal option, audit lens, and outcome tag
  in `references/options.md`.
- Leave uncaptured, with its reason, any candidate with:
  - a missing timestamp or cwd;
  - unresolved identity;
  - a rewritten or otherwise uncertain anchor;
  - overlap the cutoff cannot exclude;
  - inherited history;
  - an unknown duplicate;
  - an ambiguous item match.

## Capture only eligible incidents

After saving the report, follow `references/diagnose-capture.md` only to record
eligible historical incidents. Report-only diagnosis stops here.
