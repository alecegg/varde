import test from 'node:test';
import assert from 'node:assert/strict';
import { ConfigApiError, groupItems, loadRunnerConfig, restartNotice, restartRunner, saveRunnerConfig, validateValue } from './runnerConfigApi.ts';

const items = [
  { key: 'codex_app_server.enabled', group: 'harnesses', type: 'boolean', value: true },
  { key: 'limits.max_live_instances', group: 'limits', type: 'integer', value: 2, bounds: { min: 1, max: 64 } },
  { key: 'bot.daily_token_budget', group: 'bot', type: 'integer', value: 10, bounds: { min: 0, max: 100 } },
  { key: 'runner.require_user_pairing', group: 'runner', type: 'boolean', value: false },
];

test('groups config items by their server-provided group', () => {
  assert.deepEqual(groupItems(items), {
    harnesses: [items[0]],
    limits: [items[1]],
    bot: [items[2]],
    runner: [items[3]],
  });
});

test('validates boolean types and integer bounds from each item', () => {
  assert.equal(validateValue(items[0], false), null);
  assert.equal(validateValue(items[0], 'false'), 'Choose on or off.');
  assert.equal(validateValue(items[1], '1'), null);
  assert.equal(validateValue(items[1], '0'), 'Must be at least 1.');
  assert.equal(validateValue(items[2], '101'), 'Must be at most 100.');
  assert.equal(validateValue(items[2], '1.2'), 'Enter a whole number.');
});

test('shows a restart notice only for changes that require restart', () => {
  assert.equal(restartNotice(true), 'Restart the runner to apply this change.');
  assert.equal(restartNotice(false), '');
});

test('loads and writes through the runner config routes', async () => {
  const originalFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (url, init = {}) => {
    calls.push([url, init]);
    return new Response(JSON.stringify(url === '/api/runner/config' && init.method === 'PUT'
      ? { items, restart_required: true }
      : { items }), { status: 200 });
  };
  try {
    assert.deepEqual(await loadRunnerConfig(), items);
    assert.deepEqual(await saveRunnerConfig({ 'limits.max_live_instances': 3 }), { items, restart_required: true });
    assert.equal(calls[1][1].method, 'PUT');
    assert.deepEqual(JSON.parse(calls[1][1].body), { changes: { 'limits.max_live_instances': 3 } });
  } finally { globalThis.fetch = originalFetch; }
});

test('surfaces structured errors and restart rejection hints', async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response(JSON.stringify({ errors: { key: 'invalid' } }), { status: 400 });
  try {
    await assert.rejects(saveRunnerConfig({ key: false }), (error) => {
      assert.ok(error instanceof ConfigApiError);
      assert.deepEqual(error.errors, { key: 'invalid' });
      return true;
    });
    globalThis.fetch = async () => new Response(JSON.stringify({ error: 'not_managed', hint: 'Start service first.' }), { status: 409 });
    await assert.rejects(restartRunner(), /Start service first\./);
  } finally { globalThis.fetch = originalFetch; }
});
