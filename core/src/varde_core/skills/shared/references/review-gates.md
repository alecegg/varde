<!-- kind: reference -->
# Independent review gates

Gate every implementation change (source, configuration, documentation, fixes,
refactors, prototypes in source). Read-only investigation, workflow bookkeeping,
and prototype files under `<working>` need no gate.

## Review gates

| Gate | When | Output and owner |
|---|---|---|
| Gate | Every task commit, and the last task commit again at finish. Standalone changes use a full-diff report. | Review structure, ownership, size, declared checks, scan, and doc lint; `varde plan gate` prints `GATE-NNN` failures. It does not persist them; the orchestrator records failures in `review.md` when it chooses to persist them. |
| Plan review | Once per plan, at finish, over `base..HEAD`. It covers architecture, code, and conformance in one pass. | Macro architecture and code findings, `SPEC-NNN` findings in a plan-level `## Conformance` section, and the final header/verdict in `review.md`; `varde plan conclude` checks approved, head, and open high-severity findings. |

Every text change also gets an authoring review with the authoring skill for its
kind (skill or agent document, or doc), picked from your skill list. For a skill or agent document, one clean-context reviewer covers both reviews. The reviewer
does not approve its own work; one fixer applies findings.

## Review rounds

A plan gets one plan review, one builder fix pass, and one fixes-only re-check.
Tasks get no separate agent review; the Gate row is their only check. A
standalone change with no plan keeps one full-diff review.
Escalate to the user only a high-severity finding the fix pass cannot fix.
