import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { answerApproval, pendingApproval } from './homeApprove.ts';

const agent = (agent_id, overrides = {}) => ({
  agent_id, harness: 'test', role: 'reviewer', workspace: '/tmp/project', lifecycle: 'running',
  idle_status: null, capabilities: { respond: true },
  pending_requests: [{ request_id: `${agent_id}-request`, kind: 'approval', summary: 'Run: git push origin main' }],
  ...overrides,
});

let calls = [];
let originalFetch;
let originalEventSource;

beforeEach(() => {
  calls = [];
  originalFetch = globalThis.fetch;
  originalEventSource = globalThis.EventSource;
  class FakeEventSource {
    constructor(url) { this.url = url; this.closed = false; queueMicrotask(() => this.onopen?.()); }
    close() { this.closed = true; }
  }
  globalThis.EventSource = FakeEventSource;
  globalThis.fetch = async (url, init = {}) => {
    calls.push([url, init]);
    return { ok: true, json: async () => ({ result: 'ok' }) };
  };
});

afterEach(() => {
  globalThis.fetch = originalFetch;
  globalThis.EventSource = originalEventSource;
});

describe('pendingApproval', () => {
  it('selects the first pending request of the row agent', () => {
    const approval = pendingApproval([agent('other'), agent('row')], 'row');

    expect(approval).toEqual({
      agentId: 'row',
      request: { request_id: 'row-request', kind: 'approval', summary: 'Run: git push origin main' }
    });
  });

  it('shows nothing for a row without a live respondable agent', () => {
    expect(pendingApproval([agent('row')], null)).toBeNull();
    expect(pendingApproval([agent('row')], 'missing')).toBeNull();
    expect(pendingApproval([agent('row', { pending_requests: [] })], 'row')).toBeNull();
    expect(pendingApproval([agent('row', { capabilities: { respond: false } })], 'row')).toBeNull();
  });

  it('never answers a request just by reading it', () => {
    const approval = pendingApproval([agent('row')], 'row');

    expect(approval).not.toBeNull();
    expect(calls).toEqual([]);
  });
});

describe('answerApproval', () => {
  it('sends the decision of the clicked Allow button once', async () => {
    const approval = pendingApproval([agent('row')], 'row');

    await answerApproval(approval, 'allow');

    expect(calls.map(([url]) => new URL(url, 'http://localhost').pathname)).toEqual(['/api/agents/row/respond']);
    expect(JSON.parse(calls[0][1].body)).toEqual({ request_id: 'row-request', decision: 'allow', client: expect.any(String) });
  });

  it('sends the decision of the clicked Deny button once', async () => {
    const approval = pendingApproval([agent('row')], 'row');

    await answerApproval(approval, 'deny');

    expect(JSON.parse(calls[0][1].body)).toEqual({ request_id: 'row-request', decision: 'deny', client: expect.any(String) });
  });
});
