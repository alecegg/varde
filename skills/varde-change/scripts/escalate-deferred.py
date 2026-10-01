#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Copy a plan's escalated review findings into the standing deferred review.

Usage: escalate-deferred.py --plan-dir <abs> --deferred-dir <abs> [--json]

A candidate is a finding in one of the plan's nested reviews (a direct child
folder of --plan-dir holding review.md) with `Disposition: blank` and an
`Escalated:` note. Each candidate is copied into the matching <CATEGORY>.md of
--deferred-dir under the next unused category-local ID, with `Source:
<plan-id>/<review-id>` and `Source finding: <original-id>` fields, and the
deferred review.md is created or updated. A candidate whose Source plus Source
finding already exists in the deferred review is skipped. After every copy is
written, each candidate's source finding is set to `Disposition: escalated`.

Every file is parsed and validated before anything is written.
Exit codes: 0 ok, 1 malformed input (nothing written), 2 usage error.
"""

import argparse
import datetime
import json
import os
import re
import sys
import tempfile
from pathlib import Path

HEADING = re.compile(r"^## \[([A-Z][A-Z0-9_]*)-(\d{3,})\] (\S.*)$")
FIELD = re.compile(r"^\*\*([A-Za-z][A-Za-z ]*):\*\* ?(.*)$")
CATEGORY_FILE = re.compile(r"^[A-Z][A-Z0-9_]*\.md$")
ESCALATED = re.compile(r"^(spec-conflict|scope-creep|human-only) +[—–-] +\S")
ALLOWED = {
    "Severity": {"critical", "high", "medium", "low", "info"},
    "Label": {"auto-fix", "triage"},
    "Disposition": {"blank", "fix", "dismiss", "action-item", "escalated"},
}


class Malformed(Exception):
    pass


class Finding:
    def __init__(self, path, start, lines):
        self.path, self.start, self.lines = path, start, lines
        match = HEADING.match(lines[0])
        if not match:
            raise Malformed(f"{path}:{start + 1}: bad finding heading {lines[0]!r}")
        self.category, self.number, self.title = match.group(1), int(match.group(2)), match.group(3)
        self.id = f"{self.category}-{match.group(2)}"
        if path.name != f"{self.category}.md":
            raise Malformed(f"{path}:{start + 1}: {self.id} is not in {self.category}.md")
        self.fields = {}  # name -> (line index within block, value)
        for index, line in enumerate(lines[1:], 1):
            if line.startswith("### "):
                break
            field = FIELD.match(line)
            if field:
                name, value = field.group(1), field.group(2).strip()
                if name in self.fields:
                    raise Malformed(f"{self.where(index)}: duplicate {name} field")
                self.fields[name] = (index, value)

    def where(self, index=0):
        return f"{self.path}:{self.start + index + 1}"

    def value(self, name):
        return self.fields.get(name, (None, None))[1]

    def validate(self, full):
        # A decided value may carry a note ("fix (abc123)"); blank must be exact.
        disposition = self.value("Disposition") or ""
        word = disposition.split(" ", 1)[0]
        if word not in ALLOWED["Disposition"] or (word == "blank" and disposition != "blank"):
            raise Malformed(f"{self.where()}: {self.id} Disposition {disposition!r} is invalid")
        if not full:
            return
        for name in ("Severity", "Label"):
            if self.value(name) not in ALLOWED[name]:
                raise Malformed(f"{self.where()}: {self.id} {name} {self.value(name)!r} is invalid")
        if not self.value("Location"):
            raise Malformed(f"{self.where()}: {self.id} has no Location")
        if not ESCALATED.match(self.value("Escalated")):
            raise Malformed(f"{self.where()}: {self.id} Escalated note {self.value('Escalated')!r} is invalid")
        for heading in ("### Summary", "### Solutions"):
            if heading not in (line.rstrip() for line in self.lines):
                raise Malformed(f"{self.where()}: {self.id} lacks {heading}")


def split_blocks(path, text):
    """Return (header lines, [Finding]) for a category file, ignoring fenced code."""
    lines = text.splitlines()
    starts, fence = [], None
    for index, line in enumerate(lines):
        stripped = line.lstrip()
        if fence:
            if stripped.startswith(fence):
                fence = None
        elif stripped.startswith(("```", "~~~")):
            fence = stripped[:3]
        elif line.startswith("## "):
            starts.append(index)
    if fence:
        raise Malformed(f"{path}: unclosed code fence")
    header = lines[: starts[0]] if starts else lines
    findings = []
    for position, start in enumerate(starts):
        end = starts[position + 1] if position + 1 < len(starts) else len(lines)
        block = lines[start:end]
        if block[0].startswith("## ["):
            findings.append(Finding(path, start, block))
        elif findings:  # a non-finding section closes the previous finding
            raise Malformed(f"{path}:{start + 1}: unexpected level-two heading {block[0]!r}")
    ids = [finding.id for finding in findings]
    duplicates = sorted({item for item in ids if ids.count(item) > 1})
    if duplicates:
        raise Malformed(f"{path}: duplicate IDs {', '.join(duplicates)}")
    return header, findings


def category_files(folder):
    return sorted(path for path in folder.iterdir() if path.is_file() and CATEGORY_FILE.match(path.name))


def plan_id(plan_dir):
    parts = plan_dir.parts
    if "plans" not in parts:
        return None
    index = len(parts) - 1 - parts[::-1].index("plans")
    rest = parts[index + 1 :]
    return "/".join(rest) if rest else None


def split_frontmatter(path, text):
    lines = text.splitlines()
    if not lines or lines[0] != "---" or "---" not in lines[1:]:
        raise Malformed(f"{path}: missing frontmatter")
    end = lines.index("---", 1)
    return lines[1:end], lines[end + 1 :]


def front_value(front, key):
    for line in front:
        if line.startswith(f"{key}:"):
            return line.split(":", 1)[1].strip()
    return None


def new_review(categories, counts, branch):
    front = [
        "---",
        "title: Deferred review findings",
        "type: review",
        f"date: {datetime.date.today().isoformat()}",
        f"branch: {branch or 'unknown'}",
        "target: standing deferred findings",
        "status: complete",
        "categories:",
        *[f"  - {category}" for category in categories],
        "triage_status: pending",
        "---",
    ]
    body = ["", "# Deferred review findings", "", "## Categories", "",
            "| Category | Status | Findings |", "|---|---|---:|",
            *[f"| {category} | complete | {counts[category]} |" for category in categories]]
    return "\n".join(front + body) + "\n"


def update_review(path, text, counts):
    front, body = split_frontmatter(path, text)
    if front_value(front, "type") != "review":
        raise Malformed(f"{path}: frontmatter type is not review")
    front = update_front_categories(path, front, counts)
    front = ["triage_status: partial" if line.strip() == "triage_status: complete" else line for line in front]
    body = update_table(path, body, counts)
    return "\n".join(["---", *front, "---", *body]) + "\n"


def update_front_categories(path, front, counts):
    index = next((i for i, line in enumerate(front) if line.startswith("categories:")), None)
    if index is None:
        raise Malformed(f"{path}: frontmatter has no categories")
    inline = front[index].split(":", 1)[1].strip()
    if inline:
        if not (inline.startswith("[") and inline.endswith("]")):
            raise Malformed(f"{path}: unreadable categories value {inline!r}")
        existing = [item.strip() for item in inline[1:-1].split(",") if item.strip()]
        merged = existing + [c for c in counts if c not in existing]
        return front[:index] + [f"categories: [{', '.join(merged)}]"] + front[index + 1 :]
    end = index + 1
    while end < len(front) and re.match(r"^\s+- ", front[end]):
        end += 1
    existing = [line.split("-", 1)[1].strip() for line in front[index + 1 : end]]
    added = [f"  - {c}" for c in counts if c not in existing]
    return front[:end] + added + front[end:]


def update_table(path, body, counts):
    try:
        section = body.index("## Categories")
    except ValueError:
        raise Malformed(f"{path}: no ## Categories section") from None
    first = next((i for i in range(section + 1, len(body)) if body[i].startswith("|")), None)
    rows = []
    while first is not None and first + len(rows) < len(body) and body[first + len(rows)].startswith("|"):
        rows.append(first + len(rows))
    if len(rows) < 2:
        raise Malformed(f"{path}: ## Categories has no table")
    seen = set()
    for i in rows[2:]:
        cells = [cell.strip() for cell in body[i].strip().strip("|").split("|")]
        if len(cells) != 3:
            raise Malformed(f"{path}:{i + 1}: bad Categories row")
        if cells[0] in counts:
            body[i] = f"| {cells[0]} | {cells[1]} | {counts[cells[0]]} |"
            seen.add(cells[0])
    added = [f"| {c} | complete | {counts[c]} |" for c in counts if c not in seen]
    return body[: rows[-1] + 1] + added + body[rows[-1] + 1 :]


def copy_block(finding, new_number, source):
    lines = list(finding.lines)
    while lines and not lines[-1].strip():
        lines.pop()
    lines[0] = f"## [{finding.category}-{new_number:03d}] {finding.title}"
    last_field = max(index for index, _ in finding.fields.values())
    extra = [f"**Source:** {source}", f"**Source finding:** {finding.id}"]
    return lines[: last_field + 1] + extra + lines[last_field + 1 :]


def atomic_write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    with os.fdopen(handle, "w") as stream:
        stream.write(text)
    os.replace(temp, path)


def plan_changes(plan_dir, deferred_dir):
    pid = plan_id(plan_dir)
    candidates = []  # (finding, source, review branch)
    for review in sorted(p for p in plan_dir.iterdir() if (p / "review.md").is_file()):
        front, _ = split_frontmatter(review / "review.md", (review / "review.md").read_text())
        branch = front_value(front, "branch")
        for path in category_files(review):
            _, findings = split_blocks(path, path.read_text())
            for finding in findings:
                finding.validate(full=False)
                if finding.value("Disposition") == "blank" and "Escalated" in finding.fields:
                    finding.validate(full=True)
                    candidates.append((finding, f"{pid}/{review.name}", branch))

    deferred = {}  # category -> [header, findings, new block lines]
    copies = {}  # (source, source id) -> deferred id
    if deferred_dir.is_dir():
        for path in category_files(deferred_dir):
            header, findings = split_blocks(path, path.read_text())
            deferred[path.stem] = [header, findings, []]
            for finding in findings:
                key = (finding.value("Source"), finding.value("Source finding"))
                if all(key):
                    copies[key] = finding.id
    review_path = deferred_dir / "review.md"
    review_text = review_path.read_text() if review_path.is_file() else None
    if review_text is not None:
        split_frontmatter(review_path, review_text)

    results = []
    for finding, source, _ in candidates:
        key = (source, finding.id)
        if key in copies:
            results.append({"action": "skipped", "source": source, "source_finding": finding.id,
                            "deferred_id": copies[key], "finding": finding})
            continue
        header, existing, added = deferred.setdefault(finding.category, [[f"# {finding.category}"], [], []])
        numbers = [f.number for f in existing] + [n for n, _ in added]
        number = max(numbers, default=0) + 1
        added.append((number, copy_block(finding, number, source)))
        copies[key] = f"{finding.category}-{number:03d}"
        results.append({"action": "escalated", "source": source, "source_finding": finding.id,
                        "deferred_id": copies[key], "finding": finding})

    writes = {}
    touched = {}
    for category, (header, existing, added) in deferred.items():
        if not added:
            continue
        path = deferred_dir / f"{category}.md"
        text = path.read_text().rstrip("\n") if path.is_file() else "\n".join(header).rstrip("\n")
        for _, block in added:
            text += "\n\n" + "\n".join(block)
        writes[path] = text + "\n"
        touched[category] = len(existing) + len(added)
    if touched:
        branch = next((b for _, _, b in candidates if b), None)
        writes[review_path] = (update_review(review_path, review_text, touched) if review_text is not None
                               else new_review(sorted(touched), touched, branch))
    return results, writes


def mark_sources(results):
    by_file = {}
    for result in results:
        by_file.setdefault(result["finding"].path, []).append(result["finding"])
    for path, findings in by_file.items():
        lines = path.read_text().splitlines()
        for finding in findings:
            index = finding.start + finding.fields["Disposition"][0]
            if lines[index].strip() != "**Disposition:** blank":
                raise Malformed(f"{finding.where()}: {finding.id} changed during the run")
            lines[index] = "**Disposition:** escalated"
        atomic_write(path, "\n".join(lines) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--plan-dir", required=True)
    parser.add_argument("--deferred-dir", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    plan_dir, deferred_dir = Path(args.plan_dir), Path(args.deferred_dir)
    if not (plan_dir.is_absolute() and deferred_dir.is_absolute()):
        parser.error("--plan-dir and --deferred-dir must be absolute")
    if not (plan_dir / "plan.md").is_file():
        parser.error(f"{plan_dir} has no plan.md")
    if not plan_id(plan_dir):
        parser.error(f"{plan_dir} is not under a plans/ folder")
    if deferred_dir.exists() and not deferred_dir.is_dir():
        parser.error(f"{deferred_dir} is not a directory")

    try:
        results, writes = plan_changes(plan_dir, deferred_dir)
    except Malformed as error:
        if args.json:
            print(json.dumps({"ok": False, "error": str(error)}))
        print(f"malformed: {error}", file=sys.stderr)
        return 1
    for path, text in writes.items():  # copies first
        atomic_write(path, text)
    try:
        mark_sources(results)  # a skipped copy may be from an interrupted run
    except Malformed as error:
        print(f"malformed: {error}; copies are written, rerun to mark sources", file=sys.stderr)
        return 1

    escalated = sum(r["action"] == "escalated" for r in results)
    summary = {"escalated": escalated, "skipped": len(results) - escalated}
    for result in results:
        del result["finding"]
    if args.json:
        print(json.dumps({"ok": True, "findings": results, "summary": summary}))
    else:
        for r in results:
            print(f"{r['action']} {r['source']} {r['source_finding']} -> deferred {r['deferred_id']}")
        print(f"summary: {summary['escalated']} escalated, {summary['skipped']} skipped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
