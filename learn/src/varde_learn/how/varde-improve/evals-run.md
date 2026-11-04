---
topic: varde-improve/evals-run
version: 1
summary: Eval step 3 of 6 - billed, needs the user's explicit cost approval - run the output eval
---

## Run and compare

Run `varde learn measure <skill-dir> output`; `--help` lists options. Results
apply only to the selected harness and model without fallback, and the command
copies `<skill-dir>` as-is. For a repo skill listed in
`core/src/varde_core/skills/shared/MANIFEST`, sync it in an
isolated temp environment with
`HOME=<temp-dir>/home XDG_CONFIG_HOME=<temp-dir>/xdg VARDE_CONFIG_DIR=<temp-dir>/config VARDE_TOZ_CONFIG_DIR=<temp-dir>/toz
varde setup sync --skills-dir <temp-dir>/skills
--agents-dir <temp-dir>/agents --harnesses none`, then set `<skill-dir>` to
`<temp-dir>/skills/<skill>` so shared files resolve.
