#!/usr/bin/env bash
set -euo pipefail

: "${EVAL_SANDBOX_DIR:?EVAL_SANDBOX_DIR is required}"
cd "$EVAL_SANDBOX_DIR"

git init -q -b main
git config user.email "eval@example.invalid"
git config user.name "Varde Eval"

mkdir -p src
cat > README.md <<'EOF'
# Test quality fixture

The feature branch adds a function and a test for review.
EOF

git add README.md
git commit -q -m "Create test quality fixture"

git switch -q -c feature/test-quality-findings
cat > src/number.mjs <<'EOF'
export function double(value) {
  return value * 2;
}

export class NumberFormatter {}
EOF
cat > src/number.test.mjs <<'EOF'
import assert from "node:assert/strict";
import test from "node:test";
import { double } from "./number.mjs";

test("double returns the expected value", () => {
  assert.equal(double(3), double(3));
});
EOF

cat > src/number-design.test.mjs <<'EOF'
import assert from "node:assert/strict";
import test from "node:test";
import { NumberFormatter } from "./number.mjs";

test("number formatter is a class", () => {
  assert.equal(typeof NumberFormatter, "function");
});
EOF

git add src/number.mjs src/number.test.mjs src/number-design.test.mjs
git commit -q -m "Add test-quality fixture cases"
