# varde-review flow

Generated for human readers; agents do not load this file. Regenerate
with skill-flow.py --write from varde-agent-doc-authoring. Dotted edges
are conditional loads; min tokens follow only solid edges. Thick edges
are hand-offs to a later stage, outside min and max. Double-bordered
nodes are skill modes run inline or agent dispatches. Min and max count
this skill; main adds modes the main agent runs inline, each file once.
Subagents are per dispatch (multiply by the dispatch count); * marks a
conditional dispatch. Module overview first, then one diagram per module.

## Files

- SKILL.md (~611 tok; routes: Review a diff, branch, or code area and write down what i..., Apply the findings an earlier review already wrote down, Address review threads or failing checks on an open GitHu..., Inspect a running web, iOS simulator, or macOS app visual..., Tidy up what was just changed — naming, redundancy, consi..., Run a varde-code scan and decide what its findings mean, Fix one named, already recorded standalone finding)
  - references/fix.md (~1530 tok; routes: Apply the findings an earlier review already wrote down, Address review threads or failing checks on an open GitHu..., Fix one named, already recorded standalone finding)
    - references/fix-pass.md (~1202 tok; routes: Apply the findings an earlier review already wrote down, Address review threads or failing checks on an open GitHu..., Fix one named, already recorded standalone finding)
  - references/report.md (~1193 tok; routes: Review a diff, branch, or code area and write down what i...)
    - references/report-categories.md (~1070 tok; routes: Review a diff, branch, or code area and write down what i..., Inspect a running web, iOS simulator, or macOS app visual...)
    - references/report-format.md (~932 tok; routes: Review a diff, branch, or code area and write down what i..., Apply the findings an earlier review already wrote down, Address review threads or failing checks on an open GitHu..., Inspect a running web, iOS simulator, or macOS app visual..., Run a varde-code scan and decide what its findings mean, Fix one named, already recorded standalone finding)
  - references/review-gate-plan.md (~508 tok; routes: Review a diff, branch, or code area and write down what i..., Apply the findings an earlier review already wrote down, Address review threads or failing checks on an open GitHu..., Inspect a running web, iOS simulator, or macOS app visual..., Tidy up what was just changed — naming, redundancy, consi..., Run a varde-code scan and decide what its findings mean, Fix one named, already recorded standalone finding)
  - references/review-gate-record.md (~546 tok; routes: Review a diff, branch, or code area and write down what i...)
  - references/review-gate-worktree.md (~469 tok; routes: Review a diff, branch, or code area and write down what i..., Apply the findings an earlier review already wrote down, Address review threads or failing checks on an open GitHu..., Inspect a running web, iOS simulator, or macOS app visual..., Tidy up what was just changed — naming, redundancy, consi..., Run a varde-code scan and decide what its findings mean, Fix one named, already recorded standalone finding)
  - references/review-gates.md (~1352 tok; routes: Review a diff, branch, or code area and write down what i..., Apply the findings an earlier review already wrote down, Address review threads or failing checks on an open GitHu..., Inspect a running web, iOS simulator, or macOS app visual..., Tidy up what was just changed — naming, redundancy, consi..., Run a varde-code scan and decide what its findings mean, Fix one named, already recorded standalone finding)
  - references/scan.md (~1081 tok; routes: Run a varde-code scan and decide what its findings mean)
  - references/simplify.md (~510 tok; routes: Tidy up what was just changed — naming, redundancy, consi...)
  - references/varde-code-cli.md (~46 tok; routes: Review a diff, branch, or code area and write down what i..., Tidy up what was just changed — naming, redundancy, consi...)
  - references/visual.md (~986 tok; routes: Inspect a running web, iOS simulator, or macOS app visual...)

```mermaid
flowchart TD
  m0["fix (2 files)"]
  m1["report (3 files)"]
  m2["review (4 files)"]
  m3["scan (1 file)"]
  m4["scripts (5 files)"]
  m5["simplify (1 file)"]
  m6["visual (1 file)"]
  m0 -->|"2"| m1
  m0 -->|"2"| m4
  m1 -->|"1"| m2
  m2 -->|"2"| m4
  m3 -->|"1"| m1
  m5 -->|"1"| m4
  m6 -->|"3"| m1
```

### fix

```mermaid
flowchart TD
  n0["references/fix-pass.md (~1202 tok)"]
  n1["references/fix.md (~1530 tok)"]
  n2["report"]
  n3["scripts"]
  n0 --> n3
  n1 --> n0
  n1 --> n2
  n1 --> n3
```

### report

```mermaid
flowchart TD
  n0["references/report-categories.md (~1070 tok)"]
  n1["references/report-format.md (~932 tok)"]
  n2["references/report.md (~1193 tok)<br/>ref: references/varde-code-cli.md (~46 tok)"]
  n3["fix"]
  n4["review"]
  n5["scan"]
  n6["visual"]
  n3 --> n1
  n2 -.-> n0
  n2 --> n1
  n2 -.-> n4
  n5 --> n1
  n6 --> n0
  n6 --> n1
```

### review

```mermaid
flowchart TD
  n0["references/review-gate-plan.md (~508 tok)"]
  n1["references/review-gate-record.md (~546 tok)"]
  n2["references/review-gate-worktree.md (~469 tok)"]
  n3["references/review-gates.md (~1352 tok)"]
  n4["report"]
  n5["scripts"]
  n4 -.-> n1
  n0 --> n5
  n3 -.-> n0
  n3 -.-> n2
  n3 --> n5
```

