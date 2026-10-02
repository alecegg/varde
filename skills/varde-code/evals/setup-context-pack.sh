#!/usr/bin/env bash
set -euo pipefail

: "${EVAL_SANDBOX_DIR:?EVAL_SANDBOX_DIR is required}"
sandbox_root="$(cd "$EVAL_SANDBOX_DIR" && pwd -P)"
repo_root="$sandbox_root/project"
result_file="$sandbox_root/context-result.json"
mkdir -p "$repo_root/src"

cat > "$repo_root/src/auth.rs" <<'EOF'
pub fn refresh_session() {
    record_refresh();
}

fn record_refresh() {}
EOF

for number in {1..25}; do
    suffix="$(printf '%02d' "$number")"
    cat > "$repo_root/src/auth_refresh_helper_${suffix}.rs" <<EOF
use crate::auth::refresh_session;

pub fn auth_refresh_helper_${suffix}() {
    refresh_session();
}
EOF
done

{
    printf '%s\n' 'pub mod auth;'
    for number in {1..25}; do
        suffix="$(printf '%02d' "$number")"
        printf 'pub mod auth_refresh_helper_%s;\n' "$suffix"
    done
} > "$repo_root/src/lib.rs"

varde-code build --repo-root "$repo_root" >/dev/null
varde-code context_pack --json \
    "{\"repoRoot\":\"$repo_root\",\"query\":\"auth refresh\",\"resultsLimit\":2}" \
    > "$result_file"

python3 - "$result_file" <<'PY'
import json
import sys
from pathlib import Path

envelope = json.loads(Path(sys.argv[1]).read_text())
meta = envelope.get("meta", {})
toz = meta.get("toz", {})
assert envelope.get("ok") is True, "context_pack did not succeed"
assert meta.get("truncated") is True, "context_pack result was not truncated"
assert isinstance(toz.get("handle"), str) and toz["handle"], "missing meta.toz.handle"
assert int(toz.get("items", 0)) > 20, "fixture did not produce rows beyond offset 20"
assert len(envelope.get("data", {}).get("files", [])) == 2, "resultsLimit was not applied"
PY

handle="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["meta"]["toz"]["handle"])' "$result_file")"
varde-toz query --handle "$handle" --lines 21:21 >/dev/null
