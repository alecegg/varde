---
type: reference
status: current
date: 2026-11-01
---

# Exploration notes: GoodLinks rows #12-#18

Read by a Haiku explorer on 2026-11-01 (rendered pages only; unverified). Row numbers refer to `goodlinks-ai-links.md`. Figures are as shown on the page or vendor-reported.

| # | Link | What it is | Mechanisms and claims | Varde relevance |
|---:|---|---|---|---|
| 12 | https://github.com/heyhuynhgiabuu/pi-pretty/releases/tag/v0.7.0 | pi-pretty v0.7.0: tool-output restyler for the Pi agent | Opt-in "claudecode" style, collapsed tool rows with line and diff counts; patches non-public Pi internals | Low: private host internals |
| 13 | https://github.com/opensec-git/Pi-Bolt/blob/pi-bolt/docs/ARCHITECTURE.md | Pi-Bolt: Pi agent as a Bun single-file executable | `bun build --compile --bytecode`, static heap, bytecode fallback; one Pi version per executable | None: startup packaging of another host |
| 14 | https://github.com/trailhq/Graft/ | Trail-code (formerly graft): tree-sitter code map plus team learnings as markdown in `.trail/learnings` (11.0k stars, MIT) | Per-prompt hooks add matching files and blast radius; `trail check` compares a branch diff to saved learnings; self-reported 32% lower cost on 162 runs | High: overlaps `varde-code` and knowledge notes; compare `trail check` with `varde-knowledge` decisions; test the cost claim with our token-count evals |
| 15 | https://github.com/Davidasx/pi-key-protector | Pi extension masking credentials in tool results (MIT, 1 star) | Variable-name and value-format matching; masks after 10 exposed characters; guards against accidents, not hostile models | Medium: ideas for masking secrets in `varde-toz` captured output |
| 16 | https://github.com/nicobrenner/jeffy | Python package of CPU-retrainable text classifiers on frozen embeddings (119 stars, MIT) | Corrections stored and trigger retrain at a threshold (default 50); local HTTP server on 8400; no LLM fallback | Low: could classify friction records; out of scope now |
| 17 | https://claude.com/blog/reducing-cost-and-improving-performance-with-claude-platform | Anthropic blog (2026-09-08) on cutting Claude API cost: caching, removing outdated prompt instructions, effort tuning; `/claude-api` prompt-audit, hillclimb, cost-optimize | Vendor-reported: prompt-audit a further 9% cost cut with about 2 points higher accuracy; hillclimb 90.5% vs 78.6% at about one fifth the cost | High: compare prompt-audit with the token-count loop; flag stale rules in skills |
| 18 | https://claude.com/blog/how-warp-builds-self-improving-agents-on-claude | Warp (2026-08-26): base skill plus a scheduled "improver" skill proposing small edits from PR and issue feedback, merged through review | Keep skills small; separate skills from auto-written memory; filter feedback, keep humans in the loop; track evals and merge time | High: maps to the friction-to-skill loop; compare the improver pattern with `varde-improve`; keep the human-review gate and add an eval check before merge |

All seven fetched; no failures.
