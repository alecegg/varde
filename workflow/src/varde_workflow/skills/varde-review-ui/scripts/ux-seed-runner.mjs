#!/usr/bin/env node
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { spawn } from 'node:child_process';
import net from 'node:net';
import { createHash } from 'node:crypto';

async function makeScratchWritable(directory) {
  for (const entry of await fs.readdir(directory, { withFileTypes: true })) {
    const target = path.join(directory, entry.name);
    if (entry.isDirectory()) await makeScratchWritable(target);
    else await fs.chmod(target, (await fs.stat(target)).mode | 0o600);
  }
  await fs.chmod(directory, (await fs.stat(directory)).mode | 0o700);
}

const seedRoleConfig = `version = 1

[types.light]
harness = "codex-app-server"
model = "gpt-6-luna"
reasoning_effort = "medium"

[[types.light.fallback]]
harness = "opencode-http"
model = "opencode-go/deepseek-v4.1-flash"
reasoning_effort = "high"

[types.review]
harness = "codex-app-server"
model = "gpt-6-astra"
reasoning_effort = "high"

[[types.review.fallback]]
harness = "opencode-http"
model = "opencode-go/deepseek-v4.1-flash"
reasoning_effort = "high"

[roles.builder]
type = "light"

[roles.planner]
type = "light"

[roles.reviewer]
type = "review"

[policy]
never_models = ["*-sol"]
allow_fallback_only_on = ["provider_limit"]
create_paseo_projects = false
`;

export function scratchRunnerEnvironment(environment, working, scratch, configDir) {
  const env = {
    ...environment,
    VARDE_WORKING_DIR: working,
    VARDE_RUNNER_STATE_DIR: path.join(scratch, 'state'),
    VARDE_RUNNER_CONFIG_DIR: configDir,
    VARDE_PLANS_BACKEND: 'files',
  };
  for (const key of Object.keys(env)) {
    if (key.startsWith('PASEO_')) delete env[key];
  }
  env.PASEO_URL = 'ws://127.0.0.1:1/ws';
  return env;
}

export async function seedScratchData(working, configDir) {
  const planId = 'ux-review-seed-agent';
  const planDir = path.join(working, 'plans', planId);
  const notesDir = path.join(working, 'plans', 'ux-review-seed');
  const notesPath = path.join(notesDir, 'decision.json');
  const messagesPath = path.join(working, '.cache', 'inbox', 'messages.jsonl');
  const address = planId;
  const harness = 'codex-app-server';
  const sessionId = `${planId}-session`;
  const sessionKey = `${harness}-${createHash('sha256').update(sessionId).digest('hex')}`;
  const inboxDir = path.dirname(messagesPath);
  await fs.mkdir(planDir, { recursive: true });
  await fs.mkdir(notesDir, { recursive: true });
  await fs.mkdir(inboxDir, { recursive: true });
  await fs.mkdir(configDir, { recursive: true });

  const planText = `---
status: active
title: "UX review seed: answer a focused question"
type: plan
assigned_to: ${address}
owner: ${address}
group: ux-review
---

## Problem

The seeded scratch runner needs a review question that can be answered.

## Solution

Choose a focused area for the next review pass.
`;
  await fs.writeFile(path.join(planDir, 'plan.md'), planText);

  const decision = {
    type: 'question',
    title: 'Choose the review focus',
    asked: 'Which area should the UX review prioritize next?',
    why: 'The review can take one focused pass before the next release.',
    options: [
      { id: 'mobile', label: 'Mobile navigation' },
      { id: 'plans', label: 'Plan workflows' },
    ],
    recommendation: { id: 'mobile', label: 'Mobile navigation' },
    plan_id: planId,
  };
  await fs.writeFile(notesPath, `${JSON.stringify(decision, null, 2)}\n`);

  const timestamp = new Date().toISOString();
  const bindingsDir = path.join(inboxDir, 'bindings');
  const addressDir = path.join(inboxDir, 'addresses', address);
  await fs.mkdir(bindingsDir, { recursive: true });
  await fs.mkdir(addressDir, { recursive: true });
  await fs.writeFile(path.join(bindingsDir, `${sessionKey}.json`), `${JSON.stringify({
    address,
    harness,
    session_id: sessionId,
    bound_at: timestamp,
    last_seen: timestamp,
    token_id: 'ux-review-seed-token',
    cwd: '.',
    plan_id: planId,
  }, null, 2)}\n`);
  await fs.writeFile(path.join(addressDir, 'current'), `${JSON.stringify({ session_key: sessionKey, token_id: 'ux-review-seed-token' }, null, 2)}\n`);

  const messages = await fs.readFile(messagesPath, 'utf8').catch((error) => {
    if (error.code === 'ENOENT') return '';
    throw error;
  });
  const seededMessageId = 'ux-review-seed-needs-001';
  if (!messages.split(/\r?\n/).some((line) => line.includes(`"id":"${seededMessageId}"`))) {
    const message = {
      ts: new Date().toISOString(),
      from: address,
      to: 'main',
      kind: 'needs-user',
      text: decision.asked,
      notes: notesPath,
      id: seededMessageId,
    };
    await fs.appendFile(messagesPath, `${JSON.stringify(message)}\n`);
  }

  const roleConfigPath = path.join(configDir, 'runner.toml');
  if (!await fs.stat(roleConfigPath).then((stat) => stat.isFile()).catch(() => false)) {
    await fs.writeFile(roleConfigPath, seedRoleConfig);
  }
}

