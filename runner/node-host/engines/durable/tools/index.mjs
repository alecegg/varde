// Tool registrations per role. Engine dispatch seam: {methods, init, close}.
import { defineTool } from "@earendil-works/pi-durable";
import { Type } from "@earendil-works/pi-ai";
import { effectiveMode, replayTable, toolNamesFor } from "../roles.mjs";
import { bashExecute } from "./bash.mjs";
import { editTool, findTool, grepTool, lsTool, readTool, writeTool } from "./file-tools.mjs";

const optionalNumber = () => Type.Optional(Type.Number());

function definitions({ cwd, role, mode, sessionEnv, approvals, track }) {
  const file = (run) => async (args) => run(cwd, args);
  return {
    read: ["Read a file by line offset and limit.", Type.Object({ path: Type.String(), offset: optionalNumber(), limit: optionalNumber() }), file(readTool)],
    ls: ["List a directory.", Type.Object({ path: Type.Optional(Type.String()) }), file(lsTool)],
    find: ["Find files by name glob.", Type.Object({ pattern: Type.String(), path: Type.Optional(Type.String()) }), file(findTool)],
    grep: ["Search files with a regular expression.", Type.Object({ pattern: Type.String(), path: Type.Optional(Type.String()), ignoreCase: Type.Optional(Type.Boolean()) }), file(grepTool)],
    edit: ["Replace one unique exact string in a file.", Type.Object({ path: Type.String(), oldText: Type.String(), newText: Type.String() }), file(editTool)],
    write: ["Write a complete file inside the workspace.", Type.Object({ path: Type.String(), content: Type.String() }), file(writeTool)],
    bash: ["Run a shell command. Read-only discovery commands run at once; other commands need user approval.", Type.Object({ command: Type.String(), timeout: optionalNumber() }), bashExecute({ cwd, role, mode, sessionEnv, approvals, track })],
  };
}

/** Durable tool registrations for one session: the role's tool set, replay flags from replay.json. */
export function buildSessionTools({ cwd, role, mode, env, approvals, ctx }) {
  const track = ctx?.trackChild ? { add: (pid) => ctx.trackChild(pid, pid), remove: (pid) => ctx.untrackChild(pid) } : undefined;
  const all = definitions({ cwd, role, mode, sessionEnv: env, approvals, track });
  return toolNamesFor(role, mode).map((name) => {
    const [description, parameters, execute] = all[name];
    return defineTool({ name, description, parameters, replay: replayTable[name].replay, execute });
  });
}

export const methods = {
  "tools.list": async ({ role, mode }) => ({
    mode: effectiveMode(role, mode),
    tools: toolNamesFor(role, mode).map((name) => ({ name, replay: replayTable[name].replay })),
  }),
};
export async function init() {}
export async function close() {}
