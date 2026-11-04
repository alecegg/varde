import { describe, expect, it } from 'vitest';
import { stateMarker } from './agentStatus.ts';

const agent = (overrides = {}) => ({
  agent_id: 'agent-1', harness: 'test', role: 'worker', workspace: 'ws',
  lifecycle: null, idle_status: null, capabilities: {}, pending_requests: [],
  ...overrides,
});

describe('stateMarker', () => {
  it('gives blocked, running, idle, completed, and failed agents distinct labels and icons', () => {
    const markers = [
      stateMarker(agent({ pending_requests: [{ request_id: 'r', kind: 'approval', summary: 'Allow?' }] })),
      stateMarker(agent({ lifecycle: 'running' })),
      stateMarker(agent({ lifecycle: 'idle' })),
      stateMarker(agent({ lifecycle: 'completed' })),
      stateMarker(agent({ lifecycle: 'failed' })),
    ];

    expect(markers.map(({ label }) => label)).toEqual(['Blocked', 'Running', 'Idle', 'Completed', 'Failed']);
    expect(new Set(markers.map(({ icon }) => icon)).size).toBe(5);
  });
});
