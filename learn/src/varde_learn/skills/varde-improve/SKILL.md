---
name: varde-improve
description: "Use this skill when recurring friction should become an approved improvement: distill open friction into a proposal, rank skills for a trim, add-back or rebuild, apply an accepted change, or author skill eval cases and trigger query sets."
recommends: [varde-learn, varde-plan, varde-build]
---

# Improve from recurring friction

| Task | Read |
|---|---|
| Distill recurring friction into an approved improvement | `references/distill.md` |
| Review recurring friction for an improvement proposal | `references/improve.md` |
| Rank skills and agents, propose changes, review and apply them | Loop outcomes below |
| Author query sets or eval cases, or run an approved evaluation | Evals outcomes below |

## Loop outcomes

- `varde learn skills candidates` ranks skills and agents, one direction each (validate: every target lists `add`, `trim` or `reset`); propose with `skills extract` or `skills reset`.
- Proposals change no file until `skills accept <id>`; `skills report` writes the page whose decision blocks `varde learn docs comments <page> --kind decision` reads (validate: `git status` is clean until an accept).

## Evals outcomes

- Evals run only when the user asks and gate nothing; the loop never needs them.
- Billed runs happen only after the user approves the run and its cost (validate: approval quoted before any `varde learn measure <skill-dir> output` or `trigger` run).
- `evals/evals.json` has realistic prompts with assertions (validate: `varde learn measure <skill-dir> calibrate` passes before results are trusted).
- Eval file edits are bounded source edits, not part of the loop.
