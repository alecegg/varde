# Pi Durable first run

Pi Durable is opt-in. Install Node.js 22.19 or newer and the runner with
`uv tool install ./runner`, then install the engine's pinned packages:

```sh
npm ci --ignore-scripts --prefix runner/node-host/engines/durable
```

## Configure DeepSeek

Pi's built-in provider id is `deepseek`; it reads `DEEPSEEK_API_KEY`. The
durable engine expects a provider-prefixed model id.

```toml
[pi_durable]
enabled = true
provider = "deepseek"
model = "deepseek/deepseek-flash"
key_env = "DEEPSEEK_API_KEY"
```

Configure the builder role:

- Add a type with `harness = "pi-durable"`.
- Give it the model, reasoning effort, and required fallback.
- Assign the type to a `workspace-write` builder role.
- Export the configured key variable in the runner's environment. Varde reads it
  by name and does not store it.

## First real run

1. Start `varde-runner serve` in the same environment that has the key.
2. Choose one small, real plan task and run the smoke script from the repository
   root:

```sh
runner/scripts/pi-durable-smoke.sh builder /path/to/worktree /path/to/prompt.txt
```

The script asks for `RUN` before launching with `varde-runner agent launch`.
It watches usage events and stops the agent when reported cost reaches USD 1.00.

- Provider usage arrives after a request, so one request can cross the threshold.
- Set the provider-side spending cap at or below USD 1.00 as the hard billing cap.
- The script stops if usage history is truncated or cannot be read.

When monitoring finishes, inspect the result and cost:

1. Find the session with `varde-runner agent list`.
2. Stop or archive it with `varde-runner agent stop <id>` or
   `varde-runner agent archive <id>`.
3. Record `Smoke: PASS` and reported spend in plan Progress after successful
   completion within the cap.

## Scratch runner smokes

The offline fake-provider path checks session persistence across a runner
restart, including replay and a followup prompt. Run it from the repository root:

```sh
uv run python runner/scripts/native_smoke.py --harness pi-durable --role builder --model openai/gpt-4o-mini --out /tmp/pi-durable-offline.json
```

For a real-provider scratch smoke, the env wrapper reads the DeepSeek API key
from Pi's `~/.pi/agent/auth.json`. It passes the key only to the temporary
runner's environment, not its config. The one run command starts an isolated
runner on port 18765 by default, asks for `RUN`, meters the first prompt, then
restarts the runner and meters a followup prompt in the restored session. The
combined reported-cost stop is USD 1.00. Follow these steps:

1. Check the auth entry:

   ```sh
   runner/scripts/pi-durable-smoke-env.sh --check
   ```

2. Set a provider-side spending cap at or below USD 1, then run one small task:

   ```sh
   runner/scripts/pi-durable-smoke-env.sh builder /path/to/scratch-worktree /path/to/prompt.txt
   ```

The script prompts for `RUN`, checks the restored event replay, and reports the
combined cost on completion. Use `--port PORT` to choose another scratch port;
port 8765 is refused because it belongs to the live runner. Scratch logs and
state are kept under the system temporary directory in a
`varde-pi-durable-smoke-*` folder for inspection. Set
`PI_DURABLE_AUTH_FILE` to check a different auth file.

Use a file-only prompt, such as: "Read calc.py, change the subtraction to
addition by editing the file, and reply with one line." Pi Durable's `read`, `ls`, `find`,
`grep`, `edit`, and `write` tools operate inside the workspace without an
approval request. A shell command that can change state, including running
tests or invoking git, requires user approval for a workspace-write builder.
The wrapper cannot answer that approval. It prints lifecycle, liveness, cost,
and seconds since the last event every 15 seconds; a pending approval is shown
with its one-line summary. It stops the agent after five minutes without new
events or usage and prints FAIL with reported cost. The offline tests use a
short injectable timeout to cover this path.
