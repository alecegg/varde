---
type: review
verdict: approved
reviewer: varde-reviewer (report-only), session 2cd260e6-5a07-45e2-aaf5-56e4b8db868b
base: b97b26af2dc28f2567d952ec0f1b0db8dc7f256a
head: bb743cefa8036de3f8e96fbac47a88884f5c472e
---

# Review: sample-core

Scope: `b97b26af..8b8ae202` in `worktree/sample-core-post`. Excluded: `python/varde-code/tests/fixtures/**` (blobs; only opened through the reader), `uv.lock` (read for wheel evidence), `spikes/prototype`. Reference implementation compared: `/Users/alec/source/varde/clis/{varde-core,learn}` (read-only).

## Categories

| Category | Status | Findings |
|---|---|---|
| CORRECTNESS | complete | 9 |
| ARCHITECTURE | complete | 3 |
| API-DESIGN | complete | 4 |
| Spec axis (plan.md, acceptance criteria) | complete | 3 |

## Plan assert results

Run from the post worktree with `uv run`.

| Assert | Result |
|---|---|
| `uv sync --all-packages --frozen` plus no `tree-sitter<0.26` grep | pass |
| `test_dependency_rules.py` | pass (12) |
| `test_api_contract.py` | pass (2) |
| `test_skeletons.py` | pass (2) |
| `test suite/tests/` | fails in the sandbox (`mkdir /tmp/varde-toz-c-*` denied by the hard-coded `dir="/tmp"`, see CORRECTNESS-006); passes (3) outside it |
| `test_seams.py` | pass (3) |
| `linux-wheels.md` greps | pass, but see SPEC-002 |
| previous repo untouched (`baseline-varde.txt`) | pass |
| Whole `python/` suite | `varde-code`, `varde-core`, `contracts package`, `varde-learn`: 84 tests; 2 `test_model_parse` tests failed in the sandbox (tree-sitter-language-pack cache lock) and passed outside it. A top-level `pytest python` run aborts at collection: basename clash on `python/varde-toz/tests/test_fixtures.py` vs `python/varde-code/tests/fixtures/test_fixtures.py` |

`python -m test suite compare --module toz` prints `cases: 66`, then `groups:`, then `mismatches: 0`. 66 is correct. The plan's "65" is stale and API.md already says so.

## Decisions asked for in the brief

- **Shim vs core when the last command is removed.** Core is right. previous (`json_order.rs` `edit_event`) does `hooks.shift_remove(event)` when the entries are empty. That leaves `"hooks": {}` unless `prune_empty_hooks`. The shim's `"Start": []` is wrong. `API-extra.md` should say the shim is the wrong side and toz-adopt must expect `"hooks": {}`.
- **`compare` output.** It prints one `cases: N`, then `groups:`, then `mismatches:`. Pass.
- **Seeded dependency-rule violations.** The 10 seeded cases all fail the checker. The weaknesses are in ARCH-003.
- **Committed fixture never written.** The reader opens it with `mode=ro` and copies it with `backup`. The journal mode is `delete` (header bytes `01 01`), so there are no `-wal`/`-shm` side files. `git status` is clean after the tests. Pass.
- **Production never reads the freshness flag.** Only `testing/previous_index.py` references `FRESHNESS_CHECKS`. A test asserts this. Pass.

## [CORRECTNESS-001] Envelope drops `envelope_version`

**Severity:** high
**Status:** fixed (verified at 3ba0837)
**Location:** `python/varde-core/src/varde_core/envelope.py:7`

### Summary

previous `envelope()` emits `schema_version, envelope_version, ok, outcome, data, meta` (`varde-core/src/envelope.rs`: "Value of both `schema_version` and `envelope_version`"). Python emits five keys and has no `envelope_version`. The plan text and API.md copied the same five-key order. The plan constraint "JSON key order identical to previous" and the previous source disagree with both.

### Solutions

1. **Add `"envelope_version": ENVELOPE_VERSION` after `schema_version` in `_envelope`**
   Update API.md and the plan's key-order line to six keys, and add a key-order test. Workflow and learn print this envelope. Without the key, the first wave-1 plan that emits it produces diverging JSON, and its behavior check golden will not match.

