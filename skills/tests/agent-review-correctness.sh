#!/usr/bin/env bash
set -euo pipefail
skills_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python3 - "$skills_dir" <<'PY'
import subprocess, tempfile, sys
from pathlib import Path
skills=Path(sys.argv[1])
report=(skills/'varde-review/references/report.md').read_text()
assert 'Explicit code area' in report and 'review-scope.sh area' in report
assert 'for area scopes, review listed files' in report
session_notes_resume=(skills/'varde-knowledge/references/session-notes-resume.md').read_text()
session_notes_write=(skills/'varde-knowledge/references/session-notes-write.md').read_text()
assert 'unknown' in session_notes_resume
assert 'external target' in session_notes_resume
assert 'explicit relevant file links' in session_notes_write
assert 'target independently' in session_notes_resume and 'target independently' in session_notes_write
# Exercise the documented comparison with handoff storage outside the repo.
with tempfile.TemporaryDirectory() as tmp:
 root=Path(tmp)/'repo'; root.mkdir(); external=Path(tmp)/'working'; external.mkdir()
 subprocess.run(['git','init','-q',str(root)],check=True)
 def git(*args):
  return subprocess.run(['git',*args],cwd=root,capture_output=True,check=True).stdout
 git('config','user.email','eval@example.invalid'); git('config','user.name','Eval')
 target=root/'target.md'; target.write_text('initial\n'); git('add','.'); git('commit','-qm','seed')
 baseline=git('rev-parse','HEAD').decode().strip()
 (external/'handoff.md').write_text(f'head_sha: {baseline}\ntarget: {target}\n')
 memory=external/'note.md'; memory.write_text('memory\n')
 import hashlib
 snapshot=hashlib.sha256(memory.read_bytes()).hexdigest()
 assert not git('diff',baseline,'--','target.md')
 target.write_text('unstaged\n'); assert git('diff',baseline,'--','target.md')
 git('add','target.md'); assert git('diff',baseline,'--','target.md')
 git('commit','-qm','changed'); assert git('diff',baseline,'--','target.md')
 assert hashlib.sha256(memory.read_bytes()).hexdigest()==snapshot
 memory.write_text('changed memory\n'); assert hashlib.sha256(memory.read_bytes()).hexdigest()!=snapshot
 # An explicit area lists tracked files even without any pending diff.
 assert not git('diff','HEAD')
 assert git('ls-files','--','target.md').strip()==b'target.md'
refresh=(skills/'varde-docs/references/refresh.md').read_text()
inventory=refresh.split('2. Many')[0]
assert 'varde setup paths' not in inventory
# Memory paths resolve once in SKILL.md, never mid-workflow.
assert 'varde setup paths' not in refresh
assert 'Resolve `<working>` and `<knowledge>` once' in (skills/'varde-docs/SKILL.md').read_text()
print('PASS: clean area, external handoff comparisons and first-use routing')
PY
