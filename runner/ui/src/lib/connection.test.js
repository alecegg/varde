import { describe, expect, it } from 'vitest';
import { connectionProblemVisible, FAILURE_GRACE_MS, initialConnection, nextConnection } from './connection.ts';

describe('connection state machine', () => {
  it('does not report initial connection attempts as a failure', () => {
    const initial = initialConnection(0);
    expect(connectionProblemVisible(initial)).toBe(false);
    expect(nextConnection(initial, 'tick', FAILURE_GRACE_MS)).toEqual(initial);
  });

  it('waits through the grace period after an error', () => {
    const reconnecting = nextConnection(initialConnection(0), 'error', 10);
    expect(nextConnection(reconnecting, 'tick', 10 + FAILURE_GRACE_MS - 1).status).toBe('reconnecting');
    const failed = nextConnection(reconnecting, 'tick', 10 + FAILURE_GRACE_MS);
    expect(connectionProblemVisible(failed)).toBe(true);
  });

  it('clears a failure when the stream recovers', () => {
    const failed = nextConnection(nextConnection(initialConnection(0), 'error', 1), 'tick', FAILURE_GRACE_MS + 1);
    expect(nextConnection(failed, 'open', FAILURE_GRACE_MS + 2)).toEqual({ status: 'healthy', since: FAILURE_GRACE_MS + 2 });
  });
});
