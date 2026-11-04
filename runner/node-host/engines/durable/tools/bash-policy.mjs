// Pure classification of shell commands. "Discovery" commands only read
// relative paths inside the workspace; everything else is "other" and needs
// either a refusal (read-only) or an approval (workspace-write).
// git is not discovery: repository config (textconv, external diff, fsmonitor, pager,
// aliases) can run programs, so every git command goes through the approval gate.

const MAX_COMMAND_CHARS = 2000;
const FORBIDDEN = /[<>;`\\$(){}!~\n\r&]|\|\|/;
const SEGMENT_SPLIT = /\s*(?:&&|\|)\s*/;
const SIMPLE = new Set(["pwd", "ls", "cat", "head", "tail", "wc", "grep", "sort", "uniq", "cut", "echo", "stat", "file"]);
const FIND_WRITE_FLAGS = /^-(exec|execdir|ok|okdir|delete|fprint|fprint0|fprintf|fls)$/;

export function tokenize(segment) {
  const tokens = [];
  const pattern = /"([^"]*)"|'([^']*)'|(\S+)/g;
  for (const match of segment.matchAll(pattern)) tokens.push(match[1] ?? match[2] ?? match[3]);
  return tokens;
}

function pathArgIssue(arg) {
  const value = arg.includes("=") ? arg.slice(arg.indexOf("=") + 1) : arg;
  if (value.startsWith("/") || value.startsWith("~")) return "absolute paths are not allowed";
  if (value.split("/").includes("..")) return "parent directory references are not allowed";
  return null;
}

function segmentIssue(tokens) {
  const [name, ...args] = tokens;
  if (name === undefined) return "empty command";
  const pathIssue = args.map(pathArgIssue).find(Boolean);
  if (pathIssue) return pathIssue;
  if (name === "cd") return args.length === 1 ? null : "cd needs exactly one relative directory";
  if (name === "find") return args.some((a) => FIND_WRITE_FLAGS.test(a)) ? "find may not execute or write" : null;
  if (name === "sort") return args.some((a) => a === "-o" || /^--(output|compress-program)/.test(a)) ? "sort may not write or run programs" : null;
  return SIMPLE.has(name) ? null : `${name} is not a discovery command`;
}

/** @returns {{kind: "discovery", segments: string[][]} | {kind: "other", reason: string}} */
export function classifyBash(command) {
  if (typeof command !== "string" || command.trim() === "") return { kind: "other", reason: "empty command" };
  if (command.length > MAX_COMMAND_CHARS) return { kind: "other", reason: "command too long" };
  if (FORBIDDEN.test(command.replaceAll("&&", " "))) return { kind: "other", reason: "redirects, substitutions, ';', '||' and background jobs are not discovery" };
  const segments = command.trim().split(SEGMENT_SPLIT).map(tokenize);
  for (const tokens of segments) {
    const issue = segmentIssue(tokens);
    if (issue) return { kind: "other", reason: issue };
  }
  return { kind: "discovery", segments };
}
