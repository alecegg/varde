// Runs one shell command with a minimal environment and an attempt-local TMPDIR.
import { spawn } from "node:child_process";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";

const OUTPUT_CAP = 12000;
const DEFAULT_TIMEOUT_S = 30;
const MAX_TIMEOUT_S = 120;
const IDENTITY_KEYS = ["VARDE_AGENT_ID", "VARDE_HARNESS"];

/** Child env: PATH, TMPDIR and the two identity variables only; never provider credentials. */
export function childEnv(sessionEnv, tmpDir) {
  const env = {
    PATH: `${dirname(process.execPath)}:/usr/bin:/bin:/usr/sbin:/sbin`,
    TMPDIR: tmpDir,
    LANG: "C.UTF-8",
  };
  for (const key of IDENTITY_KEYS) {
    if (typeof sessionEnv?.[key] === "string") env[key] = sessionEnv[key];
  }
  return env;
}

function killGroup(pid) {
  try {
    process.kill(-pid, "SIGKILL");
  } catch {
    // already gone
  }
}

export async function runShell(command, { cwd, sessionEnv, timeoutS, track }) {
  const seconds = Math.min(Number(timeoutS) > 0 ? Number(timeoutS) : DEFAULT_TIMEOUT_S, MAX_TIMEOUT_S);
  const tmpDir = await mkdtemp(join(tmpdir(), "varde-pi-"));
  try {
    return await new Promise((resolve, reject) => {
      const child = spawn("/bin/sh", ["-c", command], {
        cwd,
        env: childEnv(sessionEnv, tmpDir),
        stdio: ["ignore", "pipe", "pipe"],
        detached: true,
      });
      child.on("error", reject);
      track?.add(child.pid);
      let output = "";
      let timedOut = false;
      const collect = (chunk) => {
        if (output.length < OUTPUT_CAP) output += chunk.toString("utf8");
      };
      child.stdout.on("data", collect);
      child.stderr.on("data", collect);
      const timer = setTimeout(() => {
        timedOut = true;
        killGroup(child.pid);
      }, seconds * 1000);
      child.on("close", (code) => {
        clearTimeout(timer);
        killGroup(child.pid); // sweep background leftovers
        track?.remove(child.pid);
        resolve(`${output.slice(0, OUTPUT_CAP)}${timedOut ? "\ntimed out" : `\nexit_code=${code ?? 1}`}`);
      });
    });
  } finally {
    await rm(tmpDir, { recursive: true, force: true });
  }
}
