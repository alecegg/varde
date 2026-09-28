#!/usr/bin/env bash
set -euo pipefail

# Structural contract only: this checks routing, examples, and the implemented
# parser/store boundaries. It does not claim to test live-session semantics.
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
python3 - "$repo_root" <<'PY'
from pathlib import Path
import sys

root = Path(sys.argv[1])
checks = 0


def text(relative):
    return (root / relative).read_text(encoding="utf-8")


def contains(relative, *needles):
    global checks
    content = text(relative)
    if relative == "skills/varde-learn/references/diagnose.md":
        content += text("skills/varde-learn/references/diagnose-capture.md")
    content = " ".join(content.split()).lower()
    missing = [needle for needle in needles if needle.lower() not in content]
    if missing:
        raise SystemExit(f"FAIL: {relative} is missing: {missing}")
    checks += len(needles)


skill = text("skills/varde-learn/SKILL.md")
reference_path = root / "skills/varde-learn/references/diagnose.md"
if "references/diagnose.md" not in skill or not reference_path.is_file():
    raise SystemExit("FAIL: the varde-learn skill does not route diagnosis to a real reference")
reference = reference_path.read_text(encoding="utf-8")
checks += 1
capture = text("skills/varde-learn/references/diagnose-capture.md")
if "references/diagnose-capture.md" not in reference or "Report-only diagnosis stops here" not in reference:
    raise SystemExit("FAIL: capture details must load conditionally after report-only diagnosis")
if "## Capture eligible incidents" in reference or '"incident_kind": "failed-tool"' in reference:
    raise SystemExit("FAIL: report-only diagnosis eagerly includes capture procedure")
if "## Capture eligible incidents" not in capture:
    raise SystemExit("FAIL: conditional capture reference lost its procedure")
checks += 3

contains("skills/varde-learn/SKILL.md",
    "Diagnose an existing or current agent session",
    "references/diagnose.md",
)
contains("skills/varde-learn/references/diagnose.md",
    "varde-learn diagnose inspect --harness",
    "--current",
    "--session",
    "--path",
    "--snapshot-out",
    "--cutoff-anchor",
    "--snapshot-in",
    "--offset",
    "--limit",
    "--json",
)

# Current aliases and unresolved overlap always require an independent analyst.
contains("skills/varde-learn/references/diagnose.md",
    "overlap` is `current` or `unknown`",
    "explicit `--session` IDs and `--path` inputs do not bypass this rule",
    "one independent analyst",
    "native agent delegation",
    "Do not include the coordinator's hypotheses, conclusions, or preferred fix in the handoff",
    "delegation is unavailable, stop and report that blocker",
    "Do not replace the analyst with self-analysis",
    "mandatory seven-agent pass",
    "separate grading judge",
    "Unknown overlap does not prove the target is past",
    "An individual event can still be eligible for capture only when its source identity and historical context are revalidated",
)

contains("skills/varde-learn/references/diagnose.md",
    "OpenCode does not expose a verified current caller identity",
    "Copy the entire actual anchor object",
    "storage_sequence",
    "preserve `native_id` as JSON `null`",
)

# The two frozen-bundle consumers retain different overlap duties.
contains("skills/varde-learn/references/diagnose.md",
    "original coordinator overlap assessment",
    "a new coordinator",
    "recheck trusted current identity against the frozen target and family",
    "The analyst pages the supplied bundle",
    "must not run its own `--current` intake",
    "must preserve the bundle's saved overlap result",
    "A snapshot digest is an integrity check, not source authenticity",
)

# Report quality, persistence ordering, and capture outcomes are observable.
contains("skills/varde-learn/references/diagnose.md",
    "## Complaint or triage question",
    "## Coverage and limits",
    "## Observations",
    "## Hypotheses",
    "confidence",
    "alternatives",
    "## Bounded recommendations",
    "## Capture results",
    "## Uncaptured findings",
    "Save report.md before capture",
    "record each `created` or `already-recorded` result",
    "refresh the final report summary",
    "reports stay in the working store until explicitly removed",
)

