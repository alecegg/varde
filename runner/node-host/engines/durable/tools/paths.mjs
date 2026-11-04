// Path confinement for file tools: lexical check plus a realpath check so a
// symlink inside the workspace cannot lead outside it.
import { realpath } from "node:fs/promises";
import { dirname, isAbsolute, relative, resolve, sep } from "node:path";

export class ToolRefusal extends Error {
  constructor(message) {
    super(`refused: ${message}`);
    this.name = "ToolRefusal";
  }
}

export function isInside(root, target) {
  const rel = relative(root, target);
  return rel === "" || (rel !== ".." && !rel.startsWith(`..${sep}`) && !isAbsolute(rel));
}

async function realOfNearestAncestor(path) {
  let current = path;
  for (;;) {
    try {
      return await realpath(current);
    } catch (error) {
      if (error?.code !== "ENOENT" && error?.code !== "ENOTDIR") throw error;
      const parent = dirname(current);
      if (parent === current) throw error;
      current = parent;
    }
  }
}

/** Resolve `path` against `cwd`; refuse anything that lands outside it. */
export async function confine(cwd, path) {
  if (typeof path !== "string" || path === "" || path.includes("\0")) {
    throw new ToolRefusal("path must be a non-empty string");
  }
  const absolute = resolve(cwd, path);
  if (!isInside(cwd, absolute)) throw new ToolRefusal(`path escapes the workspace: ${path}`);
  const [realRoot, realTarget] = await Promise.all([realpath(cwd), realOfNearestAncestor(absolute)]);
  if (!isInside(realRoot, realTarget)) throw new ToolRefusal(`path escapes the workspace through a link: ${path}`);
  return absolute;
}
