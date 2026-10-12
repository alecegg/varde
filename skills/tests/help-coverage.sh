#!/usr/bin/env bash
set -euo pipefail

# Checks single-line inline command spans; fenced blocks and spans with <placeholder> are not checked.

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
VARDE=${VARDE_BIN:-$REPO_ROOT/clis/target/debug/varde}
ALLOWLIST=$REPO_ROOT/skills/tests/help-coverage.allow

fail() { printf 'help-coverage: %s\n' "$*" >&2; return 1; }

python3 - "$REPO_ROOT" "$VARDE" "$ALLOWLIST" "${1:-}" <<'PY'
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

root, binary, allowlist, mode = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3]), sys.argv[4]

def read_allowlist(path):
    if not path.exists():
        return set()
    return {line.strip() for line in path.read_text().splitlines() if line.strip() and not line.lstrip().startswith('#')}

def check(files, allowed):
    cache = {}
    errors = []
    found = set()

    def help_for(words):
        key = tuple(words)
        if key not in cache:
            result = subprocess.run([binary, *words, '--help'], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            cache[key] = (result.returncode == 0, result.stdout)
        return cache[key]

    for file in files:
        text = file.read_text(errors='replace')
        for line_no, line in enumerate(text.splitlines(), 1):
            for match in re.finditer(r'`([^`]+)`', line):
                span = match.group(1).strip()
                if not span.startswith('varde') or re.match(r'^varde\s*:', span) or '--help' in span or re.search(r'<[^>]*>', span):
                    continue
                words = span.split()
                if not words or words[0] != 'varde' or len(words) < 2:
                    continue
                words = words[1:]
                flags = [word.rstrip('.,;)').split('=', 1)[0] for word in words if word.startswith('--')]
                command_words = []
                for word in words:
                    if word.startswith('-'):
                        break
                    command_words.append(word.rstrip('.,;:)'))
                if not command_words:
                    continue
                # Find the deepest prefix accepted as a subcommand. Trailing positional
                # words naturally fail once they are not a subcommand.
                accepted = None
                for end in range(1, len(command_words) + 1):
                    candidate = command_words[:end]
                    ok, _ = help_for(candidate)
                    if ok:
                        accepted = candidate
                if accepted is None:
                    display = file.relative_to(root) if file.is_relative_to(root) else file.relative_to(file.parents[2])
                    message = f'{display}:{line_no}: unknown command: varde {" ".join(command_words)}'
                else:
                    ok, output = help_for(accepted)
                    missing = [flag for flag in flags if not re.search(r'(?<![\w-])' + re.escape(flag.rstrip('=')) + r'(?![\w-])', output)]
                    display = file.relative_to(root) if file.is_relative_to(root) else file.relative_to(file.parents[2])
                    message = '' if not missing else f'{display}:{line_no}: varde {" ".join(accepted)} help lacks {", ".join(missing)}'
                display = file.relative_to(root) if file.is_relative_to(root) else file.relative_to(file.parents[2])
                identity = f'{display}|{span}'
                found.add(identity)
                if message and identity not in allowed:
                    errors.append(message)
    stale = allowed - found
    if stale:
        errors.extend(f'{allowlist.name}: stale entry: {item}' for item in sorted(stale))
    return errors

def source_files(base):
    paths = []
    for folder in (base / 'skills').glob('varde-*'):
        paths.extend(p for p in folder.rglob('*') if p.is_file() and p.suffix in {'.md', '.json', '.toml'})
    paths.extend(p for p in (base / 'skills/shared').rglob('*') if p.is_file() and p.suffix in {'.md', '.json', '.toml'})
    paths.extend(p for p in (base / 'agents').rglob('*') if p.is_file() and p.suffix in {'.md', '.json', '.toml'})
    return paths

if mode == '--self-test':
    # Run the checker against a temporary mutation and require its missing flag to fail.
    with tempfile.TemporaryDirectory(prefix='help-coverage.') as temp:
        base = Path(temp)
        fixture = base / 'skills/varde-fixture/SKILL.md'
        fixture.parent.mkdir(parents=True)
        fixture.write_text('Try `varde doc frontmatter --no-such-flag`.\n')
        errors = check([fixture], set())
        if not any('--no-such-flag' in error for error in errors):
            print('mutation fixture unexpectedly passed: missing flag was not detected', file=sys.stderr)
            sys.exit(1)
    print('help-coverage mutation fixture passed')
elif mode:
    print(f'usage: {Path(sys.argv[0]).name} [--self-test]', file=sys.stderr)
    sys.exit(2)
else:
    issues = check(source_files(root), read_allowlist(allowlist))
    if issues:
        print('\n'.join(issues), file=sys.stderr)
        sys.exit(1)
    print('Skill CLI help coverage passed.')
PY
