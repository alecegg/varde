#!/usr/bin/env bash
# Time `varde run capture --hook --harness claude-code` over fixed PostToolUse payloads.
# Usage: toz-hook.sh [--binary <path>] [--binary-args "<prefix>"] [--command "<args>"] <output.json>
# --binary-args replaces the default `run` prefix for other command layouts.
# --command replaces the whole timed argument list (for example
# "hook post-tool-use --harness claude"); the default stays `<prefix> capture --hook --harness claude-code`.
# Writes {median_ms, runs, varde_toz_version, head, ...}; median_ms is the ~64 KB payload median.
set -euo pipefail

binary=varde
prefix=(run)
command_args=()
while [[ "${1:-}" == --binary || "${1:-}" == --binary-args || "${1:-}" == --command ]]; do
  case "$1" in
    --binary) binary="${2:?--binary needs a path}" ;;
    --binary-args) read -r -a prefix <<<"${2?--binary-args needs a value}" ;;
    --command) read -r -a command_args <<<"${2:?--command needs arguments}" ;;
  esac
  shift 2
done
out="${1:?usage: toz-hook.sh [--binary <path>] [--binary-args \"<prefix>\"] [--command \"<args>\"] <output.json>}"
runs=${RUNS:-30}

work=$(mktemp -d "${TMPDIR:-/tmp}/toz-hook.XXXXXX")
trap 'rm -rf "$work"' EXIT
export VARDE_TOZ_CONFIG_DIR="$work/config"
unset TOZ_CONFIG_DIR
mkdir -p "$VARDE_TOZ_CONFIG_DIR"

# Fixed Bash PostToolUse payloads of increasing output size.
python3 - "$work" <<'PY'
import json, sys
work = sys.argv[1]
for name, size in (("small", 200), ("64kb", 64 * 1024), ("1mb", 1024 * 1024)):
    lines, n = [], 0
    while n < size:
        line = f"line {len(lines):06d} build output ok warning: unused variable x"
        lines.append(line)
        n += len(line) + 1
    payload = {
        "hook_event_name": "PostToolUse",
        "session_id": "bench",
        "tool_name": "Bash",
        "tool_input": {"command": "make"},
        "tool_response": {"stdout": "\n".join(lines)[:size], "stderr": "", "interrupted": False},
    }
    with open(f"{work}/{name}.json", "w") as f:
        json.dump(payload, f)
PY

if ((${#command_args[@]})); then
  cmd=("$binary" "${command_args[@]}")
else
  cmd=("$binary" ${prefix[@]+"${prefix[@]}"} capture --hook --harness claude-code)
fi
for name in small 64kb 1mb; do
  if command -v hyperfine >/dev/null 2>&1; then
    hyperfine --runs "$runs" --warmup 3 --input "$work/$name.json" --export-json "$work/$name.times.json" \
      --command-name "$name" "${cmd[*]}" >/dev/null
  else
    python3 - "$work/$name.json" "$work/$name.times.json" "$runs" "${cmd[@]}" <<'PY'
import json, subprocess, sys, time
payload, dest, runs, argv = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4:]
data = open(payload, "rb").read()
def once():
    t = time.perf_counter()
    subprocess.run(argv, input=data, stdout=subprocess.DEVNULL, check=True)
    return time.perf_counter() - t
for _ in range(3):
    once()
json.dump({"results": [{"times": [once() for _ in range(runs)]}]}, open(dest, "w"))
PY
  fi
done

python3 - "$work" "$out" "$runs" "$binary" "$(git rev-parse HEAD)" <<'PY'
import json, statistics, subprocess, sys
work, out, runs, binary, head = sys.argv[1:]
med = {}
for name in ("small", "64kb", "1mb"):
    times = json.load(open(f"{work}/{name}.times.json"))["results"][0]["times"]
    med[name] = round(statistics.median(times) * 1000, 2)
version = subprocess.run([binary, "--version"], capture_output=True, text=True, check=True).stdout.strip()
result = {
    "median_ms": med["64kb"],
    "runs": int(runs),
    "varde_toz_version": version,
    "head": head,
    "median_ms_by_payload": med,
}
with open(out, "w") as f:
    json.dump(result, f, indent=2)
    f.write("\n")
print(json.dumps(result))
PY
