# varde-review flow

Generated for human readers; agents do not load this file. Regenerate
with `varde learn check --write`; draw the graph with
`varde learn measure <skill> flow --mermaid` (thick arrow: handoff; dotted: conditional;
double border: external skill or agent). Min and max count
this skill; main adds modes the main agent runs inline, each file once.
Subagents are per dispatch (multiply by the dispatch count); * marks a
conditional dispatch.

## Files

- SKILL.md (~446 tok; routes: Check a plan against its tasks and criteria, Review a diff, branch, or code area and write down what i..., Apply the findings an earlier review already wrote down, Address review threads or failing checks on an open GitHu..., Tidy up a just-committed change — naming, redundancy, con..., Fix one named, already recorded standalone finding)
  - references/conform.md (~227 tok; routes: Check a plan against its tasks and criteria, Review a diff, branch, or code area and write down what i...)
  - references/fix.md (~520 tok; routes: Apply the findings an earlier review already wrote down, Address review threads or failing checks on an open GitHu..., Fix one named, already recorded standalone finding)
  - references/report.md (~455 tok; routes: Review a diff, branch, or code area and write down what i...)
    - references/report-categories.md (~564 tok; routes: Review a diff, branch, or code area and write down what i...)
    - references/report-format.md (~937 tok; routes: Review a diff, branch, or code area and write down what i...)
  - references/simplify.md (~278 tok; routes: Tidy up a just-committed change — naming, redundancy, con...)
  - references/test-quality.md (~279 tok; routes: -)
  - references/varde-code-cli.md (~54 tok; routes: -)

## Routes

| Route | Min tokens | Max tokens | Main min | Main max | Subagents per dispatch | Lookups | Files |
|---|---|---|---|---|---|---|---|
| Check a plan against its tasks and criteria | ~673 | ~673 | ~673 | ~673 | - | 0 | references/conform.md |
| Review a diff, branch, or code area and write down what i... | ~2629 | ~2629 | ~2629 | ~2629 | - | 0 | references/report.md, references/report-categories.md, references/conform.md, references/report-format.md |
| Apply the findings an earlier review already wrote down | ~966 | ~966 | ~966 | ~966 | - | 0 | references/fix.md |
| Address review threads or failing checks on an open GitHu... | ~966 | ~966 | ~966 | ~966 | - | 0 | references/fix.md |
| Tidy up a just-committed change — naming, redundancy, con... | ~724 | ~724 | ~724 | ~724 | - | 0 | references/simplify.md |
| Fix one named, already recorded standalone finding | ~966 | ~966 | ~966 | ~966 | - | 0 | references/fix.md |

## How topics

Loaded on request with `varde learn how`; a route adds its tokens when it needs one.

| Topic | Tokens |
|---|---|
| varde-review/conform-steps | ~215 |
| varde-review/fix-loop | ~277 |
| varde-review/fix-pr-source | ~110 |
| varde-review/fix-verify | ~182 |
| varde-review/gotchas | ~234 |
| varde-review/pipeline-mode | ~135 |
| varde-review/report-review | ~320 |
| varde-review/report-steps | ~302 |
| varde-review/scan-findings | ~90 |
| varde-review/simplify-steps | ~326 |
| varde-review/standalone-finding | ~122 |
| varde-review/test-fixes | ~206 |

## Structure

| Measure | Value | Target | Status |
|---|---|---|---|
| Mutual links | 0 | 0 | ok |
| Max links out of one file | 3 (references/report.md) | < 6 | ok |
| Average links per linking file | 3.0 (3 links, 1 file) | <= 2 | warning |
| Cross-module edges | 1 | - | - |
| Max route cyclomatic | 3 | <= 10 | ok |
| Max route cognitive | 4 | <= 10 warn, <= 15 error | ok |
| Most files reached by one route | 4 (Review a diff, branch, or code area and write down what i...) | <= 15 | ok |

- density: average 3.0 links per linking file (target <= 2)

## Findings

- chain: references/report-categories.md <- references/report.md
- single caller: references/report.md <- SKILL.md: Review a diff, branch, or code area and write down what i...
- single caller: references/simplify.md <- SKILL.md: Tidy up a just-committed change — naming, redundancy, con...
- shared: references/conform.md <- SKILL.md: Check a plan against its tasks and criteria; references/report.md
- shared: references/fix.md <- SKILL.md: Address review threads or failing checks on an open GitHu...; SKILL.md: Apply the findings an earlier review already wrote down; SKILL.md: One recorded finding
