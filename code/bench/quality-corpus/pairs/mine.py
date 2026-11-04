"""Mine developer-intent refactor pairs from local Git history.

Every local ref is walked by default; a clone made by ``corpus/fetch.py`` has
``refs/heads/pinned`` on the verified pin. A clone with no local branch refs
raises :class:`MiningError` rather than mining zero commits.

Python uses ``ast.parse``. Other languages use a local delimiter and
string/comment balance fallback; this is a syntax sanity check, not a full
parser. It never fetches grammars. The detector callable is
``(repo, parent, child, paths) -> bool``; ``null_detector`` accepts intent
and filters when no structural detector is available.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import random
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

INTENT = re.compile(
    r"simplif|readab|clean\s?up|extract\s+(?:method|function|class)|"
    r"reduce complexity|flatten|early return|split .* function|"
    r"remove duplication|rename .* for clarity",
    re.IGNORECASE,
)
SUFFIXES = {
    "python": {".py"},
    "javascript": {".js", ".jsx", ".mjs", ".cjs"},
    "typescript": {".ts", ".tsx"},
    "java": {".java"},
    "csharp": {".cs"},
    "go": {".go"},
    "rust": {".rs"},
    "cpp": {".cpp", ".cc", ".cxx", ".hpp", ".hh", ".hxx"},
}
PARSERS = {
    "python": "python",
    "py": "python",
    "javascript": "javascript",
    "js": "javascript",
    "typescript": "typescript",
    "ts": "typescript",
    "tsx": "tsx",
    "java": "java",
    "csharp": "c_sharp",
    "cs": "c_sharp",
    "go": "go",
    "rust": "rust",
    "rs": "rust",
    "cpp": "cpp",
    "c++": "cpp",
}
FUNCTION_TYPES = {
    "function_definition",
    "function_declaration",
    "function_item",
    "method_definition",
    "method_declaration",
    "arrow_function",
    "function_expression",
    "method",
}


class MiningError(RuntimeError):
    """Raised when local git history cannot be read."""


def null_detector(*_args: object) -> bool:
    """Explicit detector adapter for languages without a structural detector."""
    return True


def _git(repository: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise MiningError(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result.stdout


def _language_key(language: str) -> str:
    key = language.lower()
    if key not in PARSERS:
        raise ValueError(f"unsupported language: {language}")
    return key


def _is_parseable(source: str, language: str) -> bool:
    key = _language_key(language)
    if key in {"python", "py"}:
        try:
            ast.parse(source)
        except SyntaxError:
            return False
        return True
    return _balanced_source(source, key)


def _balanced_source(source: str, language: str) -> bool:
    """Check delimiters while ignoring quoted strings and language comments."""
    pairs = {"(": ")", "[": "]", "{": "}"}
    closing = set(pairs.values())
    stack = []
    quote = ""
    escaped = False
    line_comment = False
    block_comment = False
    index = 0
    while index < len(source):
        char = source[index]
        following = source[index + 1] if index + 1 < len(source) else ""
        if line_comment:
            if char == "\n":
                line_comment = False
        elif block_comment:
            if char == "*" and following == "/":
                block_comment = False
                index += 1
        elif quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = ""
        elif char in {'"', "'", "`"}:
            quote = char
        elif char == "/" and following == "/":
            line_comment = True
            index += 1
        elif char == "/" and following == "*":
            block_comment = True
            index += 1
        elif char == "#" and language in {"python", "ruby", "bash"}:
            line_comment = True
        elif char in pairs:
            stack.append(pairs[char])
        elif char in closing and (not stack or stack.pop() != char):
            return False
        index += 1
    return not stack and not quote and not block_comment and bool(source.strip())


def _source_files(
    repository: Path, parent: str, child: str, language: str
) -> list[str]:
    changes = _git(
        repository, "diff-tree", "--no-commit-id", "--name-only", "-r", parent, child
    )
    suffixes = SUFFIXES[_language_key(language)]
    return sorted(
        path for path in changes.splitlines() if Path(path).suffix.lower() in suffixes
    )


def _show(repository: Path, revision: str, path: str) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(repository), "show", f"{revision}:{path}"],
        check=False,
        capture_output=True,
    )
    if result.returncode:
        return None
    return result.stdout.decode("utf-8", errors="replace")


def _linked_issue(message: str, issue_text: dict[str, str]) -> list[str]:
    references = re.findall(r"(?:#|issues?/)(\d+)", message, re.IGNORECASE)
    return [issue_text[number] for number in references if number in issue_text]


def _function_bodies(source: str, language: str) -> dict[str, str]:
    if _language_key(language) in {"python", "py"}:
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return {}
        return {
            node.name: ast.dump(node, include_attributes=False)
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
    bodies = {}
    declaration = re.compile(
        r"(?:\b(?:function|func|fn|def)\s+|\b)"
        r"([A-Za-z_$][\w$]*)\s*\([^;{}]*\)\s*(?:const\s*)?\{"
    )
    excluded = {"if", "for", "while", "switch", "catch", "with", "match"}
    for match in declaration.finditer(source):
        name = match.group(1)
        if name in excluded:
            continue
        opening = match.end() - 1
        closing = _matching_brace(source, opening)
        if closing is not None:
            bodies[name] = source[opening + 1 : closing]
    return bodies


def _matching_brace(source: str, opening: int) -> int | None:
    depth = 0
    quote = ""
    escaped = False
    for index in range(opening, len(source)):
        char = source[index]
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = ""
        elif char in {'"', "'", "`"}:
            quote = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
    return None


def _changed_functions(
    repository: Path, parent: str, child: str, files: list[str], language: str
) -> tuple[list[str], dict[str, tuple[str, str]]]:
    changed: set[str] = set()
    content: dict[str, tuple[str, str]] = {}
    for path in files:
        before, after = _show(repository, parent, path), _show(repository, child, path)
        if (
            before is None
            or after is None
            or not _is_parseable(before, language)
            or not _is_parseable(after, language)
        ):
            return [], {}
        content[path] = (before, after)
        before_bodies, after_bodies = (
            _function_bodies(before, language),
            _function_bodies(after, language),
        )
        changed.update(
            name
            for name in before_bodies.keys() | after_bodies.keys()
            if before_bodies.get(name) != after_bodies.get(name)
        )
    return sorted(changed), content


def _generated(path: str, content: dict[str, tuple[str, str]]) -> bool:
    lowered = path.lower()
    if any(
        part in lowered for part in ("/generated/", ".generated.", ".g.", "_generated")
    ):
        return True
    return any(
        re.search(
            r"(?:@generated|<auto-generated|\bgenerated\b)", text[:500], re.IGNORECASE
        )
        for pair in content.values()
        for text in pair
    )


def _is_public(name: str, source: str, language: str) -> bool:
    key = _language_key(language)
    if key in {"python", "py", "rust", "rs"}:
        return not name.startswith("_") and (
            key not in {"rust", "rs"}
            or bool(re.search(rf"pub\s+fn\s+{re.escape(name)}\b", source))
        )
    if key == "go":
        return name[:1].isupper()
    if key in {"java", "csharp", "cs"}:
        return bool(re.search(rf"\bpublic\b[^;{{}}]*\b{re.escape(name)}\s*\(", source))
    return True


def _adds_public_feature(before: str, after: str, language: str) -> bool:
    old, new = _function_bodies(before, language), _function_bodies(after, language)
    additions = new.keys() - old.keys()
    called = {
        name
        for name in additions
        if len(re.findall(rf"\b{re.escape(name)}\s*\(", after)) > 1
    }
    return any(
        _is_public(name, after, language) and name not in called for name in additions
    )


def _walked_commits(repository: Path, revision: str | None) -> list[str]:
    """Return commits to mine, requiring local refs when none is named."""
    if revision is not None:
        return _git(repository, "rev-list", "--reverse", revision).splitlines()
    branches = _git(repository, "for-each-ref", "--format=%(refname)", "refs/heads")
    if not branches.split():
        raise MiningError(
            f"{repository}: no local branch refs to mine; fetch the repository "
            "with corpus/fetch.py, which leaves refs/heads/pinned, or pass "
            "--revision"
        )
    return _git(repository, "rev-list", "--reverse", "--all").splitlines()


def mine_repository(
    repository: Path,
    repository_name: str,
    language: str,
    *,
    revision: str | None = None,
    issue_text: dict[str, str] | None = None,
    detector: Callable[[Path, str, str, list[str]], bool] = null_detector,
) -> list[str]:
    """Return accepted commit pairs as canonical JSONL records.

    Every local ref is walked unless ``revision`` names one. The detector
    callable receives the local repository, parent and child SHA, and changed
    source paths. Use ``null_detector`` when none is available.
    """
    repository = repository.resolve()
    issues = issue_text or {}
    output = []
    commits = _walked_commits(repository, revision)
    for child in commits:
        parents = _git(repository, "rev-list", "--parents", "-n", "1", child).split()
        if len(parents) != 2:
            continue
        parent = parents[1]
        message = _git(repository, "show", "-s", "--format=%B", child).strip()
        linked = _linked_issue(message, issues)
        if not INTENT.search(" ".join([message, *linked])) or re.search(
            r"^This reverts commit\s+[0-9a-f]+",
            message,
            re.IGNORECASE | re.MULTILINE,
        ):
            continue
        files = _source_files(repository, parent, child, language)
        if not files or len(files) > 5:
            continue
        if _generated("\n".join(files), {}):
            continue
        functions, content = _changed_functions(
            repository, parent, child, files, language
        )
        if not functions or len(functions) > 6:
            continue
        if _generated("\n".join(files), content):
            continue
        if any(
            _adds_public_feature(before, after, language)
            for before, after in content.values()
        ):
            continue
        if not detector(repository, parent, child, files):
            continue
        group_id = (
            "refactor-"
            + hashlib.sha256(f"{repository_name}\0{child}".encode()).hexdigest()[:16]
        )
        samples = [f"{child}:before", f"{child}:after"]
        record = {
            "repo": repository_name,
            "parent_sha": parent,
            "child_sha": child,
            "changed_functions": functions,
            "intent_evidence": {"message": message, "linked_issues": linked},
            "filters_passed": [
                "developer_intent",
                "not_revert",
                "not_merge",
                "source_file_limit",
                "function_limit",
                "no_public_feature_addition",
                "parse_before_after",
                "not_generated",
                "detector_confirmed"
                if detector is not null_detector
                else "null_detector",
            ],
            "language": language,
            "pair_group_id": group_id,
            "pair_group": {
                "id": group_id,
                "repository": repository_name,
                "kind": "refactor",
                "samples": samples,
            },
        }
        output.append(json.dumps(record, sort_keys=True, separators=(",", ":")))
    return output


def precision_sample(
    records: list[dict], seed: int = 0, count: int = 40
) -> dict[str, list[dict]]:
    """Draw stable, without-replacement samples for each language."""
    grouped: dict[str, list[dict]] = {}
    for record in records:
        grouped.setdefault(record["language"], []).append(record)
    return {
        language: random.Random(f"{seed}:{language}").sample(  # noqa: S311 - Reproducible corpus sampling is not cryptographic.
            items, min(count, len(items))
        )
        for language, items in sorted(grouped.items())
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repository", type=Path)
    parser.add_argument("repository_name")
    parser.add_argument("language")
    parser.add_argument(
        "--revision",
        help="commit or ref to walk instead of every local ref (default: all refs)",
    )
    args = parser.parse_args()
    try:
        lines = mine_repository(
            args.repository,
            args.repository_name,
            args.language,
            revision=args.revision,
        )
    except MiningError as error:
        print(error, file=sys.stderr)
        return 1
    for line in lines:
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
