#!/usr/bin/env python3
"""Keep user-changed model settings when install.sh replaces a managed agent.

Usage: preserve-models.py --harness claude|codex|opencode|pi --agent NAME --staged FILE
                          [--installed FILE] [--dry-run]

FILE (--staged) is the shipped variant, already carrying the ownership marker.
Without --dry-run it is rewritten in place: user-changed model lines from
--installed replace the shipped ones, and one recorded-default line per shipped
model key is appended. A user-chosen model the shipped file omits (Pi
inherits the session model) is inserted without a recorded default. Preserved keys are printed one per line.
"""
import argparse
import re
import sys

KEYS = {"md": ["model"], "toml": ["model", "model_reasoning_effort"]}
KEY_LINE = {"md": r"{key}:\s*(.*?)\s*$", "toml": r"{key}\s*=\s*(.*?)\s*$"}
RECORD = {
    "md": re.compile(r"^<!-- varde-default: (.*?) -->$"),
    "toml": re.compile(r"^# varde-default: (.*?)$"),
}
# Values varde shipped in earlier releases, for installs that recorded no
# defaults. Keyed by (canonical agent name, key, harness). The current shipped
# value is always a default. Efforts and opencode models never changed.
HISTORY = {
    ("varde-reviewer", "model", "claude"): ["haiku"],
    ("varde-explorer", "model", "claude"): ["sonnet"],
    ("varde-explorer", "model", "codex"): ["gpt-5.6-luna"],
    ("varde-executor", "model", "codex"): ["gpt-5.6-luna"],
    ("varde-planner", "model", "codex"): ["gpt-5.6-terra"],
    ("varde-reviewer", "model", "codex"): ["gpt-5.6-sol"],
    # Pi agents pinned this model before they inherited the session model.
    ("varde-executor", "model", "pi"): ["deepseek/deepseek-v4-flash"],
    ("varde-explorer", "model", "pi"): ["deepseek/deepseek-v4-flash"],
    ("varde-planner", "model", "pi"): ["deepseek/deepseek-v4-flash"],
    ("varde-reviewer", "model", "pi"): ["deepseek/deepseek-v4-flash"],
}


def unquote(raw):
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
        return raw[1:-1]
    return raw


def header_lines(lines, kind):
    """Yield (index, line) for the region where model keys live."""
    if kind == "md":
        if not lines or lines[0].rstrip("\n") != "---":
            return
        for i in range(1, len(lines)):
            if lines[i].rstrip("\n") == "---":
                return
            yield i, lines[i]
    else:
        for i, line in enumerate(lines):
            if line.startswith("developer_instructions") or line.startswith("["):
                return
            yield i, line


def find_keys(lines, kind):
    """Map key -> (line index, raw value) for model keys in the header."""
    found = {}
    for i, line in header_lines(lines, kind):
        for key in KEYS[kind]:
            m = re.fullmatch(KEY_LINE[kind].format(key=re.escape(key)), line.rstrip("\n"))
            if m and key not in found:
                found[key] = (i, m.group(1))
    return found


def recorded_defaults(lines, kind):
    records = {}
    for line in lines:
        m = RECORD[kind].match(line.rstrip("\n"))
        if not m:
            continue
        for key in KEYS[kind]:
            m2 = re.fullmatch(KEY_LINE[kind].format(key=re.escape(key)), m.group(1))
            if m2:
                records[key] = unquote(m2.group(1))
    return records


def is_varde_default(key, value, shipped, records, args):
    if key in records:
        return value == records[key]
    if value == shipped:
        return True
    return value in HISTORY.get((args.agent, key, args.harness), [])


def plan(args, kind, staged_lines, installed_lines):
    """Return (key -> replacement line or None to delete) for kept settings.

    A key the staged file no longer ships is inserted when the installed file
    holds a user-chosen value and varde once shipped that key.
    """
    shipped = find_keys(staged_lines, kind)
    installed = find_keys(installed_lines, kind)
    records = recorded_defaults(installed_lines, kind)
    changes = {}
    for key, (_, shipped_raw) in shipped.items():
        if key not in installed:
            # A removed key stays removed only when a recorded default proves
            # varde once shipped it; older files simply never had one.
            if key in records:
                changes[key] = None
            continue
        index, raw = installed[key]
        if not is_varde_default(key, unquote(raw), unquote(shipped_raw), records, args):
            changes[key] = installed_lines[index]
    if kind == "md":
        for key in KEYS[kind]:
            if key in shipped or key not in installed:
                continue
            once_shipped = key in records or (args.agent, key, args.harness) in HISTORY
            index, raw = installed[key]
            if once_shipped and not is_varde_default(key, unquote(raw), None, records, args):
                changes[key] = installed_lines[index]
    return changes, shipped


def insert_at(lines):
    """Index for a new header key: after description:, else before the closing ---."""
    header = list(header_lines(lines, "md"))
    for i, line in header:
        if line.startswith("description:"):
            return i + 1
    return header[-1][0] + 1 if header else len(lines)


def rewrite(kind, staged_lines, changes, shipped):
    out = list(staged_lines)
    deleted = set()
    inserts = []
    for key, replacement in changes.items():
        if key not in shipped:
            inserts.append(replacement)
        elif replacement is None:
            deleted.add(shipped[key][0])
        else:
            out[shipped[key][0]] = replacement
    out = [line for i, line in enumerate(out) if i not in deleted]
    for line in inserts:
        out.insert(insert_at(out), line if line.endswith("\n") else line + "\n")
    if out and not out[-1].endswith("\n"):
        out[-1] += "\n"
    for key in KEYS[kind]:
        if key in shipped:
            line = staged_lines[shipped[key][0]].rstrip("\n")
            out.append(("<!-- varde-default: %s -->" if kind == "md" else "# varde-default: %s") % line + "\n")
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--harness", choices=["claude", "codex", "opencode", "pi"], required=True)
    parser.add_argument("--agent", required=True)
    parser.add_argument("--staged", required=True)
    parser.add_argument("--installed")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    kind = "toml" if args.harness == "codex" else "md"
    with open(args.staged, encoding="utf-8") as f:
        staged = f.readlines()
    changes, shipped = {}, find_keys(staged, kind)
    if args.installed:
        with open(args.installed, encoding="utf-8") as f:
            installed = f.readlines()
        changes, shipped = plan(args, kind, staged, installed)
    if not args.dry_run:
        with open(args.staged, "w", encoding="utf-8") as f:
            f.writelines(rewrite(kind, staged, changes, shipped))
    for key in changes:
        print(key)


if __name__ == "__main__":
    sys.exit(main())
