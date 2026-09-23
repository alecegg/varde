# Specialist review routing

The unified coordinator reviews ordinary changes. Use the configured review
categories without starting a specialist.

## Risk signals

Check changed files, their runtime readers, and the resolved review breadth.
Start a specialist only for these explicit signals:

| Risk signal | Specialist |
|---|---|
| `security` | Security |
| `data-integrity` | Data integrity |
| `resilience` | Resilience |
| `performance` | Performance |
| `api-design` | API design |

Keep `correctness`, `code`, `architecture`, `readability`, and `observability`
with the unified coordinator unless another explicit signal also applies.

Pass the comma-separated signals to `scripts/select-review-specialists.sh`.
The selector uses fixed priority and starts at most two specialists. An empty
result keeps the review on the unified coordinator path.

## Specialist boundary

Each selected specialist reads the bounded changed section and returns only
candidate findings. Candidates follow `references/report-candidates.md`.
Specialists do not create review folders, write category files, or set finding
dispositions.

The coordinator reviews every candidate, rejects unsupported or duplicate
entries, and saves only verified findings.
