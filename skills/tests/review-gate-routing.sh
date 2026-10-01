#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
python3 - "$repo_root" <<'PY'
from pathlib import Path
import sys

root = Path(sys.argv[1])
checks = 0

def contains(relative, *needles):
    global checks
    path = root / relative
    text = " ".join(path.read_text(encoding="utf-8").split())
    missing = [needle for needle in needles if needle not in text]
    if missing:
        raise SystemExit(f"FAIL: {relative} is missing: {missing}")
    checks += len(needles)


gate_path = "skills/shared/references/review-gates.md"

# Core gates remain mandatory outside the mechanical exception; each branch is
# loaded only for its operation.
contains(gate_path,
    "Mechanical edit exception", "entire diff", "exact operational meaning",
    "mixed or uncertain diffs", "targeted checks", "Existing review subjects",
    "Skill edits still get `varde-agent-doc-authoring` review",
    "Take the full gate for mixed or uncertain diffs and for changes to any of: - commands - paths - conditions - instruction meaning - output contracts - configuration - code - tests",
    "review init --subject <safe-id> --contract <contract.json>",
    "--checkpoint start", "--checkpoint resume", "--checkpoint complete",
    "stop implementation", "manual fallback", "shared contracts",
    "exact approval checkout",
    "references/review-gate-record.md", "before writing", "either phase",
    "references/review-gate-plan.md", "Persisted plan",
    "references/review-gate-worktree.md", "before dispatch",
    "--artifact", "absolute", "file",
)
branches = {
    "review-gate-record.md": [
        "data.record_template",
        "data.version", "data.subject.subject_id", "schema_version",
        "review inspect --subject <subject-id> --phase <pre-edit|implementation> --json",
        "review record --subject <subject-id>",
        "failing test before implementation",
    ],
    "review-gate-plan.md": [
        "review init --plan <plan.md>", "review contract", "review expand",
        "Tasks inherit", "aggregate", "conclude",
    ],
    "review-gate-worktree.md": [
        "review bind-worktree", "review abandon-worktree", "--binding",
        "--worktree", "parents", "live bindings", "completion",
    ],
}
for branch, needles in branches.items():
    relative = f"skills/shared/references/{branch}"
    if not (root / relative).is_file():
        raise SystemExit(f"FAIL: missing conditional gate reference {branch}")
    contains(relative, *needles)
contains("skills/varde-change/references/build-micro-change.md",
    "mechanical edit exception", "entire diff", "An existing review subject",
    "review init --subject <safe-id>",
    "--checkpoint start",
    "complete",
)
contains("skills/varde-change/references/build.md",
    "planning_ready",
    "implementation_ready",
    "do not dispatch implementation until its start or resume check passes",
)
contains("skills/varde-change/references/build.md",
    "--checkpoint start --json",
    "--checkpoint resume --json",
)
contains("skills/shared/references/review-gate-plan.md",
    "readiness.data.planning_ready",
    "readiness.data.implementation_ready",
)
contains("skills/varde-change/references/build-execution.md",
    "--checkpoint start --json",
    "--checkpoint resume",
    "Tasks inherit that subject",
)
contains("skills/varde-change/references/plan.md",
    "review init --plan <plan.md>",
    "review record",
    "keep the subject id in plan Progress",
)
contains("skills/varde-change/references/build-finish.md",
    "Finish all source and documentation edits",
    "phase `implementation`",
    "--checkpoint complete --json",
    "varde-workflow conclude <plan.md> --json",
)
finish = " ".join((root / "skills/varde-change/references/build-finish.md").read_text().split())
if not (finish.index("Finish all source and documentation edits") <
        finish.index("phase `implementation`") <
        finish.index("--checkpoint complete --json") <
        finish.index("varde-workflow conclude <plan.md> --json")):
    raise SystemExit("FAIL: final review/check must follow changes and precede conclude")
checks += 1
contains("skills/shared/references/review-gate-record.md",
    "review inspect --subject <subject-id>",
    "review record --subject <subject-id>",
)
contains("skills/shared/references/review-gate-plan.md",
    "`review contract`",
    "`review expand`",
)
contains("skills/shared/references/varde-workflow-cli.md",
    "Never replace approval with prose",
    "fallback below applies only to reads and planning/bookkeeping",
    "gated implementation/completion operations; if unavailable, stop those operations",
)
contains("skills/varde-review/references/report.md",
    "Review-gate evidence",
    "references/review-gate-record.md",
)
contains("skills/shared/references/review-gate-record.md",
    "review record",
    "`data.version`",
    "coordinator-written approval is insufficient",
)
contains("clis/workflow/README.md",
    "varde-workflow review init --plan",
    "varde-workflow review inspect",
    "varde-workflow review record",
    "varde-workflow review check",
    "planning_ready",
    "implementation_ready",
)
contains("memory-bank/knowledge/reference/workflow-artifact-kernel.md",
    "## Review evidence",
    "immutable scoped baseline",
    "required for gated work",
)
contains("memory-bank/knowledge/reference/workflow-schema.md",
    "`planning_ready`",
    "`implementation_ready`",
    "review checkpoint",
)
contains("memory-bank/knowledge/reference/workflow-conclusion.md",
    "review prerequisites",
    "evidence must cover the complete subject change",
    "consumed review and source revisions",
)

print(f"Review gate routing checks passed ({checks} assertions).")
PY
