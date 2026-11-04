---
topic: varde-skill-authoring/flow-ledger-refresh
version: 1
summary: Flow ledger refresh, after choice - stale ids only; no API key; location is in generate
---

## Refresh

1. Run `ledger check`; each stale id names the decision and where it now sits. List the instruction files changed since the ledger's revision, even when nothing is stale.
2. Send the auditor only the stale ids, their files, and the current ledger. Ask for corrected line bounds, alternatives, units, and depth for those ids, plus any new decisions in every changed instruction file.
3. Merge the answer, then `ledger hash`, `ledger validate`, `ledger score`.
