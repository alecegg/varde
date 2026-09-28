#!/usr/bin/env bash
set -euo pipefail
skills_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python3 - "$skills_dir" <<'PY'
import subprocess, tempfile, re, sys
from pathlib import Path
skills=Path(sys.argv[1])
text=(skills/'varde-docs/references/spec-format.md').read_text()
recipe=re.search(r'```bash\n(.*?)\n```', text, re.S)[1]
with tempfile.TemporaryDirectory() as tmp:
 root=Path(tmp); subprocess.run(['git','init','-q',tmp],check=True)
 (root/'a').write_bytes(b'alpha\n'); (root/'b').write_bytes(b'beta\n')
 def git(*args, data=None): return subprocess.run(['git',*args],cwd=root,input=data,capture_output=True,check=True).stdout.strip()
 expected=git('hash-object','--stdin',data=b''.join(p+git('hash-object','--no-filters',p.decode()) for p in [b'a',b'b']))
 valid=subprocess.run(['bash','-c',recipe],cwd=root,input=b'b\na\n',capture_output=True)
 assert valid.returncode==0 and valid.stdout.strip()==expected, valid
 invalid=subprocess.run(['bash','-c',recipe],cwd=root,input=b'a\nmissing\n',capture_output=True)
 assert invalid.returncode!=0 and not invalid.stdout.strip(), invalid
report=(skills/'varde-review/references/report.md').read_text()
assert 'explicit code area' in report and 'git ls-files -- <area>' in report
assert 'every scoped file' in report
handoff=(skills/'varde-knowledge/references/reflect-handoff.md').read_text()
assert 'unknown' in handoff and 'git diff <head_sha> -- <repo-relative-target>' in handoff
assert 'explicit relevant file links' in handoff
assert 'target independently' in handoff
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
 assert 'timestamps alone cannot' in handoff and 'external target' in handoff
 # An explicit area lists tracked files even without any pending diff.
 assert not git('diff','HEAD')
 assert git('ls-files','--','target.md').strip()==b'target.md'
refresh=(skills/'varde-docs/references/refresh.md').read_text()
inventory=refresh.split('2. Many')[0]
assert 'varde-workflow paths' not in inventory
assert 'Before that lookup' in refresh and 'reuse paths' in refresh
assert 'no memory lookup' in refresh and 'there are no lessons' in refresh
print('PASS: provenance failure, clean area, external handoff comparisons and first-use routing')
PY
