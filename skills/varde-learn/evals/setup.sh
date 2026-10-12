#!/usr/bin/env bash
set -euo pipefail

mkdir -p fixtures
cat > fixtures/friction-log.jsonl <<'EOF'
{"v":1,"id":"fixture-item-01","ts":"2026-01-01T00:00:00.000Z","kind":"item_added","body":{"title":"Missing fixture path","source":"varde-learn","repo_root":"/fixture/repo"}}
{"v":1,"id":"fixture-occurrence-01","ts":"2026-01-01T00:00:01.000Z","kind":"occurrence_appended","body":{"item":"fixture-item-01","at":"2026-01-01T00:00:01.000Z","cwd":"/fixture/repo","repo_root":"/fixture/repo","evidence":"The focused check failed because the fixture path was missing; one rerun was needed.","cost":"one rerun"}}
EOF
cat > fixtures/friction-list.json <<'EOF'
{"items":[{"id":"fixture-item-01","title":"Missing fixture path","status":"open","occurrences":[{"evidence":"The focused check failed because the fixture path was missing; one rerun was needed."}]}],"meta":{"truncated":false}}
EOF
