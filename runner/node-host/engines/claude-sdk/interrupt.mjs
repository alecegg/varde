// Per-session Claude child process group: spawn through the SDK spawn hook,
// register with the host for parent-death cleanup, kill only that group.
import { spawn } from "node:child_process";

export const STOP_GRACE_MS = 5000;
export const INTERRUPT_GRACE_MS = 5000;

export function killGroup(pgid, signal) {
  try {
    process.kill(-pgid, signal);
    return true;
  } catch {
    return false; // group already gone
  }
}

function wrapChild(child) {
  let killed = false;
  return {
    stdin: child.stdin,
    stdout: child.stdout,
    get killed() {
      return killed;
    },
    get exitCode() {
      return child.exitCode;
    },
    get signalCode() {
      return child.signalCode;
    },
    // Signals reach the whole group, so tool subprocesses die with the child.
    kill(signal) {
      killed = true;
      return killGroup(child.pid, signal);
    },
    on: (event, listener) => child.on(event, listener),
    once: (event, listener) => child.once(event, listener),
    off: (event, listener) => child.off(event, listener),
  };
}

export function createProcesses({ stopGraceMs = STOP_GRACE_MS, interruptGraceMs = INTERRUPT_GRACE_MS } = {}) {
  const records = new Map(); // session id -> {pid, exited}

  function spawnOptions(session) {
    return {
      spawnClaudeCodeProcess(options) {
        const child = spawn(options.command, options.args, {
          cwd: options.cwd,
          env: options.env,
          stdio: ["pipe", "pipe", "ignore"],
          detached: true, // own session: pgid === pid
        });
        if (child.pid === undefined) throw new Error("claude child did not start");
        const record = { pid: child.pid, exited: null };
        record.exited = new Promise((resolve) => {
          child.once("exit", () => {
            killGroup(record.pid, "SIGKILL"); // sweep tool subprocesses left behind
            session.ctx.untrackChild(record.pid);
            resolve();
          });
        });
        child.on("error", () => {});
        records.set(session.id, record);
        session.ctx.trackChild(child.pid, child.pid);
        options.signal?.addEventListener("abort", () => killGroup(record.pid, "SIGKILL"), { once: true });
        return wrapChild(child);
      },
    };
  }

  return {
    spawnOptions,

    // Interrupt ends the session's Claude child: a running turn is first asked
    // to stop softly so its result is delivered, then (at once if the turn
    // ended, or after the grace period if it did not) this session's process
    // group is killed and the query ends as "interrupted". Sends are refused
    // meanwhile, so the kill can never land on a later turn. The plugin resumes
    // from the persisted handle on the next send.
    async interrupt(session) {
      const record = records.get(session.id);
      if (!record) {
        session.expirePermissions();
        await session.query?.interrupt();
        return;
      }
      session.interrupting = true;
      session.expirePermissions();
      if (session.state === "running") {
        await session.query?.interrupt();
        await session.waitIdle(interruptGraceMs);
      }
      session.killedBy = "interrupt";
      killGroup(record.pid, "SIGKILL");
    },

    async stop(session) {
      const record = records.get(session.id);
      session.query?.close();
      if (!record) return;
      let timer;
      const grace = new Promise((resolve) => {
        timer = setTimeout(resolve, stopGraceMs);
      });
      await Promise.race([record.exited, grace]);
      clearTimeout(timer);
      killGroup(record.pid, "SIGKILL");
      await record.exited;
    },

    release(session) {
      records.delete(session.id);
    },

    groupOf: (session) => records.get(session.id)?.pid ?? null,
  };
}
