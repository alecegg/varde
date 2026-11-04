// read, ls, find, grep (safe) and edit, write (unsafe), all confined to cwd.
import { lstat, readFile, readdir, stat, writeFile } from "node:fs/promises";
import { basename, join, relative } from "node:path";
import { confine, ToolRefusal } from "./paths.mjs";

const MAX_RESULTS = 200;
const MAX_FILE_BYTES = 1_000_000;
const SKIP_DIRS = new Set([".git", "node_modules"]);
const text = (value) => ({ output: [{ type: "text", text: value }] });

export async function readTool(cwd, { path, offset = 1, limit = 200 }) {
  const file = await confine(cwd, path);
  const info = await stat(file);
  if (info.size > MAX_FILE_BYTES * 5) throw new ToolRefusal("file is too large to read");
  const lines = (await readFile(file, "utf8")).split("\n");
  const start = Math.max(0, offset - 1);
  return text(lines.slice(start, start + Math.min(limit, 500)).join("\n"));
}

export async function lsTool(cwd, { path = "." }) {
  const dir = await confine(cwd, path);
  const entries = await readdir(dir, { withFileTypes: true });
  return text(entries.map((e) => (e.isDirectory() ? `${e.name}/` : e.name)).sort().join("\n"));
}

async function* walk(root, dir) {
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) {
      if (!SKIP_DIRS.has(entry.name)) yield* walk(root, full);
    } else if (entry.isFile()) {
      yield full;
    }
  }
}

function globToRegExp(glob) {
  const escaped = glob.replace(/[.+^${}()|[\]\\]/g, "\\$&").replace(/\*/g, ".*").replace(/\?/g, ".");
  return new RegExp(`^${escaped}$`);
}

export async function findTool(cwd, { pattern, path = "." }) {
  const root = await confine(cwd, path);
  const matcher = globToRegExp(pattern);
  const found = [];
  for await (const file of walk(root, root)) {
    const rel = relative(cwd, file);
    if (matcher.test(basename(file)) || matcher.test(rel)) found.push(rel);
    if (found.length >= MAX_RESULTS) break;
  }
  return text(found.sort().join("\n"));
}

export async function grepTool(cwd, { pattern, path = ".", ignoreCase = false }) {
  const root = await confine(cwd, path);
  const regex = new RegExp(pattern, ignoreCase ? "i" : "");
  const rootInfo = await lstat(root);
  const files = rootInfo.isDirectory() ? walk(root, root) : [root];
  const hits = [];
  for await (const file of files) {
    if ((await stat(file)).size > MAX_FILE_BYTES) continue;
    const lines = (await readFile(file, "utf8")).split("\n");
    lines.forEach((line, index) => {
      if (hits.length < MAX_RESULTS && regex.test(line)) hits.push(`${relative(cwd, file)}:${index + 1}:${line}`);
    });
    if (hits.length >= MAX_RESULTS) break;
  }
  return text(hits.join("\n"));
}

export async function editTool(cwd, { path, oldText, newText }) {
  const file = await confine(cwd, path);
  const content = await readFile(file, "utf8");
  const first = content.indexOf(oldText);
  if (first < 0 || content.indexOf(oldText, first + oldText.length) >= 0) {
    throw new Error("oldText must match exactly once");
  }
  await writeFile(file, content.slice(0, first) + newText + content.slice(first + oldText.length));
  return text(`edited ${path}`);
}

export async function writeTool(cwd, { path, content }) {
  const file = await confine(cwd, path);
  await writeFile(file, content);
  return text(`wrote ${path}`);
}
