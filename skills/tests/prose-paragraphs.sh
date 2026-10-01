#!/usr/bin/env bash
set -euo pipefail

# Runs the shipped length checker over every skill's SKILL.md and references.
# Only errors fail; see varde-agent-doc-authoring/references/criteria.md.

SKILLS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$SKILLS_DIR"
if [ "$#" -gt 0 ]; then
  exec python3 varde-agent-doc-authoring/scripts/check-length.py "$@"
fi
exec python3 varde-agent-doc-authoring/scripts/check-length.py varde-*/
