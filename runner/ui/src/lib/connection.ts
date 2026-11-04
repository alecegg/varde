export type ConnectionStatus = 'connecting' | 'healthy' | 'reconnecting' | 'stale';
export type ConnectionState = { status: ConnectionStatus; since: number };
export type ConnectionEvent = 'open' | 'error' | 'tick';

let currentStatus: ConnectionStatus = 'connecting';

export const getConnectionStatus = (): ConnectionStatus => currentStatus;
export const setConnectionStatus = (status: ConnectionStatus): void => { currentStatus = status; };

// EventSource emits `error` during ordinary reconnect attempts. Wait before
// treating that transient state as a connection problem worth showing.
export const FAILURE_GRACE_MS = 5_000;
export const STALE_AFTER_MS = FAILURE_GRACE_MS;

export const initialConnection = (now: number): ConnectionState => ({ status: 'connecting', since: now });

export function nextConnection(state: ConnectionState, event: ConnectionEvent, now: number): ConnectionState {
  if (event === 'open') return { status: 'healthy', since: now };
  if (event === 'error') return state.status === 'healthy' || state.status === 'connecting' ? { status: 'reconnecting', since: now } : state;
  if (state.status === 'reconnecting' && now - state.since >= STALE_AFTER_MS) return { status: 'stale', since: state.since };
  return state;
}

export function connectionProblemVisible(state: ConnectionState): boolean {
  return state.status === 'stale';
}

export function connectionLabel(state: ConnectionState): string {
  return state.status === 'stale' ? 'Connection lost. Some updates may be delayed.' : '';
}
