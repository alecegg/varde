import { describe, expect, it } from 'vitest';
import { answerForRequest, approvalsForThread, recordApprovalAnswer } from './inlineApproval.ts';

const agent = (agent_id, overrides = {}) => ({
  agent_id, harness: 'test', role: 'builder', workspace: '/tmp/project', lifecycle: 'running',
  idle_status: null, launched_by: null, root_launched_by: 'user', capabilities: { respond: true },
  pending_requests: [{ request_id: `${agent_id}-request`, kind: 'approval', summary: 'May I proceed?' }],
  ...overrides,
});

describe('approvalsForThread', () => {
  it('selects only requests for the instance agent', () => {
    expect(approvalsForThread('instance:one', [agent('one'), agent('two')]).map(({ agent }) => agent.agent_id)).toEqual(['one']);
  });

  it('selects bot-launched descendants for the manager thread', () => {
    expect(approvalsForThread('main', [
      agent('bot-child', { root_launched_by: 'bot:manager' }),
      agent('user-child'),
      agent('not-respondable', { root_launched_by: 'bot:manager', capabilities: { respond: false } }),
    ]).map(({ agent }) => agent.agent_id)).toEqual(['bot-child']);
  });

  it('keeps only the first matching agent for a duplicate request ID', () => {
    const first = agent('first', { root_launched_by: 'bot:manager', pending_requests: [{ request_id: 'shared', kind: 'approval', summary: 'First' }] });
    const second = agent('second', { root_launched_by: 'bot:manager', pending_requests: [{ request_id: 'shared', kind: 'approval', summary: 'Second' }] });

    expect(approvalsForThread('main', [first, second])).toEqual([{ agent: first, request: first.pending_requests[0] }]);
  });

  it('does not expose requests for unrelated threads', () => {
    expect(approvalsForThread('main:other', [agent('one')])).toEqual([]);
  });
});

describe('answerForRequest', () => {
  it('matches approved answers by request id', () => {
    expect(answerForRequest([
      { role: 'event', kind: 'answer', text: 'APPROVED', link: 'request:read%3Aworkspace' },
    ], 'read:workspace')).toBe('approved');
  });

  it('matches denied answers and ignores unrelated messages', () => {
    const messages = [
      { role: 'bot', kind: 'message', text: 'DENIED', link: null },
      { role: 'event', kind: 'answer', text: 'DENIED', link: 'request:other' },
    ];
    expect(answerForRequest(messages, 'mine')).toBeUndefined();
    expect(answerForRequest(messages, 'other')).toBe('denied');
  });
});

describe('recordApprovalAnswer', () => {
  it('shows the response as approved without waiting for a resolved event', () => {
    expect(recordApprovalAnswer({}, 'agent:request', 'allow')).toEqual({ 'agent:request': 'approved' });
  });

  it('shows a deny response immediately', () => {
    expect(recordApprovalAnswer({}, 'agent:request', 'deny')).toEqual({ 'agent:request': 'denied' });
  });
});