async function main() {
  const repo = path.resolve(process.argv[2] || process.cwd());
  const source = path.resolve(process.env.VARDE_UX_SOURCE_WORKING || path.join(os.homedir(), 'source/agent-memory/projects/varde-py/working'));
  if (!await fs.stat(source).then((s) => s.isDirectory()).catch(() => false)) throw new Error(`Working data source not found: ${source}`);
  const scratch = await fs.mkdtemp(path.join(os.tmpdir(), 'varde-ux-runner-'));
  const working = path.join(scratch, 'working');
  await fs.cp(source, working, { recursive: true, dereference: true, filter: (src) => !src.includes('/.cache/') });
  await makeScratchWritable(working);
  for (const rel of ['plans', 'queue', 'roles']) await fs.mkdir(path.join(working, rel), { recursive: true });
  const server = net.createServer();
  const port = await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => { const { port: selected } = server.address(); server.close(() => resolve(selected)); });
  });
  if (port === 8765) throw new Error('Refusing reserved live runner port 8765');
  const configDir = path.join(scratch, 'config');
  const env = scratchRunnerEnvironment(process.env, working, scratch, configDir);
  await seedScratchData(working, configDir);
  const child = spawn('uv', ['run', '--project', path.join(repo, 'runner'), 'varde-runner', 'serve', '--host', '127.0.0.1', '--port', String(port)], { cwd: repo, env, detached: true, stdio: 'ignore' });
  child.unref();
  const metadata = { pid: child.pid, port, url: `http://127.0.0.1:${port}`, scratch, working };
  await fs.writeFile(path.join(scratch, 'runner.json'), JSON.stringify(metadata, null, 2));
  let ready = false;
  for (let attempt = 0; attempt < 60; attempt += 1) {
    try {
      const response = await fetch(metadata.url);
      if (response.status === 200) { ready = true; break; }
      if (response.status === 503 && (await response.text()).includes('Dashboard UI not built')) {
        throw new Error('Runner UI is not built. Run npm ci --prefix runner/ui && npm run build --prefix runner/ui first.');
      }
    } catch (error) {
      if (error.message.includes('Runner UI is not built')) throw error;
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  if (!ready) throw new Error(`Scratch runner did not become ready at ${metadata.url}; inspect ${path.join(scratch, 'runner.json')}`);
  console.log(`URL: ${metadata.url}`);
  console.log(`Scratch copy: ${working}`);
  console.log(`Teardown: kill -TERM -- -${child.pid}; rm -rf '${scratch.replaceAll("'", "'\\''")}'`);
}

if (process.argv[1] && path.resolve(process.argv[1]) === new URL(import.meta.url).pathname) await main();
