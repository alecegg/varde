#!/usr/bin/env bash
set -euo pipefail

usage() {
  printf 'Usage: %s ROLE WORKSPACE PROMPT_FILE [PORT]\n' "$0" >&2
  exit 2
}

[[ $# -ge 3 && $# -le 4 ]] || usage
role="$1"
workspace="$2"
prompt_file="$3"
port="${4:-8765}"
[[ -s "$prompt_file" ]] || { printf 'Prompt file is missing or empty.\n' >&2; exit 2; }
command -v varde-runner >/dev/null || { printf 'Install varde-runner first.\n' >&2; exit 2; }
command -v python3 >/dev/null || { printf 'Python 3 is required for the usage meter.\n' >&2; exit 2; }

printf '%s\n' "This starts one real Pi Durable run. Reported-cost stop threshold: \$1.00."
printf '%s\n' "A provider-side spending limit at or below \$1.00 is also required."
read -r -p 'Type RUN to continue: ' confirmation
[[ "$confirmation" == RUN ]] || { printf 'Cancelled.\n'; exit 1; }

launch="$(varde-runner agent launch --role "$role" --workspace "$workspace" \
  --harness pi-durable --prompt - --port "$port" < "$prompt_file")"
agent_id="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["id"])' "$launch")"
printf 'Launched agent %s\n' "$agent_id"

python3 - "$agent_id" "$port" <<'PY'
import json
import math
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

agent_id, port = sys.argv[1:]
base = f"http://127.0.0.1:{port}/api/agents"
cap = 1.0
deadline = time.monotonic() + 30 * 60
client = "pi-durable-smoke-meter"
query = urllib.parse.urlencode({"client": client, "role": "observer", "after": 0})
watch_url = f"{base}/{urllib.parse.quote(agent_id, safe='')}/watch?{query}"
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
spent = 0.0
event_name = ""
data_lines = []
seen_usage = False


def stop(reason):
    subprocess.run(
        ["varde-runner", "agent", "stop", agent_id, "--port", port], check=False
    )
    print(reason, file=sys.stderr)
    raise SystemExit(3)


def account(kind, payload):
    global spent, seen_usage
    if kind != "usage":
        return
    cost = payload.get("costUsd")
    if not isinstance(cost, (int, float)) or not math.isfinite(cost) or cost < 0:
        stop("Usage event has no valid cost; stopped without continuing unmetered.")
    spent += cost
    seen_usage = True
    print(f"Reported session cost: ${spent:.4f}", flush=True)
    if spent >= cap:
        stop("Reported usage reached the $1.00 smoke cap; the agent was stopped.")


def check_liveness():
    with opener.open(f"{base}", timeout=30) as response:
        agents = json.load(response)
    row = next((item for item in agents if item.get("agent_id") == agent_id), None)
    if row is None:
        stop("Agent disappeared before the smoke completed.")
    state = row.get("liveness")
    if state in {"closed", "idle"}:
        if not seen_usage:
            stop("Agent became idle without a usage event; spend could not be verified.")
        print(f"Agent is {state}; reported session cost: ${spent:.4f}")
        raise SystemExit(0)
    if state in {"error", "stalled"}:
        stop(f"Agent liveness is {state}; stopped the smoke run.")


try:
    with opener.open(watch_url, timeout=45) as response:
        for raw in response:
            if time.monotonic() >= deadline:
                stop("Smoke exceeded 30 minutes; stopped the agent.")
            line = raw.decode("utf-8").rstrip("\r\n")
            if line.startswith("event: "):
                event_name = line[7:]
            elif line.startswith("data: "):
                data_lines.append(line[6:])
            elif not line:
                if data_lines:
                    data = json.loads("\n".join(data_lines))
                    if event_name == "error":
                        stop(f"Runner watch failed: {data}")
                    if event_name == "snapshot":
                        if data.get("truncated"):
                            stop("Usage event history is truncated; stopped fail-closed.")
                        for item in data.get("events", []):
                            account(item.get("kind"), item.get("payload", {}))
                    elif event_name == "event":
                        account(data.get("kind"), data.get("payload", {}))
                    data_lines.clear()
                    event_name = ""
                check_liveness()
except (OSError, urllib.error.URLError, json.JSONDecodeError) as error:
    stop(f"Usage meter failed ({error}); stopped the smoke run.")
PY
