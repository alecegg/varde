---
status: completed
title: 'sample-core: shared Python core, contracts, code seams and fixtures, behavior check kit and package skeletons so every module plan can start against a stable interface'
type: plan
depends_on:
- sample-spikes
- python-port-toz
shared:
- uv.lock
- pyproject.toml
reviewed_commit: b97b26af2dc28f2567d952ec0f1b0db8dc7f256a
reviewed_on: 2026-10-14
branch: worktree/sample-core-post
---

## Problem

Toz was ported on an interim `_core` shim (223 lines mirroring varde-core). Every other module needs the same shared layer (redact, paths, sqlite, envelope, json_order, jsonio, notes, contracts, behavior check harness, code seams); without one owner they would each reinvent it, collide on package skeletons, and the wave-1 code plans would depend on each other's internals.

## Solution

A uv workspace under `python/` holds `varde-core`, `contracts package`, `test suite` and a skeleton for every module package (pyproject, `varde.modules` entry point, a stub manifest of every file each plan owns), plus the shared code seams (protocols, graph model, git, test-only previous-index reader), committed fixture repos, and `API.md` with a dependency-rules test. Module plans own disjoint files and import only what `API.md` lists.

## Non-goals

- Module logic (each module plan ports its own crate)
- App routing and packaging (python-port-app-shell)
- Switching toz to core (python-port-toz-adopt)
- Linux execution testing (deferred; only wheel availability here)
- Hook install and OS sandbox

## Constraints

- previous repo `/Users/alec/source/varde` (renamed `previous implementation` at cutover) is read-only; goldens come only from the reference implementation `/Users/alec/source/varde/clis/target/release/varde` through `test suite gen` and are committed, so `compare` never needs the reference implementation path
- SQLite schemas, file formats, paths and JSON key order identical to previous — previous and Python read the same stores during migration — except the code `index.db` (derived cache, see Decisions)
- Python >=3.14, no native extensions of our own at first (reopening is an explicit per-module user decision); third-party dependencies are the set core declares in each package's pyproject (extra ones go in plan `shared:` and need a one-line reason in the task Progress)
- Imports only as allowed by `python/varde-core/API.md`; only the app package depends on module packages
- Hook-path code (anything `varde capture --hook`, `varde note` or `varde event` reaches) imports nothing heavy at module import time
- Help text is a committed snapshot rendered verbatim (generated once from the reference implementation), not rebuilt from the parser
- Measured runs hold `/Users/alec/source/.varde-measure.lock`, use `ioreg` only, N>=30 for wall time, N>=5 for `ioreg` write bytes, record load, retain every run, no quiet-machine gating
- Gated: first task `gate-check`; no other task starts until the user's approval is recorded (condition 4)
- Wave-1 start signal: when `api-freeze` is done the orchestrator sends main a milestone message `core api-freeze done` (varde msg send --to main); wave-1 plans start then. Tasks wave 1 does not need (redact, text_audit, skill_relations, learn-base, linux wheels, shim mapping) run after `api-freeze`
- Package names: dist `varde-core`/`contracts package`/`test suite`, import `varde_core`/`old_contracts`/`test suite`; root workspace members `python/*` so new packages need no root edit
- Root `pyproject.toml` becomes a virtual workspace with no tree-sitter pin; the prototype `src/varde_py` and `tests/test_index.py` move unchanged to `spikes/prototype/`
- Dependency rules (Python): families `varde-toz`; `varde-md-core`+`varde-workflow`; `varde-learn`; `varde-doc`; `varde-code`; core imports no varde package; contracts imports only core; modules import core, contracts and their own family; `test suite` only as dev dependency or test import; only `varde` imports modules; edges come from pyproject dependencies plus an AST import scan; the test seeds a violation per rule

## Design

### Tech choices

- Layout: `python/<dist>/src/<import>/`, `python/<dist>/tests/`, goldens in `python/<dist>/tests/behavior check/{cases.json,golden/}`
- Module contract `old_contracts.module.Module`: `name`, `run(argv, io) -> int`, `help(path) -> str`
- Stub-per-plan rule: the skeleton task creates every stub file and a machine-readable `docs/core/stub-manifest.json` (plan -> files); `api-freeze` copies it into the `API.md` ownership table; each plan owns whole files and never edits another plan's stub
- All third-party deps for every package are declared upfront from the spike results (`spikes/packaging`), including newest tree-sitter and grammar wheels, ast-grep-py (newest, pinned and recorded in `docs/core/versions.md`), a file-event library for watch (watchdog)
- Newest tree-sitter and grammars: pinned at build time and recorded; previous reference implementation grammar lock is `ast-grep-language 0.45.3` (Cargo.lock), recorded as baseline

### Schema / data model

(none)

### API / interface contracts