## [CORRECTNESS-002] json_order re-indents untouched raw values on every edit, so edits are not idempotent

**Severity:** high
**Status:** fixed (verified at 3ba0837)
**Location:** `python/varde-core/src/varde_core/json_order.py:96`

### Summary

previous serializes untouched `RawValue`s verbatim. `_dump_raw_object` does `v.replace("\n", "\n" + child)` on the raw slices of the top-level fields and of untouched hook events, so every edit shifts multi-line foreign content.

Reproduced with `{"a":{\n      "x": 1\n},"hooks":{"Stop":[{\n   "command":"k"\n}], ...}}`. After `append_entry`, the `"x": 1` line moves 2 columns. After a second `append_entry`, it moves 10 columns more. The same happens to the foreign `Stop` entry.

The previous test "keeps nested user indentation stable" only passes in Python because the edited event is regenerated. That is why 8 ported tests missed this. In practice, running install or uninstall repeatedly on a user's `settings.json` makes any hand-indented section drift.

### Solutions

1. **Emit raw slices verbatim**
   Join the root and hooks fields with the fixed previous indentation and never re-indent a raw slice. Add a test that applies two successive edits to a multi-line document and asserts the untouched text is byte-identical.

## [CORRECTNESS-003] json_order accepts malformed documents previous rejects, and overwrites non-array events

**Severity:** medium
**Status:** fixed (verified at 3ba0837)
**Location:** `python/varde-core/src/varde_core/json_order.py:17`, `:190`

### Summary

All four cases below were reproduced.

- Truncated JSON (`{"hooks": `) raises `IndexError` from the hand-rolled `_decode`. previous returns a `serde_json::Error`, and `append_entry` has no Python-visible error type. Callers cannot catch it as `ValueError`.
- `{"hooks":[1]}` raises `AttributeError`.
- `{"hooks":{"E":3}}` plus `append_entry(..., "E", ...)` silently replaces the non-array with a new array (data loss). previous errors.
- `{"hooks":{"E":null}}` plus remove returns the document unchanged. previous errors.

`_decode` also does not reject trailing garbage or invalid tokens as `json` would.

### Solutions

1. **Parse with `json.loads` for validation, then locate spans**
   Type-check `hooks` (object) and the event (array), and raise `ValueError` on every failure. Add negative tests.

## [CORRECTNESS-004] jsonio prints positive exponents as `1e+21`; serde_json prints `1e21`

**Severity:** high
**Status:** fixed (verified at 3ba0837)
**Location:** `python/varde-core/src/varde_core/jsonio.py:13`

### Summary

`_float` adds `+` for non-negative exponents. serde_json (ryu) emits `1e21` and `1.2345678901234568e17`. Reproduced: `dumps([1e21, 1e16, 1.5e300])` gives `[1e+21,1e+16,1.5e+300]`. The only exponent test uses `1e-7`, which passes. Large floats in any ported JSON output (stats, scores) will not byte-match previous. `json_order._dump` has the same issue through `json.dumps` (low).

### Solutions

1. **Drop the `+` from the exponent in `_float`**
   Add vectors for 1e16, 1e21, 1e-5 and 1.7976931348623157e308. Route `json_order._dump` scalars through `jsonio`.

## [CORRECTNESS-005] text_audit regexes are quadratic in Python and linear in previous

**Severity:** medium
**Status:** fixed (verified at 3ba0837)
**Location:** `python/varde-core/src/varde_core/text_audit.py:49`

### Summary

`_SERIES` backtracks. Measured on a single paragraph line:

| Input | `audit` time |
|---|---|
| 20k chars of `A` | 3.2 s |
| 20k chars of `word ` | 1.6 s |
| 100k chars | 79 s |
| `"sk-" + "a"*50000` | 20 s |
| 40k chars of `a-` | 11 s |

previous's `regex` is linear. The redactor's builtins were fast on the same strings (`redact`: 1.3 s worst case, on the `a-` x 20k input). Agent docs are short, but `varde learn check`/`workflow lint` read arbitrary files, and a generated or minified `.md` hangs the CLI.

