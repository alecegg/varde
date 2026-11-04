---
topic: varde-orchestrate/pipeline-recovery
version: 1
summary: Record handoff completion and reclaim slots after a crash
---

# Pipeline recovery

- Native Stop hooks keep blocking until handoff completion is recorded. Record each boundary with `varde hook pipeline-handoff-complete --harness <claude|codex|paseo> --session <id> --turn <n>`; Paseo also needs `--plan-dir <abs-plan-dir> --slot <slot>`. The replacement continues from the checkpoint, `plan.md` and open comments.
- After a crash run `varde plan slot reclaim`; stale slots go dead and their items return to queued. The idle reaper parks a slot instead, so a resumed session keeps its claims.
