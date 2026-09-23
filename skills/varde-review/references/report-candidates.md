# Specialist candidate contract

Specialists return candidate findings to the coordinator. Candidate output is
temporary input. Do not save it as a category file.

## Required fields

Every candidate must contain these seven fields:

| Field | Rule |
|---|---|
| Location | Repository-relative file and stable line or symbol when possible |
| Category | One of the ten review categories |
| Severity | `critical`, `high`, `medium`, `low`, or `info` |
| Evidence | A concrete code path, check, or reproduction |
| Impact | The observed consequence if the issue remains |
| Refutation | The checks attempted that could disprove the candidate |
| Suggested disposition | A proposed follow-up, never a final decision |

The normalization helper reads these fields as tab-separated records through
`scripts/normalize-review-candidates.sh`. It keeps the first valid candidate
for each `category|location|impact` key.

## Coordinator gate

The coordinator checks every accepted candidate against the changed file and
its callers. It rejects malformed records, unsupported categories, unsupported
severities, duplicate keys, and candidates without code evidence. It then
removes any remaining overlap between findings about the same issue.

Only the coordinator may assign a finding identifier, choose the final
severity and label, set disposition to `blank`, or write a category file.
Specialists never create review folders or save findings directly.