### Solutions

1. **Rewrite `_SERIES` as a linear scan**
   Split on `[,;:.!?()]` boundaries and count items, or cap the unit length before running the regex. Add a timing guard test.

## [CORRECTNESS-006] Behavior check `gen` runs the reference implementation with the user's real environment

**Severity:** high
**Status:** fixed (verified at 3ba0837)
**Location:** `python/test suite/src/test suite/cli.py:146`

### Summary

`_generate` runs `[reference implementation, *args]` with the inherited `HOME`/`VARDE_CONFIG_DIR`/learn/toz store variables, cwd set to a bare temp dir. `_compare` isolates all of these. A learn, workflow, toz or code golden run therefore mutates the real stores (friction items, plan files, toz store, index), and the goldens depend on the machine's state. It also does not run `setup` cases, serve the fixtures HTTP server, or lay out fixtures, so it cannot regenerate the committed toz goldens, which compare relied on.

A timeout also crashes: `TimeoutExpired.stdout` is bytes, so `json.dumps` raises `TypeError` (`:151`).

### Solutions

1. **Share one isolated environment builder between `gen` and `compare`**
   Use a temp `HOME`/`VARDE_CONFIG_DIR`/store dirs, run `setup` cases, and decode timeout bytes. Add a stub-reference implementation test that asserts `HOME` is not inherited.

## [CORRECTNESS-007] Redactor: regex dialect and literal-ordering differences from previous

**Severity:** low
**Status:** fixed (verified at 3ba0837)
**Location:** `python/varde-core/src/varde_core/redact/__init__.py:99`

### Summary

The builtin patterns match previous (checked all ten). The engine logic matches `selected()` exactly, including span extension and the empty-match rule. Remaining deviations:

- User patterns compile with Python `re`. previous-only syntax (`\p{L}`, `[[:alpha:]]`) raises `ValueError`. Python-only syntax (lookaround, backreferences) is accepted where previous says invalid. Python permits an empty match adjacent to the previous match; previous's `find_iter` does not.
- Literal values are sorted by code-point length (`-len(value.value)`) where previous uses byte length. Order, and so precedence, differs for non-ASCII secrets of equal char length.
- Surrogate-escaped env values (non-UTF-8 bytes) raise `UnicodeEncodeError` in `redact_spans`. previous skips them in `from_environment`.
- `values._is_common_literal` uses `float()`, which accepts `1_000` and surrounding whitespace; previous `parse::<f64>` rejects them.
- `from_dotenv` uses `splitlines()`, which also splits on `\x0b`, `\x0c`, `\x1c-\x1e`, `\x85`, U+2028 and U+2029. previous `lines()` splits only on `\n` and `\r\n`.

### Solutions

1. **Fix the cheap items; document the regex dialect**
   Sort by `len(value.encode())`. Skip values that fail `encode()` in `from_environment`. Use `split("\n")` with `\r` stripping. Reject lookaround and backreferences, or document the Python-`re` dialect for user patterns in API.md. Add vectors for each.

## [CORRECTNESS-008] write_meter.scaled accepts inputs previous rejects

**Severity:** low
**Status:** fixed (verified at 3ba0837)
**Location:** `python/varde-core/src/varde_core/write_meter.py:56`

### Summary

`float(" 1_0 ")` is accepted, so `VARDE_WRITE_BUDGET_SCALE=1_0` scales by 10. previous ignores it and uses 1.0. The macOS offset (index 19 of `rusage_info_v4`) and flavor 4 are correct.

### Solutions

1. **Validate with a regex before `float()`**
   Reject underscores and whitespace.

## [CORRECTNESS-009] TestIndexService.check_fresh compares against every file under the root

**Severity:** low
**Status:** fixed (verified at 3ba0837)
**Location:** `python/varde-code/src/varde_code/testing/previous_index.py:98`

### Summary

