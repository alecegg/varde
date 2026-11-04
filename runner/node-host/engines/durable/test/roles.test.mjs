import assert from "node:assert/strict";
import { mkdtemp, mkdir, readFile, symlink, writeFile, realpath } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { before, describe, it } from "node:test";
import { buildSessionTools, methods } from "../tools/index.mjs";
import { effectiveMode, resolveModelConfig, toolNamesFor } from "../roles.mjs";

let cwd;
let outside;
before(async () => {
  cwd = await realpath(await mkdtemp(join(tmpdir(), "roles-cwd-")));
  outside = await realpath(await mkdtemp(join(tmpdir(), "roles-out-")));
  await writeFile(join(cwd, "a.txt"), "alpha\nbeta\n");
  await mkdir(join(cwd, "sub"));
  await writeFile(join(cwd, "sub", "b.js"), "const beta = 1;\n");
  await writeFile(join(outside, "secret.txt"), "secret");
  await symlink(outside, join(cwd, "link-out"));
  await symlink(join(outside, "secret.txt"), join(cwd, "link-secret"));
});

const call = (tools, name, args, api = { conversationId: "c1", callId: "k1" }) =>
  tools.find((tool) => tool.name === name).execute(args, api, undefined);
const outputText = (result) => result.output[0].text;
const session = (role, mode, extra = {}) =>
  buildSessionTools({ cwd, role, mode, env: { VARDE_AGENT_ID: "agent-1", VARDE_HARNESS: "pi-durable" }, ...extra });

describe("roles: tool sets", () => {
  it("read-only roles have no write tools, whatever mode is asked", () => {
    for (const role of ["explorer", "reviewer"]) {
      for (const mode of ["read-only", "workspace-write"]) {
        assert.deepEqual(toolNamesFor(role, mode), ["read", "ls", "find", "grep", "bash"]);
        assert.equal(effectiveMode(role, mode), "read-only");
      }
    }
  });

  it("builder and planner get write tools only in workspace-write mode", () => {
    for (const role of ["builder", "planner"]) {
      assert.deepEqual(toolNamesFor(role, "workspace-write").slice(-2), ["edit", "write"]);
      assert.ok(!toolNamesFor(role, "read-only").includes("write"));
    }
  });

  it("rejects unknown roles and modes", () => {
    assert.throws(() => toolNamesFor("wizard", "read-only"), { code: "invalid_params" });
    assert.throws(() => toolNamesFor("builder", "full-access"), { code: "invalid_params" });
  });

  it("registrations carry the replay flags from replay.json", async () => {
    const tools = session("builder", "workspace-write");
    const flags = Object.fromEntries(tools.map((tool) => [tool.name, tool.replay]));
    assert.deepEqual(flags, { read: "safe", ls: "safe", find: "safe", grep: "safe", bash: "safe", edit: "unsafe", write: "unsafe" });
    const list = await methods["tools.list"]({ role: "reviewer", mode: "workspace-write" });
    assert.equal(list.mode, "read-only");
    assert.deepEqual(list.tools.map((tool) => tool.name), ["read", "ls", "find", "grep", "bash"]);
    const table = JSON.parse(await readFile(new URL("../replay.json", import.meta.url), "utf8"));
    assert.ok(table.tools.bash.gated.effect.includes("once"));
  });
});

