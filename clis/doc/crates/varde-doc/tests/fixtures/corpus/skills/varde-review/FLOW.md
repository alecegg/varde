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

- SKILL.md (~608 tok; routes: Review a diff, branch, or code area and write down what i..., Apply the findings an earlier review already wrote down, Address review threads or failing checks on an open GitHu..., Inspect a running web, iOS simulator, or macOS app visual..., Tidy up what was just changed — naming, redundancy, consi..., Run a varde scan and decide what its findings mean, Fix one named, already recorded standalone finding)
  - references/fix.md (~1910 tok; routes: Apply the findings an earlier review already wrote down, Address review threads or failing checks on an open GitHu..., Fix one named, already recorded standalone finding)
  - references/report.md (~1214 tok; routes: Review a diff, branch, or code area and write down what i...)
    - references/report-categories.md (~1154 tok; routes: Review a diff, branch, or code area and write down what i..., Apply the findings an earlier review already wrote down, Address review threads or failing checks on an open GitHu..., Inspect a running web, iOS simulator, or macOS app visual..., Fix one named, already recorded standalone finding)
    - references/report-format.md (~955 tok; routes: Review a diff, branch, or code area and write down what i..., Apply the findings an earlier review already wrote down, Address review threads or failing checks on an open GitHu..., Inspect a running web, iOS simulator, or macOS app visual..., Run a varde scan and decide what its findings mean, Fix one named, already recorded standalone finding)
  - references/review-gate-plan.md (~538 tok; routes: Review a diff, branch, or code area and write down what i..., Apply the findings an earlier review already wrote down, Address review threads or failing checks on an open GitHu..., Inspect a running web, iOS simulator, or macOS app visual..., Tidy up what was just changed — naming, redundancy, consi..., Run a varde scan and decide what its findings mean, Fix one named, already recorded standalone finding)
  - references/review-gate-record.md (~544 tok; routes: Review a diff, branch, or code area and write down what i...)
  - references/review-gate-worktree.md (~494 tok; routes: Review a diff, branch, or code area and write down what i..., Apply the findings an earlier review already wrote down, Address review threads or failing checks on an open GitHu..., Inspect a running web, iOS simulator, or macOS app visual..., Tidy up what was just changed — naming, redundancy, consi..., Run a varde scan and decide what its findings mean, Fix one named, already recorded standalone finding)
  - references/review-gates.md (~1551 tok; routes: Review a diff, branch, or code area and write down what i..., Apply the findings an earlier review already wrote down, Address review threads or failing checks on an open GitHu..., Inspect a running web, iOS simulator, or macOS app visual..., Tidy up what was just changed — naming, redundancy, consi..., Run a varde scan and decide what its findings mean, Fix one named, already recorded standalone finding)
  - references/scan.md (~1079 tok; routes: Run a varde scan and decide what its findings mean)
  - references/simplify.md (~509 tok; routes: Tidy up what was just changed — naming, redundancy, consi...)
  - references/varde-code-cli.md (~53 tok; routes: Review a diff, branch, or code area and write down what i..., Tidy up what was just changed — naming, redundancy, consi...)
  - references/visual.md (~1072 tok; routes: Apply the findings an earlier review already wrote down, Address review threads or failing checks on an open GitHu..., Inspect a running web, iOS simulator, or macOS app visual..., Fix one named, already recorded standalone finding)

```mermaid
flowchart TD
  m0["fix (1 file)"]
  m1["report (3 files)"]
  m2["review (4 files)"]
  m3["scan (1 file)"]
  m4["scripts (5 files)"]
  m5["simplify (1 file)"]
  m6["visual (1 file)"]
  m0 -->|"2"| m1
  m0 -->|"1"| m4
  m0 -->|"1"| m6
  m1 -->|"1"| m2
  m2 -->|"2"| m4
  m3 -->|"1"| m1
  m5 -->|"1"| m4
  m6 -->|"3"| m1
```

### fix

```mermaid
flowchart TD
  n0["references/fix.md (~1910 tok)"]
  n1["report"]
  n2["scripts"]
  n3["visual"]
  n0 --> n1
  n0 --> n3
  n0 --> n2
```

### report

```mermaid
flowchart TD
  n0["references/report-categories.md (~1154 tok)"]
  n1["references/report-format.md (~955 tok)"]
  n2["references/report.md (~1214 tok)<br/>ref: references/varde-code-cli.md (~53 tok)"]
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
  n0["references/review-gate-plan.md (~538 tok)"]
  n1["references/review-gate-record.md (~544 tok)"]
  n2["references/review-gate-worktree.md (~494 tok)"]
  n3["references/review-gates.md (~1551 tok)"]
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
  n0["references/scan.md (~1079 tok)"]
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
  n5 --> n1
  n6 --> n3
  n7 --> n4
```