`root.rglob("*")` includes `.git/**`, ignored and untracked files. For any real fixture checkout that has a `.git` directory or extra files, the set never equals the indexed set, so `check_fresh` returns False. The test only passes because its tmp checkout has one file. The seam test also never opens the committed `indexes/*.db` through `TestIndexService`. `test_fixtures.py` opens one with `open_previous_index`, but nothing builds a graph from SQL or postcard, although the plan acceptance says "builds the graph from SQL or the optional postcard decoder". Wave-1 plans must write that themselves.

### Solutions

1. **Compare against the walker's listing**
   Use the `FileWalker` seam or `git ls-files` for the current set. Add a `check_fresh` test on the committed fixture repos, and either add a SQL graph loader to the seam or state that code-query owns it.

## [ARCH-001] `tree-sitter-language-pack` downloads grammars at runtime

**Severity:** high
**Status:** fixed (verified at 3ba0837)
**Location:** `python/varde-code/src/varde_code/parse.py:56`

### Summary

`get_language()` in `tree-sitter-language-pack==1.22.1` pulls grammar shared libraries into `~/Library/Caches/tree-sitter-language-pack/v1.22.1`. This machine has 374 libs and 535 MB there; the installed wheel is 4.8 MB. In the sandbox the call fails with `CacheLockError: open lock file .../.download.lock: Operation not permitted`.

So `TreeSitterParser` needs network or a pre-warmed writable cache on the first parse of each language. That breaks offline CI, read-only or sandboxed hosts, and hash-pinned installs, and the extractor behavior check group-B languages. `versions.md`/`linux-wheels.md` say nothing about it.

### Solutions

1. **Pin and prefetch**
   Use the pack's init or download API to prefetch the grammar set, point the cache at a configurable dir, and document it. Alternatively use per-grammar wheels (`tree-sitter-python`, etc.) as the plan's Tech-choices line says ("newest tree-sitter and grammar wheels").
2. **Add an offline guard test**
   The guard should fail with a clear message when the cache is unwritable.

## [ARCH-002] Stub modules violate the `Module` contract

**Severity:** medium
**Status:** fixed (verified at 3ba0837)
**Location:** `python/varde-code/src/varde_code/module.py:1` (same file in 5 sibling packages)

### Summary

`old_contracts.module.Module` requires `name: str`. The six skeleton `register()` functions return the module object, which has no `name` (checked: all six entry points print `<NO NAME>`). `run` writes to `getattr(io, "err", None)`, but `Io` has no `err`, so the message goes to stdout and `run([], None)` prints nothing. `test_skeletons.py` checks `run` and `help` only, so the gap passes. The app plan, which discovers modules by `name`, breaks on first use.

### Solutions

1. **Return a small stub class instance**
   Give it `name`, `run` writing to stderr, and `help(path)`. Assert `name == entry_point.name` in the test.

## [ARCH-003] Dependency-rules test has detection gaps

**Severity:** low
**Status:** fixed (verified at 3ba0837)
**Location:** `python/varde-core/tests/test_dependency_rules.py:62`

### Summary

All 5 dependency and 5 import seeds do fail the checker. Gaps that let a real violation through:

- Requirement names are split on `<`, `>`, `=` only. `varde-code~=1`, `varde-code[x]`, and `varde-code; marker` yield names that never match, so the dependency edge is silently dropped.
- `optional-dependencies` and `dependency-groups` are never read. That is where the allowed "dev dependency" on behavior check would live, and so also where an unallowed one would hide.
- The test-import branch has no seeded violation. The "behavior check at runtime" branch is dead: every case is already rejected by the family rule.
- The APP and BEHAVIOR rules have no seeds.

### Solutions

1. **Parse requirements with `packaging.requirements.Requirement`**
   Scan the optional and group tables. Add seeds for each uncovered rule.

## [API-001] API.md says the Signatures-fixed section is not importable, and the contract test only does `hasattr`

**Severity:** medium
**Status:** fixed (verified at 3ba0837)
**Location:** `python/varde-core/API.md:118`, `python/varde-core/tests/test_api_contract.py:19`

### Summary

