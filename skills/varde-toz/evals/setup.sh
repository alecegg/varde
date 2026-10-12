#!/usr/bin/env bash
set -euo pipefail

mkdir -p fixtures
cat > fixtures/captured-status.txt <<'EOF'
## git status --short
 M src/main.rs
?? notes.txt
EOF
cat > fixtures/captured-find.txt <<'EOF'
preview: src/main.rs, src/lib.rs
capture handle: toz-handle-no-rerun-03
state: captured, output clipped
EOF
cat > fixtures/batch-inputs.json <<'EOF'
{"commands":["git rev-parse --show-toplevel","git branch --show-current"]}
EOF