describe("roles: read-only refusals", () => {
  it("a read-only session cannot write: no write tool, bash writes refused", async () => {
    const tools = session("reviewer", "read-only");
    assert.equal(tools.find((tool) => tool.name === "write"), undefined);
    assert.equal(tools.find((tool) => tool.name === "edit"), undefined);
    for (const command of ["echo hi > out.txt", "touch out.txt", "cat a.txt >> a.txt", "rm a.txt", "sed -i s/a/b/ a.txt", "tee out.txt", "find . -delete", "sort -o out.txt a.txt"]) {
      await assert.rejects(call(tools, "bash", { command }), /refused/, command);
    }
    await assert.rejects(readFile(join(cwd, "out.txt")), { code: "ENOENT" });
    assert.equal(await readFile(join(cwd, "a.txt"), "utf8"), "alpha\nbeta\n");
  });

  it("read-only bash never calls the approval gate", async () => {
    let called = 0;
    const tools = session("explorer", "read-only", { approvals: { gateAndEffect: async () => (called += 1) } });
    await assert.rejects(call(tools, "bash", { command: "touch x" }), /refused/);
    assert.equal(called, 0);
  });

  it("discovery commands and read tools work", async () => {
    const tools = session("reviewer", "read-only");
    assert.match(outputText(await call(tools, "bash", { command: "ls && cat a.txt | head -n 1" })), /alpha/);
    assert.equal(outputText(await call(tools, "read", { path: "a.txt", limit: 1 })), "alpha");
    assert.match(outputText(await call(tools, "ls", {})), /sub\//);
    assert.match(outputText(await call(tools, "find", { pattern: "*.js" })), /sub\/b\.js/);
    assert.match(outputText(await call(tools, "grep", { pattern: "beta" })), /a\.txt:2:beta/);
    assert.match(outputText(await call(tools, "bash", { command: "pwd" })), new RegExp(cwd));
  });
});

describe("roles: git cannot run repository-configured programs", () => {
  it("a textconv git diff is refused for read-only roles and never executes", async () => {
    const { execFileSync } = await import("node:child_process");
    const repo = await realpath(await mkdtemp(join(tmpdir(), "roles-git-")));
    const marker = join(repo, "marker");
    const git = (...args) => execFileSync("git", args, { cwd: repo, stdio: "ignore", env: { ...process.env, GIT_CONFIG_GLOBAL: "/dev/null", GIT_CONFIG_NOSYSTEM: "1" } });
    git("init", "-q");
    git("config", "user.email", "t@example.com");
    git("config", "user.name", "t");
    await writeFile(join(repo, "textconv.sh"), `#!/bin/sh\ntouch ${marker}\ncat "$1"\n`, { mode: 0o755 });
    git("config", "diff.evil.textconv", join(repo, "textconv.sh"));
    await writeFile(join(repo, ".gitattributes"), "*.txt diff=evil\n");
    await writeFile(join(repo, "a.txt"), "one\n");
    git("add", ".");
    git("commit", "-q", "-m", "init");
    await writeFile(join(repo, "a.txt"), "two\n");
    const tools = buildSessionTools({ cwd: repo, role: "reviewer", mode: "read-only", env: {} });
    for (const command of ["git diff", "git diff -- a.txt", "git log -p", "git show HEAD", "git status"]) {
      await assert.rejects(call(tools, "bash", { command }), /refused/, command);
    }
    await assert.rejects(readFile(marker), { code: "ENOENT" });
  });
});

describe("roles: path confinement", () => {
  it("refuses escapes in every file tool and in bash discovery", async () => {
    const tools = session("builder", "workspace-write");
    for (const [name, args] of [
      ["read", { path: "../x" }],
      ["read", { path: outside + "/secret.txt" }],
      ["read", { path: "link-secret" }],
      ["ls", { path: "link-out" }],
      ["find", { pattern: "*", path: "../" }],
      ["grep", { pattern: "x", path: "link-out" }],
      ["write", { path: "../escape.txt", content: "x" }],
      ["write", { path: "link-out/escape.txt", content: "x" }],
      ["edit", { path: "link-secret", oldText: "secret", newText: "x" }],
      ["bash", { command: "cat ../x" }],
      ["bash", { command: "cat /etc/hosts" }],
      ["bash", { command: "cat link-secret" }],
      ["bash", { command: "ls link-out" }],
      ["bash", { command: "cd .. && ls" }],
    ]) {
      await assert.rejects(call(tools, name, args), /refused/, `${name} ${JSON.stringify(args)}`);
    }
    await assert.rejects(readFile(join(outside, "escape.txt")), { code: "ENOENT" });
    assert.equal(await readFile(join(outside, "secret.txt"), "utf8"), "secret");
  });

  it("workspace-write writes and edits inside cwd", async () => {
    const tools = session("builder", "workspace-write");
    assert.match(outputText(await call(tools, "write", { path: "sub/new.txt", content: "one two" })), /wrote/);
    await call(tools, "edit", { path: "sub/new.txt", oldText: "two", newText: "three" });
    assert.equal(await readFile(join(cwd, "sub/new.txt"), "utf8"), "one three");
    await assert.rejects(call(tools, "edit", { path: "sub/new.txt", oldText: "nope", newText: "x" }), /exactly once/);
  });
});

describe("roles: approval-gated bash", () => {
  const gate = (decision, log = []) => ({
    gateAndEffect: async (request, effect) => {
      log.push(request);
      if (decision !== "approve") return { status: decision };
      return { status: "executed", value: await effect() };
    },
  });

  it("builder non-discovery commands wait on the gate and run once, in cwd, with a minimal env", async () => {
    process.env.PI_TEST_API_KEY = "must-not-leak";
    try {
      const log = [];
      const tools = session("builder", "workspace-write", { approvals: gate("approve", log) });
      const result = await call(tools, "bash", { command: "printenv VARDE_AGENT_ID; printenv VARDE_HARNESS; printenv PI_TEST_API_KEY; pwd; echo $TMPDIR" });
      const text = outputText(result);
      assert.match(text, /^agent-1\npi-durable\n/);
      assert.ok(!text.includes("must-not-leak"));
      assert.match(text, new RegExp(cwd));
      assert.match(text, /varde-pi-/);
      assert.equal(log.length, 1);
      assert.deepEqual(log[0], { key: "c1:k1", tool: "bash", summary: log[0].summary, input: { command: log[0].input.command } });
      assert.match(log[0].summary, /^Run: /);
    } finally {
      delete process.env.PI_TEST_API_KEY;
    }
  });

  it("deny and expired block the command, so its effect never runs", async () => {
    for (const status of ["denied", "expired"]) {
      const tools = session("builder", "workspace-write", { approvals: gate(status) });
      await assert.rejects(call(tools, "bash", { command: "touch gated.txt" }), new RegExp(status));
    }
    await assert.rejects(readFile(join(cwd, "gated.txt")), { code: "ENOENT" });
  });

  it("fails closed without an approval bridge, and planner may not use it", async () => {
    await assert.rejects(call(session("builder", "workspace-write"), "bash", { command: "touch x" }), /approval bridge/);
    const planner = session("planner", "workspace-write", { approvals: gate("approve") });
    await assert.rejects(call(planner, "bash", { command: "touch x" }), /refused/);
  });

  it("times out a long command and kills its group", async () => {
    const tools = session("builder", "workspace-write", { approvals: gate("approve") });
    const result = await call(tools, "bash", { command: "sleep 30", timeout: 0.2 });
    assert.match(outputText(result), /timed out/);
  });
});

describe("roles: model config", () => {
  it("splits a provider-prefixed model and reports key presence by name only", () => {
    const env = { MY_KEY: "super-secret-value" };
    const config = resolveModelConfig({ provider: "deepseek", model: "deepseek/deepseek-flash", key_env: "MY_KEY" }, env);
    assert.deepEqual(config, { provider: "deepseek", modelId: "deepseek-flash", keyEnv: "MY_KEY", keyPresent: true });
    assert.ok(!JSON.stringify(config).includes("super-secret-value"));
    assert.equal(resolveModelConfig({ provider: "p", model: "m", key_env: "ABSENT" }, env).keyPresent, false);
    assert.equal(resolveModelConfig({ provider: "p", model: "m" }, env).keyEnv, null);
    assert.throws(() => resolveModelConfig({ provider: "a", model: "b/c" }, env), /disagree/);
    assert.throws(() => resolveModelConfig({ model: "bare" }, env), /provider/);
  });
});
