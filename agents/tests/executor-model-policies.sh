#!/usr/bin/env bash
set -euo pipefail

AGENTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

python3 - "$AGENTS_DIR" <<'PY'
import json
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
manifest = json.loads((root / "capabilities.json").read_text())
profiles = {profile["name"]: profile for profile in manifest["profiles"]}
assert set(profiles) == {"executor", "explore", "plan", "review"}

executor = profiles["executor"]
expected = {
    "claude": ("sonnet", None, False),
    "codex": ("gpt-5.6-luna", "xhigh", True),
    "opencode": ("deepseek/deepseek-v4-flash", None, False),
}
for harness, (model, effort, supports_effort) in expected.items():
    policy = executor["models"][harness]
    assert policy["model"] == model, (harness, policy)
    assert policy["reasoning_effort"] == effort, (harness, policy)
    assert policy["reasoning_effort_supported"] is supports_effort, (harness, policy)
    assert (effort is None) == (policy["reasoning_efforts"] == []), (harness, policy)

claude = (root / "executor/claude.md").read_text()
codex = (root / "executor/codex.toml").read_text()
opencode = (root / "executor/opencode.md").read_text()
assert 'model: "sonnet"' in claude
assert 'model = "gpt-5.6-luna"' in codex
assert 'model_reasoning_effort = "xhigh"' in codex
assert 'model: "deepseek/deepseek-v4-flash"' in opencode
assert all('reasoning_effort' not in text for text in (claude, opencode))
print("Executor model policies passed.")
PY
