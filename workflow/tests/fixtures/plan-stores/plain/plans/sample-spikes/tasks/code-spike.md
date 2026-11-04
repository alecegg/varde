---
type: task
status: done
depends_on: [repo-setup]
owns: [spikes/code-behavior check/]
---

Steps:

- Index-speed rows are measured (shared lock); behavior check counts are not.
- Run the previous extractor (installed varde, index database under $TMPDIR, fixtures copied into this repo) and the Python extractor (already in varde-py src/) across all 21 grammars.
- Report fixture counts per language (flag any language with fewer than 5 fixtures) and entity counts and diffs of (kind, name, line) per language, grammar name and version per side per language, both 21-language sets, each diff classified as grammar-version difference or port bug, plus ABI and wheel gaps.
- Add index-speed rows: cold index, no-change refresh, 1-file edit wall time, previous vs Python.
- Write results/behavior check.json and results/index-speed.json.

#### Acceptance criteria

- assert: `python3 -c "import json;d=json.load(open('/Users/alec/source/varde-py/spikes/code-behavior check/results/behavior check.json'));assert len(d['languages'])==21 and all('grammar_previous' in l and 'grammar_py' in l and 'cause' in l for l in d['languages'])"` → exit 0
- assert: `python3 -c "import json;d=json.load(open('/Users/alec/source/varde-py/spikes/code-behavior check/results/index-speed.json'));assert {'cold','refresh','edit1'}<=set(d)"` → exit 0

#### Progress
