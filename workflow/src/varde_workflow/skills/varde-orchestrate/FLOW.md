# varde-orchestrate flow

Generated for human readers; agents do not load this file. Regenerate
with `varde learn check --write`; draw the graph with
`varde learn measure <skill> flow --mermaid` (thick arrow: handoff; dotted: conditional;
double border: external skill or agent). Min and max count
this skill; main adds modes the main agent runs inline, each file once.
Subagents are per dispatch (multiply by the dispatch count); * marks a
conditional dispatch.

## Files

- SKILL.md (~511 tok; routes: Progress reply to main, Finish the plan, Dispatch a reviewer, A command was denied, Change a status)
  - references/build-finish.md (~482 tok; routes: Finish the plan)
  - references/main-agent-replies.md (~78 tok; routes: Progress reply to main)
  - references/review-gates.md (~408 tok; routes: Dispatch a reviewer)
  - references/varde-workflow-cli.md (~215 tok; routes: A command was denied)
  - references/workflow-state.md (~98 tok; routes: Change a status)

## Routes

| Route | Min tokens | Max tokens | Main min | Main max | Subagents per dispatch | Lookups | Files |
|---|---|---|---|---|---|---|---|
| Progress reply to main | ~589 | ~589 | ~589 | ~589 | - | 0 | references/main-agent-replies.md |
| Finish the plan | ~993 | ~993 | ~993 | ~993 | - | 0 | references/build-finish.md |
| Dispatch a reviewer | ~919 | ~919 | ~919 | ~919 | review ~1499 | 0 | references/review-gates.md |
| A command was denied | ~726 | ~726 | ~726 | ~726 | - | 0 | references/varde-workflow-cli.md |
| Change a status | ~609 | ~609 | ~609 | ~609 | - | 0 | references/workflow-state.md |

## How topics

Loaded on request with `varde learn how`; a route adds its tokens when it needs one.

| Topic | Tokens |
|---|---|
| varde-orchestrate/dispatch | ~296 |
| varde-orchestrate/finish-steps | ~315 |
| varde-orchestrate/finish-wrapup | ~186 |
| varde-orchestrate/integration | ~268 |
| varde-orchestrate/launch-checks | ~153 |
| varde-orchestrate/merge-approval | ~158 |
| varde-orchestrate/pipeline-checkpoints | ~182 |
| varde-orchestrate/pipeline-eligibility | ~168 |
| varde-orchestrate/pipeline-handoff | ~252 |
| varde-orchestrate/pipeline-mode | ~328 |
| varde-orchestrate/pipeline-recovery | ~165 |
| varde-orchestrate/pipeline-review | ~230 |
| varde-orchestrate/plan-setup | ~294 |
| varde-orchestrate/relay-shapes | ~176 |
| varde-orchestrate/reporting | ~259 |
| varde-orchestrate/review-wave | ~144 |
| varde-orchestrate/watchdog | ~276 |
| varde-orchestrate/worker-launch | ~277 |
| varde-orchestrate/worker-loop | ~334 |

## Structure

| Measure | Value | Target | Status |
|---|---|---|---|
| Mutual links | 0 | 0 | ok |
| Max links out of one file | 0 | < 6 | ok |
| Average links per linking file | 0 (0 links, 0 files) | <= 2 | ok |
| Cross-module edges | 0 | - | - |
| Max route cyclomatic | 1 | <= 10 | ok |
| Max route cognitive | 0 | <= 10 warn, <= 15 error | ok |
| Most files reached by one route | 1 (Progress reply to main) | <= 15 | ok |

## Findings

- single caller: references/build-finish.md <- SKILL.md: Finish the plan
- unreferenced: scripts/worktree-cleanup.sh
- unreferenced: scripts/worktree-create.sh
- unreferenced: scripts/worktree-merge.sh
- unreferenced: scripts/worktree-wave.sh