### scan

```mermaid
flowchart TD
  n0["references/scan.md (~1081 tok)"]
  n1["report"]
  n0 --> n1
```

### scripts

```mermaid
flowchart TD
  n0["scripts/change-ranges.sh"]
  n1["scripts/pr-intake.py"]
  n2["scripts/review-scope.sh"]
  n3["scripts/risk-tier.py"]
  n4["scripts/snapshot.sh"]
  n5["fix"]
  n6["review"]
  n7["simplify"]
  n5 --> n4
  n5 --> n1
  n6 --> n3
  n7 --> n4
```

### simplify

```mermaid
flowchart TD
  n0["references/simplify.md (~510 tok)<br/>ref: references/varde-code-cli.md (~46 tok)"]
  n1["scripts"]
  n0 --> n1
```

### visual

```mermaid
flowchart TD
  n0["references/visual.md (~986 tok)"]
  n1["report"]
  n0 --> n1
```

## Routes

| Route | Min tokens | Max tokens | Main min | Main max | Subagents per dispatch | Lookups | Files |
|---|---|---|---|---|---|---|---|
| Review a diff, branch, or code area and write down what i... | ~3852 | ~6727 | ~3852 | ~6727 | review* ~3406, review* ~4749-7624 | 0 | references/report.md, references/review-gates.md, references/report-categories.md, references/report-format.md, references/varde-code-cli.md, references/review-gate-record.md, references/review-gate-plan.md, references/review-gate-worktree.md, scripts/risk-tier.py |
| Apply the findings an earlier review already wrote down | ~4275 | ~6604 | ~4275 | ~6604 | review ~3406, executor* ~3573, executor ~3823-7625, review* ~4749-7624 | 0 | references/fix.md, references/review-gates.md, references/fix-pass.md, references/report-format.md, scripts/pr-intake.py, references/review-gate-plan.md, references/review-gate-worktree.md, scripts/risk-tier.py, scripts/snapshot.sh |
| Address review threads or failing checks on an open GitHu... | ~4275 | ~6604 | ~4275 | ~6604 | review ~3406, executor* ~3573, executor ~3823-7625, review* ~4749-7624 | 0 | references/fix.md, references/review-gates.md, references/fix-pass.md, references/report-format.md, scripts/pr-intake.py, references/review-gate-plan.md, references/review-gate-worktree.md, scripts/risk-tier.py, scripts/snapshot.sh |
| Inspect a running web, iOS simulator, or macOS app visual... | ~3599 | ~5928 | ~3599 | ~5928 | review* ~3406, review* ~4749-7624 | 0 | references/visual.md, references/review-gates.md, references/report-format.md, references/report-categories.md, references/review-gate-plan.md, references/review-gate-worktree.md, scripts/risk-tier.py |
| Tidy up what was just changed — naming, redundancy, consi... | ~1167 | ~3496 | ~1167 | ~3496 | review* ~3406, review* ~4749-7624 | 0 | references/simplify.md, references/review-gates.md, references/varde-code-cli.md, scripts/snapshot.sh, references/review-gate-plan.md, references/review-gate-worktree.md, scripts/risk-tier.py |
| Run a varde-code scan and decide what its findings mean | ~2624 | ~4953 | ~2624 | ~4953 | review* ~3406, review* ~4749-7624 | 0 | references/scan.md, references/review-gates.md, references/report-format.md, references/review-gate-plan.md, references/review-gate-worktree.md, scripts/risk-tier.py |
| Fix one named, already recorded standalone finding | ~4275 | ~6604 | ~6619 | ~10382 | review ~3406, review ~4749-7624, executor* ~3573, executor ~3823-7625 | 0 | references/fix.md, references/review-gates.md, references/fix-pass.md, references/report-format.md, scripts/pr-intake.py, references/review-gate-plan.md, references/review-gate-worktree.md, scripts/risk-tier.py, scripts/snapshot.sh |

## Structure

| Measure | Value | Target | Status |
|---|---|---|---|
| Mutual links | 0 | 0 | ok |
| Max links out of one file | 4 (references/report.md) | < 6 | ok |
| Average links per linking file | 2.12 (17 links, 8 files) | <= 2 | warning |
| Cross-module edges | 12 | - | - |
| Diagram edges | 46 | <= 60 | ok |
| Max route cyclomatic | 8 | <= 10 | ok |
| Max route cognitive | 15 | <= 10 warn, <= 15 error | warning |
| Most files reached by one route | 9 (Review a diff, branch, or code area and write down what i...) | <= 15 | ok |

- density: average 2.12 links per linking file (target <= 2)

## Findings

- chain: references/fix-pass.md <- references/fix.md
- single caller: references/report.md <- SKILL.md: Review a diff, branch, or code area and write down what i...
- single caller: references/scan.md <- SKILL.md: Run a varde-code scan and decide what its findings mean
- single caller: references/simplify.md <- SKILL.md: Tidy up what was just changed — naming, redundancy, consi...
- single caller: references/visual.md <- SKILL.md: Inspect a running web, iOS simulator, or macOS app visual...
- shared: references/fix.md <- SKILL.md: Address review threads or failing checks on an open GitHu...; SKILL.md: Apply the findings an earlier review already wrote down; SKILL.md: One recorded finding
- shared: references/report-categories.md <- references/report.md; references/visual.md
- shared: references/report-format.md <- references/fix.md; references/report.md; references/scan.md; references/visual.md
