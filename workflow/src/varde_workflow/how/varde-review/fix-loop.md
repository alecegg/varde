---
topic: varde-review/fix-loop
version: 1
summary: Fix loop and commits for applying recorded findings
---

## Fix loop

Process findings in category and file order:

1. **Verify the finding is real.** Reload the block; confirm the location and defect still hold, else record `asked` with the reason.
2. **Pick one reliable in-scope solution:** the recorded one, else the only reasonable one; ask when several are reasonable.
3. **Apply it, or ask.** Apply every fix that keeps the plan's intended behaviour. Group the fixes that change it (what the plan, spec, or public API promises) for the user, and record `fixed` or `asked`.
4. **Defer an out-of-scope finding:** append it to the deferred store's category file, `<working>/reviews/deferred/<CATEGORY>.md`, and record `deferred`.
5. When findings are many, suggest running them through planning; the user decides.

### Commit

Create one commit per finding named `fix(<ID>): <summary>`, staging only that finding's paths. For a PR source, commit only the verified fixes on the local PR branch; pushing or replying needs the user's explicit choice.
