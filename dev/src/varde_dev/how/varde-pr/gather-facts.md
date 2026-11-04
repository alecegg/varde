---
topic: varde-pr/gather-facts
version: 1
summary: Run pr-facts and handle unmeasured impact
---

- `scripts/pr-facts.sh <base> <head>` builds its own merge-base index (no main-checkout index needed), so `detect_changes` compares base symbols with head symbols.
- Review the source for key impact edges.
- If impact is unmeasured, run `varde map --help` to find the index readiness commands, build the index on main, then retry.
- Include the script's error and truncation fields in your summary.
