import test from 'node:test';
import assert from 'node:assert/strict';
import { archiveAgent, attentionOrder, getAgentCapabilities, interruptAgent, launchAgent, listAgents, openAgentWriter, promptAgent, respondAgent, resumeAgent, stopAgent } from './agentsApi.ts';

const agent = (agent_id, lifecycle, pending_requests = [], idle_status = null) => ({ agent_id, harness: 'test', role: 'worker', workspace: 'ws', lifecycle, idle_status, capabilities: {}, pending_requests });

test('agents sort by attention with archived agents last and stable ties', () => {
  const rows = [agent('archived', 'archived'), agent('done', 'completed'), agent('idle', 'idle'), agent('running', 'running'), agent('limited', 'rate_limited'), agent('failed', 'failed'), agent('pending', 'idle', [{ request_id: 'r', kind: 'approval', summary: 'Allow?' }])];
  assert.deepEqual(attentionOrder(rows).map(({ agent_id }) => agent_id), ['pending', 'limited', 'failed', 'running', 'idle', 'done', 'archived']);
});

test('agents API sends typed request shapes and reuses writer client', async (t) => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  const originalEventSource = globalThis.EventSource;
  class FakeEventSource { constructor(url) { this.url = url; this.closed = false; calls.push(['watch', url, this]); queueMicrotask(() => this.onopen?.()); } close() { this.closed = true; } }
  globalThis.EventSource = FakeEventSource;
  globalThis.fetch = async (url, init = {}) => {
    calls.push([url, init]);
    return { ok: true, json: async () => {
      if (url === '/api/agents' && init.method === 'POST') return { agent_id: 'new-agent' };
      if (url === '/api/agents') return [];
      if (url === '/api/agents/capabilities') return { codex: { prompts: true }, disabled: ['claude'] };
      return {};
    } };
  };
  t.after(() => { globalThis.fetch = originalFetch; globalThis.EventSource = originalEventSource; });

  await listAgents();
  const launched = await launchAgent({ harness: 'codex', workspace: 'ws', role: 'worker', prompt: 'start', address: { slot: 'slot-1', plan: 'plan-1' } });
  const capabilities = await getAgentCapabilities();
  let registeredClose;
  const writer = await openAgentWriter('agent/one', (close) => { registeredClose = close; });
  await promptAgent('agent/one', writer, 'hello');
  await interruptAgent('agent/one', writer);
  await respondAgent('agent/one', writer, 'req-1', 'allow');
  await resumeAgent('agent/one', writer);
  await stopAgent('agent/one', writer);
  await archiveAgent('agent/one', writer);
  writer.close();
  assert.equal(typeof registeredClose, 'function');

  assert.equal(calls[0][0], '/api/agents');
  assert.equal(calls[1][0], '/api/agents');
  assert.equal(calls[1][1].method, 'POST');
  assert.equal(calls[1][1].headers['Content-Type'], 'application/json');
  assert.deepEqual(launched, { agent_id: 'new-agent' });
  assert.deepEqual(JSON.parse(calls[1][1].body), { harness: 'codex', workspace: 'ws', role: 'worker', prompt: 'start', address: { slot: 'slot-1', plan: 'plan-1' } });
  assert.equal(calls[2][0], '/api/agents/capabilities');
  assert.deepEqual(capabilities, { harnesses: { codex: { prompts: true } }, disabled: ['claude'] });
  const [watchUrl, watch] = calls[3].slice(1);
  const query = new URL(watchUrl, 'http://localhost').searchParams;
  assert.equal(new URL(watchUrl, 'http://localhost').pathname, '/api/agents/agent%2Fone/watch');
  assert.equal(query.get('role'), 'writer');
  assert.equal(query.get('client'), writer.client);
  assert.equal(watch.closed, true);
  const writes = calls.slice(4);
  assert.deepEqual(writes.map(([url]) => new URL(url, 'http://localhost').pathname.split('/').at(-1)), ['prompt', 'interrupt', 'respond', 'resume', 'stop', 'archive']);
  assert.deepEqual(JSON.parse(writes[0][1].body), { text: 'hello', client: writer.client });
  assert.deepEqual(JSON.parse(writes[2][1].body), { request_id: 'req-1', decision: 'allow', client: writer.client });
  for (const [, init] of writes) assert.equal(JSON.parse(init.body).client, writer.client);
});

test('launch errors include the server error body', async (t) => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => ({ ok: false, status: 422, text: async () => JSON.stringify({ error: 'Unknown harness' }) });
  t.after(() => { globalThis.fetch = originalFetch; });

  await assert.rejects(
    launchAgent({ harness: 'bad', workspace: 'ws', role: 'worker', prompt: 'start' }),
    { message: 'Request failed (422): Unknown harness' },
  );
});
