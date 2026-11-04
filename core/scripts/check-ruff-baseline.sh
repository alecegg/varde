#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
baseline_file="$script_dir/ruff-baseline.json"
ruff_json="$(uv run --locked --all-packages ruff check \
    --select E,TRY,S \
    --ignore TRY003 \
    --output-format=json \
    --exit-zero)"

python3 -c '
import json
import re
import sys
from collections import Counter

baseline_path = sys.argv[1]
diagnostics = json.load(sys.stdin)
with open(baseline_path, encoding="utf-8") as baseline_file:
    baseline = json.load(baseline_file)
counts = Counter()
rule_code = re.compile(r"^(E|TRY|S)\d")
for diagnostic in diagnostics:
    match = rule_code.match(diagnostic["code"])
    if match:
        counts[match.group(1)] += 1

failed = False
for prefix, limit in baseline.items():
    count = counts[prefix]
    if count > limit:
        print(f"{prefix}: {count} violations exceeds baseline {limit}", file=sys.stderr)
        failed = True
    elif count < limit:
        print(f"{prefix}: {count} violations (baseline {limit}); lower the baseline")
    else:
        print(f"{prefix}: {count} violations (baseline {limit})")

sys.exit(1 if failed else 0)
' "$baseline_file" <<<"$ruff_json"
