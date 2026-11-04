# Distill recurring friction into an approved improvement

Run this workflow only when the user asks to review recurring friction.

## Outcomes

- Open items come from `varde learn friction list --status open --json`, inspected with `varde learn friction show <ID> --json`.
- Require two real occurrences of the same obstacle and a shared improvement target. If evidence does not establish both, report it as insufficient and propose nothing.
- The current source and guidance are inspected, and the proposed change is classified as one of:
  - adding a missing rule;
  - tightening an underspecified rule;
  - relaxing/removing a rule, gate, or required step that is ignored, contradicted, obsolete, or too strict.
- Relaxing is weighed before tightening; to relax a safety, permission, or approval check, name the failure it prevents and why that risk is acceptable. The option and audit rules in `references/options.md` apply. Prefer a small source change over repeating guidance more loudly.
- The target may be anywhere that changes agent behavior:
  - the user's instructions or memory;
  - harness or sandbox configuration;
  - the project's repository;
  - a Varde skill or CLI;
  - a drafted upstream issue.
- The proposal presents, and offers a before/after evaluation on identical cases (validate: each is present):
  - source item IDs and each occurrence's evidence;
  - the shared failure mode;
  - exact target files or symbols and the proposed diff;
  - expected impact as a hypothesis, and risks;
  - items that would become `promoted`.
- Approval is requested for the exact source scope, installed copies included, and separately for billed eval runs with cost (`evals × configs × runs × 2` judge-graded calls). The request to review friction implies neither. Approved evals run their cases before the change (`varde learn measure <skill-dir> output`) and the same cases after it; the results are compared.
- The approved source change is made as a bounded edit, planned first when scope is unsettled.
- After the change, one adoption is recorded for its source items with `varde learn friction adopt --items <ids> --summary <text> --files <paths> [--commit <sha>] [--eval-before <path> --eval-after <path>] --json`. Validate: `--commit` only for a verified commit, eval paths only for approved, completed runs.
- Recording promotes every listed item and appends its status history in one transaction, so run no separate status command; report a failure.
