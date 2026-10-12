#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
python3 - "$repo_root" <<'PY'
from pathlib import Path
import sys

root = Path(sys.argv[1])
checks = 0


def text(relative):
    return " ".join((root / relative).read_text(encoding="utf-8").split())


def contains(relative, *needles):
    global checks
    body = text(relative)
    missing = [needle for needle in needles if needle not in body]
    if missing:
        raise SystemExit(f"FAIL: {relative} is missing: {missing}")
    checks += len(needles)


def excludes(relative, *needles):
    global checks
    body = text(relative)
    present = [needle for needle in needles if needle in body]
    if present:
        raise SystemExit(f"FAIL: {relative} still contains: {present}")
    checks += len(needles)


gate = "skills/shared/references/review-gates.md"

# One independent review per change, two axes, one fixer, and the report header.
contains(gate,
    "One independent review per plan or change",
    "since a fixed `base` commit",
    "Spec",
    "Standards",
    "one fixer",
    "`review.md`",
    "`verdict`",
    "`approved`",
    "`changes-requested`",
    "`reviewer`",
    "`head`",
)
# Every text change gets the doc-authoring review, stated here once.
contains(gate, "Every text change", "varde-agent-doc-authoring")
# The fix re-check rules.
contains(gate,
    "fixes-only re-review",
    "block only at critical or high",
    "header-only re-check",
    "holds only the named fixes",
    "rewrites `head`",
)
# `varde plan conclude` is the only gate.
contains(gate, "varde plan conclude", "is the only gate")
# The removed machinery stays out of the shared gate text.
excludes(gate,
    "Mechanical edit exception",
    "start-bounded",
    "checkpoint",
    "tier",
    "review subject",
    "--subject",
    "review-gate-",
)

# Only the surviving shared gate reference ships; the removed gate references
# and the shared tier script leave no file behind.
refs = sorted(path.name for path in (root / "skills/shared/references").glob("review-gate*"))
if refs != ["review-gates.md"]:
    raise SystemExit(f"FAIL: unexpected shared gate references: {refs}")
checks += 1
if (root / "skills/shared/scripts").exists():
    raise SystemExit("FAIL: skills/shared/scripts should be gone with the tier script")
checks += 1

# MANIFEST installs only surviving shared files, and no longer sends
# review-gates.md to varde-review.
manifest = {}
for line in (root / "skills/shared/MANIFEST").read_text(encoding="utf-8").splitlines():
    if line.strip():
        parts = line.split()
        manifest[parts[0]] = parts[1:]
gate_entries = sorted(path for path in manifest if path.startswith("references/review-gate"))
if gate_entries != ["references/review-gates.md"]:
    raise SystemExit(f"FAIL: MANIFEST lists stale gate files: {gate_entries}")
checks += 1
recipients = manifest.get("references/review-gates.md", [])
if "varde-review" in recipients:
    raise SystemExit("FAIL: MANIFEST still installs review-gates.md into varde-review")
checks += 1
# Each recipient must name the reference it receives.
for skill in recipients:
    if not any("references/review-gates.md" in path.read_text(encoding="utf-8")
               for path in (root / "skills" / skill).rglob("*.md")):
        raise SystemExit(f"FAIL: {skill} installs review-gates.md but never names it")
    checks += 1

# The CLI reference keeps the fallback rule and names no removed command.
contains("skills/shared/references/varde-workflow-cli.md",
    "Never replace approval with prose",
    "When `varde` is missing: stop every operation, reads included",
    "varde setup sync",
)
excludes("skills/shared/references/varde-workflow-cli.md",
    "review inspect",
    "transition",
    "recover",
    "escalate-deferred",
    "varde plan review",
)

print(f"Review gate routing checks passed ({checks} assertions).")
PY
