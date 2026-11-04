// Scripted stand-in for @anthropic-ai/claude-agent-sdk used by the engine tests.
// Each user message makes one turn. Text commands:
//   "tool"   -> assistant text, a tool_use, its tool_result, then the result
//   "hang"   -> init only; the turn never produces a result
//   "fail"   -> the stream throws
//   "perm"   -> asks options.canUseTool("Bash") and reports the behavior
//   other    -> assistant echo then the result
// With options.spawnClaudeCodeProcess the fake spawns a real child (and a
// grandchild in the same group) like the SDK does; env.FAKE_STUBBORN makes
// the child ignore SIGTERM. close() sends SIGTERM through the spawned process.
export const calls = [];

export function reset() {
  calls.length = 0;
}

export const FAKE_HANDLE = "fake-sdk-session-1";

function resultMessage(subtype = "success") {
  return {
    type: "result",
    subtype,
    is_error: subtype !== "success",
    result: subtype === "success" ? "done" : null,
    total_cost_usd: 0.0123,
    usage: { input_tokens: 10, output_tokens: 5, cache_read_input_tokens: 2, cache_creation_input_tokens: 1 },
    modelUsage: {
      "fake-model": {
        inputTokens: 10,
        outputTokens: 5,
        cacheReadInputTokens: 2,
        cacheCreationInputTokens: 1,
        costUSD: 0.0123,
        contextWindow: 200000,
      },
    },
  };
}

export function query({ prompt, options }) {
  const call = { options, prompt, interrupted: 0, closed: false, sent: [], proc: null, grandchild: null };
  const abort = new AbortController();
  calls.push(call);
  let closed = false;
  let wake = null;
  const pending = [];
  const notify = () => {
    const waiting = wake;
    wake = null;
    waiting?.();
  };
  const push = (message) => {
    pending.push(message);
    notify();
  };
  const next = () =>
    new Promise((resolve) => {
      const check = () => {
        if (pending.length > 0) resolve({ value: pending.shift(), done: false });
        else if (closed) resolve({ value: undefined, done: true });
        else wake = check;
      };
      check();
    });

  (async () => {
    let started = false;
    for await (const input of prompt) {
      const text = input.message.content;
      call.sent.push(text);
      if (!started) {
        started = true;
        if (options.spawnClaudeCodeProcess) {
          spawnChild(call, options);
          // Like the real SDK, the stream fails when its child dies underneath it.
          call.proc.on("exit", () => {
            if (!closed) push({ type: "__throw__" });
          });
        }
        push({ type: "system", subtype: "init", session_id: options.resume ?? FAKE_HANDLE, cwd: options.cwd });
      }
      if (text === "hang") continue;
      if (text === "stuck") {
        call.ignoreInterrupt = true;
        continue;
      }
      if (text === "toolhang") {
        push({
          type: "assistant",
          message: { content: [{ type: "tool_use", id: "tu-hang", name: "Bash", input: {} }] },
        });
        continue;
      }
      if (text === "perm") {
        const decision = await options.canUseTool("Bash", { command: "rm" }, {
          signal: abort.signal,
          toolUseID: "tu-perm",
          title: "Run rm",
        });
        push({ type: "assistant", message: { content: [{ type: "text", text: `perm:${decision.behavior}` }] } });
        push(resultMessage());
        continue;
      }
      if (text === "fail") {
        push({ type: "__throw__" });
        continue;
      }
      push({ type: "assistant", message: { content: [{ type: "text", text: `echo: ${text}` }] } });
      if (text === "tool") {
        push({
          type: "assistant",
          message: { content: [{ type: "tool_use", id: "tu1", name: "Bash", input: { command: "ls" } }] },
        });
        push({ type: "user", message: { content: [{ type: "tool_result", tool_use_id: "tu1", content: "ok" }] } });
      }
      push(resultMessage());
    }
    closed = true;
    notify();
  })();

  return {
    async interrupt() {
      call.interrupted += 1;
      abort.abort();
      if (!call.ignoreInterrupt) push(resultMessage("error_during_execution"));
    },
    close() {
      call.closed = true;
      abort.abort();
      call.proc?.kill("SIGTERM");
      closed = true;
      notify();
    },
    [Symbol.asyncIterator]() {
      return {
        next: async () => {
          const item = await next();
          if (item.value?.type === "__throw__") throw new Error("fake stream failure");
          return item;
        },
      };
    },
  };
}

function spawnChild(call, options) {
  const stubborn = options.env?.FAKE_STUBBORN ? 'process.on("SIGTERM", () => {});' : "";
  const script =
    `${stubborn}const g = require("node:child_process").spawn("sleep", ["300"], {stdio: "ignore"});` +
    "console.log('GRANDCHILD ' + g.pid); setInterval(() => {}, 1000);";
  call.proc = options.spawnClaudeCodeProcess({
    command: process.execPath,
    args: ["-e", script],
    cwd: options.cwd,
    env: options.env ?? {},
    signal: new AbortController().signal,
  });
  call.proc.stdout.on("data", (chunk) => {
    const match = /GRANDCHILD (\d+)/.exec(String(chunk));
    if (match) call.grandchild = Number(match[1]);
  });
}