# The example input spelling must match the strict Rust request parser.
contains("skills/varde-learn/references/diagnose.md",
    '"snapshot_path"',
    '"snapshot_digest"',
    '"session_id"',
    '"anchor"',
    '"incident_kind"',
    '"item"',
    '"evidence"',
    '"failed-tool"',
    '"repeated-work"',
    '"workflow-deviation"',
    '"existing"',
    '"new"',
    '"native_id"',
    '"already-recorded"',
    '"occurrence_id"',
)
contains("skills/varde-learn/references/diagnose.md",
    "64 KiB",
    "8 KiB",
    "2 MiB",
    "16 MiB per source",
    "32 MiB per family",
    "256 KiB per record",
    "10,000 records",
    "1,000 records per page",
    "32 linked children plus the selected root (up to 33 sessions)",
    "5,000 discovered metadata entries",
    "rewritten, inherited, or otherwise uncertain anchors",
    "approved fallback is an independently revalidated, append-stable JSONL line position and record digest",
)

# Source contracts: keep structural claims tied to the public parser/types.
contains("clis/learn/crates/varde-learn/src/cli.rs",
    "Inspect one local session or page a frozen evidence bundle",
    "Record one verified historical incident from a frozen evidence bundle",
    "snapshot_in",
    "snapshot_out",
    "cutoff_anchor",
    "pub struct DiagnoseCaptureArgs",
    "pub file: PathBuf",
)
contains("clis/learn/crates/varde-learn-core/src/diagnose/mod.rs",
    "pub const MAX_SOURCE_BYTES: usize = 16 * 1024 * 1024",
    "pub const MAX_FAMILY_SOURCE_BYTES: usize = 32 * 1024 * 1024",
    "pub const MAX_RECORD_BYTES: usize = 256 * 1024",
    "pub const MAX_RECORDS: usize = 10_000",
    "pub const MAX_PAGE_LIMIT: usize = 1_000",
    "pub const MAX_FAMILY: usize = 32",
    "pub const MAX_DISCOVERY_FILES: usize = 5_000",
    "pub const MAX_SNAPSHOT_BYTES: usize = 2 * 1024 * 1024",
    "#[serde(deny_unknown_fields)] struct CaptureFile",
    "MAX_CAPTURE_BYTES: usize = 64 * 1024",
    "8 * 1024",
    "CurrentOverlap::Unknown",
)
contains("clis/learn/crates/varde-learn-core/src/store.rs",
    "const SCHEMA_VERSION: i64 = 3",
    "const SCHEMA_V3: &str",
    "identity_version INTEGER NOT NULL",
    "record_historical_occurrence",
    "find_historical_witness",
)
contains("clis/learn/crates/varde-learn-core/src/import.rs",
    "fn optional_provenance",
    "validate_provenance",
)
contains("clis/learn/crates/varde-learn/src/friction.rs",
    "varde-friction-item",
    "fn render_incident_provenance",
)

# Module docs must keep diagnosis discoverable and preserve the old friction routes.
contains("clis/learn/README.md",
    "`diagnose inspect` reads bounded local Codex, Claude, or OpenCode session",
    "without starting another harness client or opening the friction",
    "`diagnose capture` records a reviewed event in that store.",
    "32 linked children plus the",
    "selected root (up to 33 sessions)",
    "varde-learn diagnose inspect",
    "varde-learn diagnose capture",
    "varde-friction-item",
    "schema 3",
    "--harness opencode --session <SESSION_ID>",
    "unavailable result for `--current`",
)
contains("clis/learn/AGENTS.md",
    "diagnose inspect",
    "diagnose capture",
    "current or unknown session overlap",
    "friction evidence",
)
contains("memory-bank/knowledge/decision/varde-learn-module.md",
    "diagnose",
    "independent analyst",
    "provenance",
    "schema 3",
)
if "varde-diagnose" in skill or "varde-diagnose" in reference:
    raise SystemExit("FAIL: diagnosis routes through the retired standalone skill")
checks += 1

print(f"Session diagnosis documentation checks passed ({checks} structural assertions).")
PY
