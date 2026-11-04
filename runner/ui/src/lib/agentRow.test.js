import { describe, expect, it } from 'vitest';
import { cardTitle, oneLine, shortId, workspaceName } from './agentRow.ts';

const agent = (overrides = {}) => ({
  agent_id: 'agent-123456789',
  role: 'builder',
  workspace: '/work/projects/demo',
  lifecycle: 'running',
  idle_status: null,
  pending_requests: [],
  ...overrides,
});

describe('cardTitle', () => {
  it('titles a card by role and workspace basename', () => {
    expect(cardTitle(agent())).toBe('builder: demo');
  });

  it('ignores trailing separators on the workspace', () => {
    expect(cardTitle(agent({ workspace: '/work/projects/demo/' }))).toBe('builder: demo');
  });

  it('falls back to the role when there is no usable workspace', () => {
    expect(cardTitle(agent({ role: 'reviewer', workspace: null }))).toBe('reviewer');
    expect(cardTitle(agent({ role: 'reviewer', workspace: '   ' }))).toBe('reviewer');
  });

  it('never uses the raw 32-character agent id as the title', () => {
    const id = '23d6751abf35461fa51672eaf427858a';
    expect(cardTitle(agent({ agent_id: id }))).toBe('builder: demo');
    expect(cardTitle(agent({ agent_id: id, workspace: `/work/${id}` }))).toBe('builder');
    expect(cardTitle(agent({ agent_id: id, workspace: `/work/${id}` }))).not.toContain(id);
  });

  it('names an unassigned role instead of leaving it blank', () => {
    expect(cardTitle(agent({ role: null }))).toBe('Unassigned role: demo');
    expect(cardTitle(agent({ role: '  ' }))).toBe('Unassigned role: demo');
  });
});

describe('workspaceName', () => {
  it('returns the last path segment for posix and windows paths', () => {
    expect(workspaceName('/work/projects/demo')).toBe('demo');
    expect(workspaceName('C:\\work\\demo\\')).toBe('demo');
  });

  it('returns an empty string when the workspace is missing', () => {
    expect(workspaceName(null)).toBe('');
    expect(workspaceName('')).toBe('');
    expect(workspaceName('/')).toBe('');
  });
});

describe('shortId', () => {
  it('shows the first 8 characters as the secondary id', () => {
    expect(shortId('23d6751abf35461fa51672eaf427858a')).toBe('23d6751a');
    expect(shortId('abc')).toBe('abc');
  });
});

describe('oneLine state pill', () => {
  it('labels a running agent Running', () => {
    expect(oneLine(agent()).state).toEqual({ tone: 'running', label: 'Running', icon: '▶' });
  });

  it('labels pending work Blocked rather than unknown', () => {
    expect(oneLine(agent({ pending_requests: [{}] })).state.label).toBe('Blocked');
    expect(oneLine(agent({ idle_status: 'awaiting_question' })).state.label).toBe('Blocked');
  });

  it('labels a failed agent Failed', () => {
    expect(oneLine(agent({ lifecycle: 'failed' })).state.label).toBe('Failed');
  });

  it('labels an agent with no lifecycle or idle status Idle rather than unknown', () => {
    const row = oneLine(agent({ lifecycle: null, idle_status: null }));
    expect(row.state).toEqual({ tone: 'idle', label: 'Idle', icon: '○' });
    expect(row.state.label).not.toBe('unknown');
  });

  it('labels a completed agent Completed', () => {
    expect(oneLine(agent({ lifecycle: 'completed' })).state.label).toBe('Completed');
  });
});

describe('oneLine', () => {
  it('composes the title, short id, and state', () => {
    expect(oneLine(agent())).toEqual({
      title: 'builder: demo',
      shortId: 'agent-12',
      state: { tone: 'running', label: 'Running', icon: '▶' },
    });
  });
});