- `### Signatures fixed, implemented in api-complete` still says the redact, text_audit, skill_relations and learn names are "not importable yet". They are importable now.
- The extra test covers only module attributes, not `values.collect/from_dotenv/from_environment`.
- The main test's row regex `\| \`mod\` \| \`name\` \|` skips the `varde_code.graph_model` row, which has no separate name cell (`Graph(...)` is in the first backticked cell after the module). `Graph` is never import-checked by the plan's contract test.
- Neither test checks signatures, only presence.

### Solutions

1. **Merge the extra rows into the table and fix the Graph row**
   Move the post-freeze names into the main table. Add `inspect.signature` checks for the documented parameter lists.

## [API-002] `EntityKind.as_i64`/`as_str` are properties; API.md documents them as methods

**Severity:** medium
**Status:** fixed (verified at 3ba0837)
**Location:** `python/varde-code/src/varde_code/model.py:32`

### Summary

The enum names and values match previous, as does `span_of`. `as_i64` and `as_str` (also on `SymbolKind` and `EdgeKind`) are `@property`. previous has methods, and API.md lists them like methods. A wave-1 plan that writes `kind.as_str()` gets `TypeError: 'str' object is not callable`.

### Solutions

1. **Make them methods, or document the property form in API.md**
   Do this before more plans import them.

## [API-003] `RelationError` collapses previous's three variants

**Severity:** low
**Status:** fixed (verified at 3ba0837)
**Location:** `python/varde-core/src/varde_core/skill_relations.py:19`

### Summary

`RelationError` is one class with `.kind` and `.detail`. previous matches on `Malformed`, `Unknown` and `Cycle`. The Display text matches. `parse` and `closure` otherwise port faithfully (verified line by line). `lines()` becomes `splitlines()`, a minor edge. API.md does not document the `.kind` strings.

### Solutions

1. **Document `.kind` and `.detail` in API.md**
   The values are `malformed`, `unknown` and `cycle`.

## [API-004] Behavior check kit hard-codes toz

**Severity:** high
**Status:** fixed (verified at 3ba0837)
**Location:** `python/test suite/src/test suite/cli.py:59`

### Summary

The plan says the kit "generalizes" the toz harness for module plans. `_compare` still:

- builds toz-specific fixtures, a toz `config.toml` and `VARDE_TOZ_CONFIG_DIR`;
- runs `python -m varde_<module>.cli`, which is missing for every module except toz (skeletons expose `module.py`, and `md-core` maps to `varde_md-core`);
- uses `dir="/tmp"`, which fails under the sandbox and on hosts without /tmp;
- defines `ROOT = parents[4]`, which assumes an editable source checkout;
- hard-codes `query.search`/`query.list` in `order_setup_cases`;
- accepts `--all` and ignores it.

The behavior check test exercises only `--module toz --case help.capture`. Every wave-1 module plan (learn, workflow, md-core, doc, code) will hit this on its first `compare`.

### Solutions

1. **Make module setup pluggable**
   Add a per-module `behavior check/harness.py` hook or a manifest key for env, fixtures and command, defaulting to `Module.run` through the entry point. Use `tempfile.gettempdir()`. Wire `--all`. Add a non-toz sample-module test, plus one that asserts the full toz run prints `cases: 66`.

## [SPEC-001] Stub manifest has no files for five plans

**Severity:** low
**Status:** deferred (low; manifest note not added, ownership by glob unchanged)
**Location:** `docs/core/stub-manifest.json`

### Summary

`code-rules`, `code-langs`, `code-gate`, `app-setup` and `app-glue` map to `[]`. The plan says the skeleton creates every stub file per plan. The ownership table covers them by `owns` globs, so nothing breaks today. The `test_every_stub_manifest_file_exists` assertion is vacuous for those plans. Check that those plans' task files really need no pre-created file, or state that in API.md.

### Solutions

1. **Record "no stub files, ownership by glob" for those five plans**
   Put the note in the manifest or in API.md.

## [SPEC-002] linux-wheels.md: the `resolved` rows are honest but prove less than the plan's goal

**Severity:** medium
**Status:** fixed (verified at 3ba0837)
**Location:** `docs/core/linux-wheels.md:9`

### Summary

