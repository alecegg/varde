---
type: task
status: done
depends_on: [repo-setup]
owns: [spikes/toz-scripting/]
---

Steps:

- Not measured; read-only analysis.
- First task of the toz spikes.
- Count the existing toz scripts and profiles in /Users/alec/source/varde (read-only; locate them with a repository search and record the paths).
- Classify each as declarative (globs, regex, field select, trim, group, count) or genuinely programmatic (state, loops, arbitrary logic), with a one-line reason per item.
- Report the declarative share and conclude whether a declarative profile format (plus a narrow expression language if needed) can drop the embedded script runner.
- Write results/count.json with {total, declarative, programmatic, items:[{path, class, reason}]} and results/conclusion.md.
- The conclusion feeds toz-script-runner-spike.

#### Acceptance criteria

- assert: `python3 -c "import json;d=json.load(open('/Users/alec/source/varde-py/spikes/toz-scripting/results/count.json'));assert d['total']>0 and d['declarative']+d['programmatic']==d['total'] and len(d['items'])==d['total']"` → exit 0
- retrieve: `/Users/alec/source/varde-py/spikes/toz-scripting/results/conclusion.md` → declarative share and an explicit yes/no/partial on dropping the embedded runner

#### Progress
