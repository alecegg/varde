#!/usr/bin/env bash
set -euo pipefail

git init -q
git config user.email eval@example.invalid
git config user.name 'Varde Eval'
case "$EVAL_ID" in
  5)
    mkdir -p code-cli
    printf '# Repository\n' > README.md
    printf '# Code CLI\n' > code-cli/README.md
    printf '# Changelog\n\n## Unreleased\n\n- Existing entry.\n' > code-cli/CHANGELOG.md
    ;;
  6|7)
    mkdir -p src/billing src/shared memory-bank/knowledge/specs
    printf 'pub fn charge() {}\n' > src/billing/charge.rs
    printf 'pub fn refund() {}\n' > src/billing/refunds.rs
    printf 'billing = "billing-service"\n' > deployment.toml
    source_hash="$(git hash-object --no-filters src/billing/charge.rs)"
    aggregate="$(printf 'src/billing/charge.rs%s' "$source_hash" | git hash-object --stdin)"
    cat > memory-bank/knowledge/specs/billing.md <<SPEC
---
type: spec
id: specs/billing
domain: billing
source_roots:
  - src/billing
covered_paths:
  - src/billing/charge.rs
source_hash: $aggregate
sources:
  - path: src/billing/charge.rs
    hash: $source_hash
---

<!-- varde-spec:generated:start -->
## Summary

Billing charges.
<!-- varde-spec:generated:end -->

## Notes
SPEC
    architecture_hash="$(git hash-object --no-filters deployment.toml)"
    architecture_aggregate="$(printf 'deployment.toml%s' "$architecture_hash" | git hash-object --stdin)"
    cat > memory-bank/knowledge/specs/architecture.md <<SPEC
---
type: spec
id: specs/architecture
domain: architecture
source_roots:
  - deployment.toml
covered_paths:
  - deployment.toml
source_hash: $architecture_aggregate
sources:
  - path: deployment.toml
    hash: $architecture_hash
---

<!-- varde-spec:generated:start -->
## Overview

Billing service deployment.
<!-- varde-spec:generated:end -->

## Notes
SPEC
    printf 'source_commit: none\n' > memory-bank/knowledge/specs/index.md
    if [[ "$EVAL_ID" == 7 ]]; then
      printf 'billing = "new-billing-service"\n' > deployment.toml
      printf 'pub fn tax() {}\n' > src/shared/tax.rs
      printf 'pub fn common() {}\n' > src/billing/common.rs
      cp memory-bank/knowledge/specs/billing.md memory-bank/knowledge/specs/shared.md
      sed -i.bak 's/specs\/billing/specs\/shared/g; s/domain: billing/domain: shared/' memory-bank/knowledge/specs/shared.md
      rm memory-bank/knowledge/specs/shared.md.bak
    fi
    ;;
  8|9)
    mkdir -p docs src/config
    printf 'export const DEFAULT_TIMEOUT = 30;\n' > src/config/schema.ts
    printf '# Configuration\n\nThe default timeout is 10.\n' > docs/config-reference.md
    ;;
  *) exit 2 ;;
esac
git add .
git commit -qm 'Seed documentation evaluation'