The assert greps pass, and the doc states that the compile ran without `--only-binary`, so `resolved` allows an sdist. I reproduced the two wheel-only failures with uv 0.12.19 and `--only-binary :all:`:

- **`tree-sitter-language-pack==1.22.1` on Linux.** The doc calls this an unexplained "wheel-artifact limitation". It is not. The Linux wheels are `cp310-abi3-manylinux_2_34_{x86_64,aarch64}` (see `uv.lock`). With the default `--python-platform x86_64-unknown-linux-gnu` (glibc 2.28 baseline) there is no match. With `x86_64-manylinux_2_34` and `aarch64-manylinux_2_34` the wheel-only compile resolves. Real risk: Linux hosts with glibc below 2.34 (RHEL/Alma 8, Ubuntu 20.04, Debian 11) get the sdist, which needs a previous toolchain. Ubuntu 22.04+ and Debian 12+ are fine. The doc should state the glibc 2.34 floor.
- **`watchdog==6.0.0` on macOS arm64.** Confirmed: `uv.lock` lists only Linux and Windows wheels, so macOS gets the sdist and compiles the FSEvents extension (needs Xcode CLT). Treat as a real risk on the primary platform. Options: allow a pure-Python fallback, or pin a release with a macOS wheel. I did not verify other releases' wheel sets.

The plan criterion was "all three platforms resolve", so the rows pass. The stronger goal, an installable wheel set on each platform, is not met. The doc should split the table into a normal-resolve column and a wheel-only column, with the 2_34 note.

### Solutions

1. **Add a wheel-only column probed at `manylinux_2_34`, and record the glibc floor**
   Record the watchdog macOS sdist as a known risk.
2. **Pick the watchdog fallback**
   Handle the missing observer at runtime, or choose a different release.

## [SPEC-003] Behavior check acceptance asserts the stale case count only indirectly

**Severity:** low
**Status:** fixed (bb743ce: `test_toz_full_golden_set_compares_cleanly`)
**Location:** `python/test suite/tests/test_behavior check.py:33`

### Summary

The plan asserted "toz goldens compare with exactly 65 cases". The test compares one case (`help.capture`). Nothing in the test run checks that the 66 committed toz cases compare clean. I ran it by hand: `cases: 66`, `mismatches: 0`.

### Solutions

1. **Add a full toz compare with `--min-cases 66`**
   Use the real golden set, and update the plan text to 66.

## Not found (checked, no defect)

- `paths.py` and `sqlite.py`: match `paths.rs` (HOME precedence, macOS data dir, empty variables) and `sqlite.rs`. `constants.py` and `toz_instruction_block` match.
- `write_meter` macOS struct offset and flavor, and Linux `wchar:`.
- `redact` engine core and the ten builtin patterns, including byte-offset spans.
- `text_audit` scan and layout logic, thresholds, hint strings and `expand_skill_dir`, except for CORRECTNESS-005.
- `skill_relations` parse and closure order.
- `varde_learn.redact.apply`, `errors.py` and codes match `error.rs`. `resolve_store_dir` matches `store.rs` for env, TOML and `~` handling. previous's custom `resolve_directory` symlink walk was not compared; Python uses `Path.resolve()`.
- `EntityKind` order and values match `model.rs`. `Parser` protocol and tree-sitter 0.26.0 / ast-grep-py 0.50.0 are the newest releases per `versions.md`. I did not re-verify PyPI.
- `pattern_match` and `toz_bridge` were read only for import structure. Their logic was not diffed against previous; code-query/code-rules own that fidelity.

## Re-review at 3ba0837

Scope: fixes for the named findings only (`8b8ae20..3ba0837`). Checks run with `uv run`: 116 tests pass outside the sandbox (inside it, 3 fail on a locked grammar cache and local port binding, both sandbox limits). `python -m test suite compare --module toz` prints `cases: 66`, `mismatches: 0`.