### simplify

```mermaid
flowchart TD
  n0["references/simplify.md (~509 tok)<br/>ref: references/varde-code-cli.md (~53 tok)"]
  n1["scripts"]
  n0 --> n1
```

### visual

```mermaid
flowchart TD
  n0["references/visual.md (~1072 tok)"]
  n1["fix"]
  n2["report"]
  n1 --> n0
  n0 --> n2
```

## Routes

| Route | Min tokens | Max tokens | Main min | Main max | Subagents per dispatch | Lookups | Files |
|---|---|---|---|---|---|---|---|
| Review a diff, branch, or code area and write down what i... | ~3984 | ~7111 | ~3984 | ~7111 | review* ~3595, review* ~4876-8003 | 0 | references/report.md, references/review-gates.md, references/report-categories.md, references/report-format.md, references/varde-code-cli.md, references/review-gate-record.md, references/review-gate-plan.md, references/review-gate-worktree.md, scripts/risk-tier.py |
| Apply the findings an earlier review already wrote down | ~5699 | ~8282 | ~5699 | ~8282 | review ~3595, builder ~3721-8469, builder unresolved, review* ~4876-8003 | 0 | references/fix.md, references/review-gates.md, references/report-format.md, references/visual.md, scripts/pr-intake.py, references/review-gate-plan.md, references/review-gate-worktree.md, scripts/risk-tier.py, references/report-categories.md |
| Address review threads or failing checks on an open GitHu... | ~5699 | ~8282 | ~5699 | ~8282 | review ~3595, builder ~3721-8469, builder unresolved, review* ~4876-8003 | 0 | references/fix.md, references/review-gates.md, references/report-format.md, references/visual.md, scripts/pr-intake.py, references/review-gate-plan.md, references/review-gate-worktree.md, scripts/risk-tier.py, references/report-categories.md |
| Inspect a running web, iOS simulator, or macOS app visual... | ~3789 | ~6372 | ~3789 | ~6372 | review* ~3595, review* ~4876-8003 | 0 | references/visual.md, references/review-gates.md, references/report-format.md, references/report-categories.md, references/review-gate-plan.md, references/review-gate-worktree.md, scripts/risk-tier.py |
| Tidy up what was just changed — naming, redundancy, consi... | ~1170 | ~3753 | ~1170 | ~3753 | review* ~3595, review* ~4876-8003 | 0 | references/simplify.md, references/review-gates.md, references/varde-code-cli.md, scripts/snapshot.sh, references/review-gate-plan.md, references/review-gate-worktree.md, scripts/risk-tier.py |
| Run a varde scan and decide what its findings mean | ~2642 | ~5225 | ~2642 | ~5225 | review* ~3595, review* ~4876-8003 | 0 | references/scan.md, references/review-gates.md, references/report-format.md, references/review-gate-plan.md, references/review-gate-worktree.md, scripts/risk-tier.py |
| Fix one named, already recorded standalone finding | ~5699 | ~8282 | ~9358 | ~14981 | review ~3595, review* ~4876-8003, builder ~3721-8469, builder unresolved | 0 | references/fix.md, references/review-gates.md, references/report-format.md, references/visual.md, scripts/pr-intake.py, references/review-gate-plan.md, references/review-gate-worktree.md, scripts/risk-tier.py, references/report-categories.md |

## Structure

| Measure | Value | Target | Status |
|---|---|---|---|
| Mutual links | 0 | 0 | ok |
| Max links out of one file | 4 (references/report.md) | < 6 | ok |
| Average links per linking file | 2.29 (16 links, 7 files) | <= 2 | warning |
| Cross-module edges | 12 | - | - |
| Diagram edges | 41 | <= 60 | ok |
| Max route cyclomatic | 9 | <= 10 | ok |
| Max route cognitive | 17 | <= 10 warn, <= 15 error | defect |
| Most files reached by one route | 9 (Review a diff, branch, or code area and write down what i...) | <= 15 | ok |

- density: average 2.29 links per linking file (target <= 2)

## Findings

- single caller: references/report.md <- SKILL.md: Review a diff, branch, or code area and write down what i...
- single caller: references/scan.md <- SKILL.md: Run a varde scan and decide what its findings mean
- single caller: references/simplify.md <- SKILL.md: Tidy up what was just changed — naming, redundancy, consi...
- shared: references/fix.md <- SKILL.md: Address review threads or failing checks on an open GitHu...; SKILL.md: Apply the findings an earlier review already wrote down; SKILL.md: One recorded finding
- shared: references/report-categories.md <- references/report.md; references/visual.md
- shared: references/report-format.md <- references/fix.md; references/report.md; references/scan.md; references/visual.md
- shared: references/visual.md <- SKILL.md: Inspect a running web, iOS simulator, or macOS app visual...; references/fix.md
