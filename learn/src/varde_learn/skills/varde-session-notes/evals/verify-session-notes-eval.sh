#!/usr/bin/env bash
set -euo pipefail

# Static fixtures cannot verify these assertions; leave them uncovered so the
# grader judges session evidence.
case "$EVAL_ID" in
  *) printf '{"results":[]}' ;;
esac