Repros re-run: `envelope` now emits six keys. Two successive `append_entry` calls leave the multi-line `"x": 1` and the foreign `Stop` entry byte-identical. Truncated JSON, `{"hooks":[1]}`, non-array events, `null` events and trailing garbage all raise `ValueError`. `jsonio.dumps` prints `1e21`, `1e16`, `1.5e300`. `audit` on the 20k to 180k char inputs now takes at most 0.04 s. `VARDE_WRITE_BUDGET_SCALE=1_0` is ignored. ARCH-001 is handled by `VARDE_TREE_SITTER_CACHE_DIR`, a writability guard with a clear error and a guard test, and `docs/core/parser-cache.md`.

| Finding | Result |
|---|---|
| CORRECTNESS-001..009 | fixed |
| ARCH-001..003 | fixed |
| API-001..004 | fixed (API-004: pluggable harness, entry-point default, `--all` wired, non-toz test) |
| SPEC-002 | fixed (wheel-only column and glibc 2.34 floor recorded; watchdog macOS sdist listed as a risk, not removed) |
| SPEC-001 | deferred (low) |
| SPEC-003 | open (low): no full 66-case compare in the test suite |

## New findings

### [REREVIEW-001] `gen` runs setup cases through the Python module and gives the reference implementation `python_args`

**Severity:** high
**Status:** fixed (bb743ce)
**Location:** `python/test suite/src/test suite/cli.py:205` and `:216`

#### Summary

The CORRECTNESS-006 fix for `_generate` has two regressions.

- Each case's `setup` list runs twice. First `run_case(..., command_for(args.module), ...)` runs the setup through the Python module's entry point against the reference implementation's isolated state. Then the loop below runs it through the reference implementation. For a module without a registered entry point, `gen` crashes: `gen --module sample --reference implementation X --cases c.json` with any case that has `setup` raises `ValueError: no varde.modules entry point registered for 'sample'` (reproduced). For a registered stub it silently runs the stub instead.
- The reference implementation command uses `case.get("python_args", case["args"])`. `python_args` are the Python CLI's arguments. The previous reference implementation must get `case["args"]`. Five toz cases define `python_args`, so regenerating them drives the reference implementation with the wrong argv.

The new `gen` test has no `setup` case and no `python_args`, so it passes.

#### Solutions

1. **Delete the Python setup loop and pass `case["args"]` to the reference implementation**
   Keep the reference implementation-driven setup loop. Add a stub-reference implementation test with a `setup` case and a `python_args` case that asserts the reference implementation log shows setup once and the previous args.

### [REREVIEW-002] Smaller notes (non-blocking)

- `text_audit._series_candidates` checks only the first `and`/`or` in a punctuation run and returns the whole run, so the inline-list count can differ from the old regex in rare cases. Add vectors against previous output.
- The flag selects every case; it does not define a separate mode.
- `toz_harness.TOZ_FIXTURES` assumes `parents[4]` of the installed file (same editable-checkout assumption that `ROOT` no longer makes).

## Re-check at bb743ce

Scope: REREVIEW-001 and SPEC-003 only (diff `3ba0837..bb743ce`, two files). Checked by reading; I could not run the tests because the harness denied test execution in this session.

- REREVIEW-001 fixed. `cli.py:206-211` no longer calls `run_case` or the Python module for setup; each `setup` id runs once through `args.reference implementation` with the setup case's `args`. The target command is `[*command, *case["args"]]` with `command = [str(args.reference implementation)]`, so `python_args` no longer reach the reference implementation.
- New test `test_generation_uses_reference implementation_setup_and_previous_args` has a `setup` case and a target with `python_args`. It asserts the reference implementation log is exactly `[["setup-previous"], ["previous-args"]]` and the golden stdout is `previous-args`. On the old code the module `sample` has no entry point, so the Python setup loop raised `ValueError`, and `python-args` would have reached the reference implementation. The test would fail there.
- SPEC-003 fixed. `test_toz_full_golden_set_compares_cleanly` runs `compare --module toz --min-cases 66` and asserts `cases: 66` and `mismatches: 0`.
- SPEC-001 stays deferred (low). REREVIEW-002 notes stay non-blocking.

## Verdict

approved. No critical or high finding is open. REREVIEW-001 and SPEC-003 are fixed (verified by reading, not by running tests); SPEC-001 is deferred (low).
