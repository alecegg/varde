---
type: reference
status: current
date: 2026-11-01
---

# Exploration notes: GoodLinks rows #4, #6-#11

Read by a Haiku explorer on 2026-11-01 (rendered pages only; unverified). Row numbers refer to `goodlinks-ai-links.md`. Row #5 is covered in an earlier note. Figures are as shown on the page.

| # | Link | What it is | Mechanisms and claims | Varde relevance |
|---:|---|---|---|---|
| 4 | https://github.com/aicodeking/deepseek-stack | SKILL.md collection for planning, verifying and shipping with DeepSeek models (103 stars, MIT) | Loop skills have hard round caps (verify max 5, review max 4); ship skills need `gh` and `python3` | Low: bounded rounds match our two-round review gate |
| 6 | https://destiner.io/blog/post/pi-is-the-last-harness/ | Opinion (2026-11-01): Pi, open and vendor-agnostic, will be the last widely adopted harness | Text-in text-out core, optional features, an "engine" substrate with unified providers and compaction | Low: context only; some Paseo workers already use Pi |
| 7 | https://github.com/Nutlope/hallmark | Design skill to stop generated pages looking AI-made (44.8k stars, MIT) | Three tiers: Floor never ships, Reflex overridable with a reason, Finish never blocks; `sloplint --render` at eight widths | Medium: severity tiers could clarify which `varde-design` checks block |
| 8 | https://github.com/Leonxlnx/taste-skill | Skill building sites from one of 20 art directions (about 107.7k stars, MIT) | Six-step build; script deals three directions; only public-domain/CC0/CC BY/CC BY-SA images; up to three fix rounds | Low: overlaps `varde-design`; license-filtered image sourcing only |
| 9 | https://github.com/pbakaus/impeccable | Design commands plus a deterministic anti-"AI slop" detector for about 20 agents (about 99.3k stars, Apache-2.0) | 24 slash commands; 62 detector rules, "No LLM, no API key"; `npx impeccable detect` for CI | Medium: compare its 62 rules with the `varde-design` rule set for gaps |
| 10 | https://github.com/cathrynlavery/diagram-design | Skill producing single-file HTML+SVG diagrams, 45 types (about 63.9k stars, MIT) | One type reference loaded per request; 4px grid, one accent colour; WCAG AA checks; imports draw.io, Mermaid, Excalidraw | Low: grid and contrast rules could inform `varde-visualize` output checks |
| 11 | https://contextfirst.blog/superlite-hand-an-agent-a-spec/ | superlite (2026-10-18, updated 10-22): Claude Code plugin for parallel autonomous builds from a spec | Hooks stop the coordinator editing code; task graphs with owned files; Opus/Sonnet/Haiku tiers; rulings log; self-run benchmarks the author calls "a strong hint" | Medium: hook-enforced "coordinator cannot edit" matches our orchestrator rule; consider a hook (claims unverified; partial read) |

Star counts are as displayed; some are implausibly high and unverified.
