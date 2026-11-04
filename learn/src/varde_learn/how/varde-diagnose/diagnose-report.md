---
topic: varde-diagnose/diagnose-report
version: 1
summary: 3 of 3 - save the diagnosis report before any capture
---

# Save the diagnosis report

Save the report at `<resolved-working>/diagnoses/<report-id>/report.md` before capture, omitting a section only when it does not apply:

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

For bounded triage, cover failures, repeated work, workflow deviations, and available time/token signals.