- `varde_core.envelope`: `ENVELOPE_VERSION=1`, `success(data, meta)`, `negative_result(code, message, details, meta)`, `tool_error(code, message)` → dict with key order `schema_version, ok, outcome, data, meta`
- `varde_core.jsonio`: `dumps`, `dumps_pretty` matching `serde_json` (no ASCII escaping)
- `varde_core.paths`: `varde_config_dir()`, `data_dir()`; `varde_core.sqlite.configure_connection(conn)`; `varde_core.write_meter`: `WriteMeter.start()/bytes()`, `available()`, `scaled(limit)`
- `varde_core.redact`: `RedactConfig`, `Redactor(cfg)` (`ValueError` on invalid pattern), `.redact`, `.redact_spans`, `SecretValue`, `Kind`, `Span`, `Notice`, `values.*`
- `varde_core.json_order`: `append_entry`, `remove_matching_commands*`, `replace_owned_entries*`, `RemoveOptions`
- `varde_core.text_audit`: `audit(text, path) -> list[Finding]`, `Severity`, `Rule`, `expand_skill_dir`; `varde_core.skill_relations`: `parse(frontmatter) -> Relations` (raises `RelationError`), `closure(...)`, `IMPLICIT_SKILL`
- `varde_core.constants`: `TOZ_BLOCK_START/END`, `TOZ_NOTE`, `LEARN_NOTE`, `toz_instruction_block(template)`
- `old_contracts`: `Io`, `ApiError`, `CaptureInput`, `SearchQuery`, `SearchHit`, `SourceResult`, `Module`, and the protocols `ImpactQuery`, `OutputCapture`, `SearchSource`
- `varde_code.model` (entities, edges, languages, `EdgeKind`, `Community`, `RoleTag`, `span_of`), `varde_code.parse` (`Parser` protocol, tree-sitter implementation), `varde_code.toz_bridge`, `varde_code.git` (`run_git`, ported from `git.rs`)
- `varde_code.seams` (protocols; implementations are registered by the owning plan): `FileWalker.list_source_listing(root)`, `is_vcs_internal` and `IndexService.ensure_fresh/check_fresh/dump_state/repo_db_path` (impl: code-index), `ExtractionProvider.extract(path, source, language) -> ExtractOutput` incl. per-function complexity (impl: code-extract; reference implementation-JSON provider in tests), `GraphCache.read/write`
- `varde_code.graph_model.Graph` (data structure and serialization to Python's own format; algorithms stay in code-query)
- `varde_code.testing.previous_index.open_previous_index(path, repo_root)`: test-only; in-memory copy with `files.path` rebased to `repo_root`, build_version/mtime-size/dbPath checks off, `schema_version == 19`, scope and derived-slice revs on; `decode_graph_cache` (postcard) optional, since previous falls back to SQL load (`persist.rs:556-572`)
- `varde_code.pattern_match` (find_pattern LIBRARY): ast-grep-py matching on its own `ast_grep_py.SgRoot` (newest, pinned in `docs/core/versions.md`): `find_patterns`, `find_patterns_unbounded`, language table, C#/Solidity snippet wrapping; code-query's `find_pattern` mode and code-rules call it, so rules need no code-query dependency
- Behavior check CLI (what module plans use):
- `python -m test suite gen --module M --reference implementation PATH [--cases FILE] [--out DIR]`: runs the reference implementation on `cases.json`, writes goldens (default `python/<pkg>/tests/behavior check/golden`)
- `python -m test suite compare --module M [--golden DIR] [--cases FILE] [--min-cases N] [--all]`: runs Python, normalizes, prints `cases: N` and `mismatches: N`; exit 1 on any mismatch or if cases < `--min-cases`; never needs the reference implementation
- `python -m test suite.extractor --lang L (repeatable) --group A|B|all --min F --overall-min F --min-entities N [--report]` (plan-owned by code-extract): A = bash python previous javascript typescript tsx go java c cpp; B = csharp kotlin elixir dart php swift haskell ruby scala lua solidity; reads committed `behavior check/extract/<lang>/reference implementation.json`
- Fixture corpus (`code-fixtures`): fixture repos under `python/varde-code/tests/fixtures/repos/<name>/` at fixed repo-relative paths, a script that replays fixed git history (pinned author/date), reference implementation-built `index.db` and reference implementation `map extract` JSON under `fixtures/indexes/` and `fixtures/extract/`, built with toz isolated by `VARDE_TOZ_CONFIG_DIR`; per-language extractor fixtures need >= 100 reference implementation entities

## Decisions so far

- Core before modules → this plan completes first; module plans declare `depends_on: [sample-core]`
- Behavior check kit generalizes `python/varde-toz/tests/behavior check/{gen_golden,compare}.py` and `NORMALIZE.md` → toz keeps its copy until python-port-toz-adopt
- Code `model`/`parse`/seams/graph model/fixtures live here → the wave-1 code plans stay parallel with disjoint ownership (resolves undeclared index/query/rules/extract cross-imports)
- Condition 3 (Linux) owned here as per-platform wheel-resolution checks only
- Code index is a derived cache (user decision 2026-10-14) → Python builds and reads its own index at its own path (`<config>/code/repos-py/<name>-<hash>/index.db`) so previous and Python never force each other to rebuild during the dual run; table schemas stay identical where free, but `graph_cache` and `slice_meta.build_version` may differ; previous-built `index.db` fixtures are read only through the test seam (freshness checks off, postcard decoder). Relaxes 'identical SQLite schema' for the code index ONLY; the toz store stays identical
- ApiError and span_of live with the contracts/model in core (review finding) → rules and query no longer import each other
- Root pyproject becomes virtual and drops the tree-sitter pin → newest tree-sitter allowed
- find_pattern matching LIBRARY (ast-grep-py, own SgRoot) lives in core as `varde_code.pattern_match`; code-query wraps it as a mode and code-rules calls it → rules depend only on core and wave 1 stays parallel

## Open Questions

n/a — no open questions

## Assumptions

- The shim-to-core mapping (shim `redact(text, builtin=, patterns=)` -> `Redactor(cfg).redact`; `scaled(limit, setting)` -> `scaled(limit)`; `current_bytes()` -> `WriteMeter`) is recorded in `API-extra.md` (task `api-complete`, after the freeze) and used by toz-adopt — affects: api-complete, toz-adopt — confidence: high
- No reference implementation CLI exposes core functions, so core behavior check uses previous unit-test vectors transcribed into JSON fixtures — affects: core tests — confidence: medium

## Acceptance criteria

- [ ] Given the workspace
      When `uv sync` runs
      Then all packages resolve and install, with the newest tree-sitter (no `<0.26` pin anywhere)
      (assert: `cd /Users/alec/source/varde-py && uv sync --all-packages --frozen && ! grep -rn 'tree-sitter.*<0.26' pyproject.toml python/*/pyproject.toml` → exit 0)
- [ ] Given the dependency rules
      When the rules test runs (pyproject deps plus AST import scan, with seeded violations)
      Then core/contracts/module/app edges hold and each seeded violation fails
      (assert: `cd /Users/alec/source/varde-py && uv run pytest python/varde-core/tests/test_dependency_rules.py -q` → exit 0)
- [ ] Given wave 1 starts
      When `api-freeze` is done
      Then every import wave 1 needs is listed in `API.md` with a contract test, and main received the milestone message
      (assert: `cd /Users/alec/source/varde-py && uv run pytest python/varde-core/tests/test_api_contract.py -q` → exit 0 (imports every name listed in `API.md`, including `ApiError`, `span_of`, `ImpactQuery`, `OutputCapture`, `SearchSource`, the code seams))
- [ ] Given each skeleton package
      When its `varde.modules` entry point loads
      Then `run`, `help` exist and return exit code 2 with a stub message, and every stub file in the manifest exists
      (assert: `cd /Users/alec/source/varde-py && uv run pytest python/varde/tests/test_skeletons.py -q` → exit 0)
- [ ] Given the behavior check kit
      When a sample case is generated with a stub reference implementation script and compared
      Then compare prints `cases: N` and `mismatches: 0`, fails on a mutated golden and when cases < `--min-cases`; the toz goldens compare with exactly 65 cases
      (assert: `cd /Users/alec/source/varde-py && uv run pytest python/test suite/tests/ -q` → exit 0)
- [ ] Given the code test seam
      When tests open a committed previous-built `index.db` with freshness checks off
      Then Python reads tables with paths rebased to the checkout (the committed fixture is never written) and builds the graph from SQL or the optional postcard decoder; production code never reads the freshness-off flag
      (assert: `cd /Users/alec/source/varde-py && uv run pytest python/varde-code/tests/core/test_seams.py -q` → exit 0)
- [ ] Given owned condition 3
      When wheel availability is checked per platform
      Then all three platforms resolve; Linux execution deferred
      (assert: `cd /Users/alec/source/varde-py && grep -qE '^\| macos-arm64 .*resolved' docs/core/linux-wheels.md && grep -qE '^\| linux-x86_64 .*resolved' docs/core/linux-wheels.md && grep -qE '^\| linux-aarch64 .*resolved' docs/core/linux-wheels.md && grep -qi 'deferred' docs/core/linux-wheels.md` → exit 0)
- [ ] Given the previous repo
      When work ends
      Then nothing changed there
      (assert: `test "$(git -C /Users/alec/source/varde rev-parse HEAD; git -C /Users/alec/source/varde status --porcelain -- clis)" = "$(cat /Users/alec/source/varde-py/docs/toz-port/baseline-varde.txt)"` → exit 0)

## Progress

## Related

- Gate: `/Users/alec/source/agent-memory/projects/varde-py/working/plans/2026-10-14-varde-python-port/notes/gate-report.md` (condition 3 owner), `/Users/alec/source/agent-memory/projects/varde-py/working/plans/2026-10-14-varde-python-port/notes/gate-decision-2026-10-14.md`, `/Users/alec/source/agent-memory/projects/varde-py/working/plans/2026-10-14-varde-python-port/notes/gate-approval.md`
- Inventory and graph: `/Users/alec/source/agent-memory/projects/varde-py/working/plans/2026-10-14-varde-python-port/notes/port-plan.md`
- /Users/alec/source/varde-py/python/varde-toz/src/varde_toz/_core/ (interim shim)
- /Users/alec/source/varde-py/spikes/packaging/ (multi-package layout, entry-point discovery)
- /Users/alec/source/varde/clis/varde-core, contracts package, varde/tests/dependency_rules.rs
