# varde-design

Frontend design tooling for agents: checks for common page defects and slop,
design-token and project-survey reports, and starter pages. This scaffold has
no rules, skills or checker code yet; `varde design --help` is a stub.

## Render tier

The render tier measures a page in headless Chromium at every width in one
launch (`probe.py`) and judges the recorded measurements with a pure function
(`judge.py`). Playwright is an optional extra, so the static tier works
without it. To enable the render tier:

1. `pip install 'varde-design[render]'` (in a repository checkout:
   `uv sync --extra render`).
2. `playwright install chromium` (in a checkout: `uv run playwright install chromium`).

Without either, the probe reports `render: not run (<reason>)` with this hint
and the check exits 1. Chromium is launched single-process (`--single-process
--no-zygote --disable-gpu`), which works inside a sandbox that denies Mach
port registration; the sandbox must still allow reading the browser cache.

## Licence

MIT, declared in `pyproject.toml` (the repository has no root LICENSE file).
Starters and rules are original work. Any third-party text or code copied into
this module needs an entry in a `NOTICE` file in this directory.

## Layer

Level 1 in `layers.toml`: it may import only `varde-core` or lower, and not
`varde-data` (also level 1). Project settings belong in a `varde-design.toml`
read with the standard library `tomllib`.
