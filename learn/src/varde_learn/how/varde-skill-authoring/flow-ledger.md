---
topic: varde-skill-authoring/flow-ledger
version: 1
summary: Flow ledger intro and choice - generate or refresh; the auditor subagent writes it, no API key
---

# Flow ledger

A flow ledger lists a skill's workflow decisions with cited source lines, so `varde learn measure <skill> ledger` can score full-flow complexity offline. An auditor subagent writes it; no API key or direct model call is involved.

Run `varde learn measure <ledger.json> ledger [--root DIR] [--json]`; `score` also takes `--route NAME`. Cited paths are relative to `--root` (default: the current Git top level).

## Choose generate or refresh

| Situation | Do |
|---|---|
| No ledger yet, or an audit of an external skill or repo | Generate |
| A ledger exists and sources changed | Refresh |

`ledger check` exits 0 when no existing decision's cited lines changed. It cannot see new decisions, so refresh still inspects changed instruction files.
