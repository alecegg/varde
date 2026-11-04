from __future__ import annotations

import subprocess
import sys


def test_hook_path_imports_no_module_libraries():
    script = """
import sys
import varde.glue.hook
import varde.glue.session_notes
import varde.glue.contracts
import varde.fastpath
blocked = {name for name in sys.modules if name.startswith('varde_learn.')}
assert 'varde_learn.loop.diagnose' not in blocked, sorted(blocked)
allowed = {
    'varde_learn.knowledge',
    'varde_learn.knowledge.memory',
    'varde_learn.knowledge.memory_config',
}
assert blocked <= allowed, sorted(blocked - allowed)
assert 'varde_code' not in sys.modules
assert 'varde_code.query' not in sys.modules
assert 'varde_toz' not in sys.modules
assert 'varde_workflow' not in sys.modules
"""
    subprocess.run([sys.executable, "-c", script], check=True)  # noqa: S603 - Imports the hook in a clean interpreter to test startup isolation.
