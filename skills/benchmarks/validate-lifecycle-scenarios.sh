#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 <lifecycle-scenarios.json>" >&2
  exit 2
fi

catalog="$1"
if [[ ! -f "$catalog" ]]; then
  echo "lifecycle scenario catalog not found: $catalog" >&2
  exit 1
fi

if ! jq -e '
  def nonempty_string:
    type == "string" and test("\\S");
  def nonempty_strings:
    type == "array" and length > 0 and all(.[]; nonempty_string);
  def valid_token_capture:
    type == "object"
    and (.method | nonempty_string)
    and (.evidence_path | nonempty_string)
    and (.fields | nonempty_strings);

  type == "object"
  and .schema_version == 1
  and (.scenarios | type == "array" and length > 0)
  and all(.scenarios[];
    type == "object"
    and (.id | nonempty_string)
    and (.name | nonempty_string)
    and (.setup | nonempty_strings)
    and (.workflow_actions | nonempty_strings)
    and (.observable_assertions | nonempty_strings)
    and (.evidence_paths | nonempty_strings)
    and (.token_capture | valid_token_capture)
  )
  and (([.scenarios[].id] | length) == ([.scenarios[].id] | unique | length))
' "$catalog" >/dev/null 2>&1; then
  echo "invalid lifecycle scenario catalog: $catalog" >&2
  exit 1
fi

echo "lifecycle scenario catalog is valid: $catalog"
