// Flags mid-turn silence. It only emits status events: it never aborts, kills
// or interrupts the query (flag-only decision, see CONTRACT.md).

export const DEFAULT_IDLE_S = 300;

export function createWatchdog({ setTimer = setTimeout, clearTimer = clearTimeout } = {}) {
  const states = new Map(); // session id -> {timer, silent}

  function arm(session, state) {
    clearTimer(state.timer);
    const idleMs = (session.idleTimeoutS ?? DEFAULT_IDLE_S) * 1000;
    state.timer = setTimer(() => fire(session, state), idleMs);
    state.timer.unref?.();
  }

  function fire(session, state) {
    const quiet = session.state === "running" && session.toolsInFlight.size === 0;
    if (quiet && !state.silent) {
      state.silent = true;
      session.emit("status", { status: "running", silent: true });
    }
    // Keep checking: a tool may finish later and the stream may stay quiet.
    if (session.state !== "ended") arm(session, state);
  }

  return {
    attach(session) {
      const state = { timer: null, silent: false };
      states.set(session.id, state);
      arm(session, state);
    },
    touch(session) {
      const state = states.get(session.id);
      if (!state) return;
      if (state.silent) {
        state.silent = false;
        session.emit("status", { status: "running", silent: false });
      }
      arm(session, state);
    },
    detach(session) {
      const state = states.get(session.id);
      if (state) clearTimer(state.timer);
      states.delete(session.id);
    },
    isSilent: (session) => states.get(session.id)?.silent ?? false,
  };
}
