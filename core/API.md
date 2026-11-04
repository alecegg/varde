# Wave-1 Python API freeze

Historical working-document references point to the archive index at `/Users/alec/source/agent-memory/projects/varde-py/working/plans/2026-10-14-varde-python-port/evidence/README.md`; the ownership inventory points to archived copies or current relocated paths.

This document freezes imports for the initial code and module plans. Use only the names marked **available** below. The signatures describe the integrated Python source as of this commit.

## Shared runtime and test commands

- Run tests from the workspace root with `uv run pytest ...`; the root dev group provides pytest.
- The root workspace includes the nine module directories (core, toz, code, doc, learn, knowledge, workflow, dev, and app). Each package appends its own third-party dependencies only to its own `<module>/pyproject.toml`.
- When integrating a branch that changes package dependencies, rebase on `main` and run `uv lock` to regenerate `uv.lock`. Never hand-merge `uv.lock`.
- The dependency-rules test checks project dependencies from package `pyproject.toml` files and package imports from Python ASTs. It seeds each restriction in a temporary source copy and requires the rule checker to reject it.

## Available imports

Each row is an importable module attribute used by wave-1 plans. The contract column is the supported behavior/signature.

| Module | Name | Signature / contract |
|---|---|---|
| `varde_core.envelope` | `ENVELOPE_VERSION` | Integer `1`; envelope version. |
| `varde_core.envelope` | `success` | `success(data: object, meta: object) -> dict[str, object]`; returns keys in order `schema_version`, `envelope_version`, `ok`, `outcome`, `data`, `meta`. |
| `varde_core.envelope` | `negative_result` | `negative_result(code: str, message: str, details: object, meta: object) -> dict[str, object]`; negative-result envelope. |
| `varde_core.envelope` | `tool_error` | `tool_error(code: str, message: str) -> dict[str, object]`; tool-error envelope. |
| `varde_core.jsonio` | `dumps` | `dumps(value: object) -> str`; compact serde-compatible JSON, preserving insertion order and non-ASCII text. |
| `varde_core.jsonio` | `dumps_pretty` | `dumps_pretty(value: object) -> str`; two-space pretty JSON, preserving insertion order and non-ASCII text. |
| `varde_core.yamlio` | `YamlSyntaxError` | `ValueError` for invalid YAML, with compact source-independent error text. |
| `varde_core.yamlio` | `load_yaml` | `load_yaml(text: str) -> Any`; loads YAML with YAML 1.2 core scalar rules. |
| `varde_core.yamlio` | `dump_yaml` | `dump_yaml(value: Any) -> str`; serializes YAML with stable serde-compatible scalar layout. |
| `varde_core.frontmatter` | `FrontmatterError` | `ValueError` for invalid markdown frontmatter. |
| `varde_core.frontmatter` | `parse` | `parse(data: bytes | str) -> tuple[dict[str, Any], str]`; parses YAML mapping frontmatter and markdown body. |
| `varde_core.frontmatter` | `serialize` | `serialize(frontmatter: dict[str, Any], body: str) -> str`; serializes frontmatter and markdown body. |
| `varde_core.frontmatter` | `frontmatter_bounds` | `frontmatter_bounds(data: bytes) -> tuple[int, int]`; returns the byte bounds of frontmatter content. |
| `varde_core.paths` | `varde_config_dir` | `varde_config_dir() -> pathlib.Path`; resolves VARDE_CONFIG_DIR, XDG_CONFIG_HOME, then home config. |
| `varde_core.paths` | `data_dir` | `data_dir() -> pathlib.Path | None`; resolves platform data directory. |
| `varde_core.sqlite` | `configure_connection` | `configure_connection(connection: Any) -> None`; applies busy timeout, WAL, NORMAL sync, and foreign keys. |
| `varde_core.utc` | `as_utc` | `as_utc(value: datetime) -> datetime`; treats naive datetimes as UTC and converts aware values to UTC. |
| `varde_core.utc` | `parse_datetime` | `parse_datetime(value: Any) -> datetime | None`; parses ISO timestamps, returning `None` for invalid or non-string values and preserving aware offsets. |
| `varde_core.utc` | `utc_day` | `utc_day(value: datetime) -> date`; returns the calendar day in UTC. |
| `varde_core.utc` | `window_start` | `window_start(value: datetime, *, days: int = 0, hours: int = 0) -> datetime`; returns a UTC-normalized look-back start. |
| `varde_core.utc` | `in_window` | `in_window(value: datetime, start: datetime, end: datetime) -> bool`; checks an inclusive UTC-normalized interval. |
| `varde_core.constants` | `TOZ_BLOCK_START` | Toz note block opening marker. |
| `varde_core.constants` | `TOZ_BLOCK_END` | Toz note block closing marker. |
| `varde_core.constants` | `TOZ_NOTE` | Shared Toz instructions text. |
| `varde_core.constants` | `LEARN_NOTE` | Shared learn friction instructions text. |
| `varde_core.constants` | `HOW_NOTE` | Shared text explaining `varde learn how` topics, placed in the learn block. |
| `varde_core.constants` | `toz_instruction_block` | `toz_instruction_block(template: str) -> str`; extracts the marked block and substitutes the shared Toz note; raises ValueError if markers are missing. |
| `varde_core.io` | `Io` | Frozen optional capabilities: `impact` and `capture`, each `object | None` and defaulting to `None`. |
| `varde_core.module` | `Module` | Protocol: `name: str`; `run(self, argv: list[str], io: Io) -> int`; `help(self, path: str) -> str`. Stub entry points return concrete `Module` objects with a `name`. |
| `varde_code` | `CaptureInput` | Text or item-list input with `.from_text(text)` and `.from_items(items)` constructors. |
| `varde_code` | `OutputCapture` | Protocol: `capture(self, input: CaptureInput, source: str, label: str) -> str | None`. |
| `varde_code.model` | `EntityKind` | `FUNCTION=0`, `CLASS=1`, `INTERFACE=2`, `VARIABLE=3`, `PARAMETER=4`, `EXPORT=5`, `CALL=6`, `LITERAL=7`, `MEMBER_ACCESS=8`, `IMPORT=9`, `CATCH=10`, `THROW=11`, `CONTROL_FLOW=12`, `ROUTE=13`, `RESPONSE=14`, `EXTENDS=15`, `IMPLEMENTS=16`, `DECORATOR=17`, `TYPE_REF=18`, `CALLABLE_BOUNDARY=19`; methods `as_i64(self) -> int`, `as_str(self) -> str`, `from_i64(value: int) -> EntityKind | None`. |
| `varde_code.model` | `SymbolKind` | `BINDING=0`, `REFERENCE=1`; methods `as_i64(self) -> int`, `as_str(self) -> str`, `from_i64(value: int) -> SymbolKind | None`. |
| `varde_code.model` | `EdgeKind` | `CALL=0`, `IMPORT=1`, `EXTENDS=2`, `IMPLEMENTS=3`; methods `as_i64(self) -> int`, `as_str(self) -> str`, `from_i64(value: int) -> EdgeKind | None`. |
| `varde_code.model` | `RoleTag` | String enum with `ROUTE_HANDLER`, `PAGE_COMPONENT`, `CLI_COMMAND`, `BACKGROUND_JOB`, `EVENT_LISTENER`, `MIDDLEWARE`, `PROCESS_MAIN`. |
| `varde_code.model` | `Span` | `Span(start_byte: int, end_byte: int, start_line: int, start_col: int, end_line: int, end_col: int)`; lines are 1-based, columns 0-based. |
| `varde_code.model` | `FileMeta` | `FileMeta(mtime: int, size: int, content_hash: str)`. |
| `varde_code.model` | `Entity` | `Entity(kind: EntityKind, name: str, file_id: int, span: Span, enclosing_function: str | None = None, method: str | None = None, path: str | None = None, status: str | None = None, body_shape: str | None = None, body_minhash: list[int] | None = None, is_async: bool | None = None, is_test: bool = False, owner_type: str | None = None)`; mutable extracted entity. |
| `varde_code.model` | `Symbol` | `Symbol(kind: SymbolKind, name: str, file_id: int, span: Span)`; binding or reference. |
| `varde_code.model` | `Diagnostic` | `Diagnostic(file_id: int | None, path: str, message: str, severity: str)`. |
| `varde_code.model` | `ExtractOutput` | `ExtractOutput(entities: list[Entity] = [], symbols: list[Symbol] = [], diagnostics: list[Diagnostic] = [], files: list[str] = [], file_meta: list[FileMeta] = [])`; mutable extraction result lists. |
| `varde_code.model` | `Community` | `Community(id: int, members: list[str])`; frozen record. |
| `varde_code.model` | `saturating_u32` | `saturating_u32(value: int) -> int`; clamps to unsigned 32-bit range. |
| `varde_code.model` | `span_of` | `span_of(node: object) -> Span`; converts tree-sitter byte and point offsets to Rust-compatible coordinates. |
| `varde_code.parse` | `EXTENSION_LANGUAGES` | `dict[str, str]`; maps supported file extensions to canonical language names. |
| `varde_code.parse` | `ALIASES` | `dict[str, str]`; maps aliases such as `ts` and `c++` to canonical names. |
| `varde_code.parse` | `SUPPORTED_LANGUAGES` | Tuple of unique names: typescript, tsx, javascript, c, cpp, go, java, csharp, kotlin, swift, python, ruby, php, lua, scala, dart, elixir, solidity, haskell, bash, rust. |
| `varde_code.parse` | `Parser` | Protocol: `parse(self, language: str, source: str) -> ParsedFile`. |
| `varde_code.parse` | `ParsedFile` | `ParsedFile(lang: str, tree: object, source: bytes, masked_preprocessor: bool = False)`; `.root -> Node`, `.has_error() -> bool`. |
| `varde_code.parse` | `TreeSitterParser` | `TreeSitterParser()` uses `tree-sitter-language-pack`; parser cache location and configuration are documented in `/Users/alec/source/agent-memory/projects/varde-py/working/plans/2026-10-14-varde-python-port/evidence/core/parser-cache.md`; `.parse(language: str, source: str) -> ParsedFile`. |
| `varde_code.parse` | `language_for_extension` | `language_for_extension(extension: str) -> str | None`. |
| `varde_code.parse` | `language_for_path` | `language_for_path(path: str | Path) -> str | None`. |
| `varde_code.parse` | `language_from_name` | `language_from_name(name: str) -> str | None`. |
| `varde_code.parse` | `language_name` | `language_name(language: str) -> str`; raises ValueError if unsupported. |
| `varde_code.parse` | `parse_source` | `parse_source(language: str, source: str, parser: Parser | None = None) -> ParsedFile`. |
| `varde_code.parse` | `parse_source_for_path` | `parse_source_for_path(language: str, path: str | Path, source: str, parser: Parser | None = None) -> ParsedFile`. |
| `varde_code.parse` | `parse_file` | `parse_file(path: str | Path, parser: Parser | None = None) -> ParsedFile | None`. |
| `varde_code.toz_bridge` | `PAGE_LIMIT` | Integer `20`; maximum pages used by this bridge. |
| `varde_code.toz_bridge` | `enabled` | `enabled() -> bool`; true unless VARDE_CODE_TOZ is `0`. |
| `varde_code.toz_bridge` | `available` | `available(capture: OutputCapture | None) -> bool`. |
| `varde_code.toz_bridge` | `capture_text` | `capture_text(capture: OutputCapture | None, source: str, label: str, text: str) -> str | None`; best-effort capture. |
| `varde_code.toz_bridge` | `capture_items` | `capture_items(capture: OutputCapture | None, mode: str, items: list[Any]) -> dict[str, Any] | None`; best-effort JSONL capture. |
| `varde_code.toz_bridge` | `add_guide` | `add_guide(guide: dict[str, Any], reference: dict[str, Any], start: int, end: int) -> None`. |
| `varde_code.seams` | `FileWalker` | Protocol: `list_source_listing(self, root: Path) -> list[Path]`; `is_vcs_internal(self, path: Path) -> bool`. |
| `varde_code.seams` | `IndexService` | Protocol: `ensure_fresh(self, root: Path) -> None`; `check_fresh(self, root: Path, scope: object = None) -> bool`; `dump_state(self, root: Path) -> dict[str, object]`; `repo_db_path(self, root: Path) -> Path`. |
| `varde_code.seams` | `ExtractionProvider` | Protocol: `extract(self, path: Path, source: str, language: str) -> ExtractOutput`; complexity is carried in provider output. |
| `varde_code.seams` | `GraphCache` | Protocol: `read(self, db_path: Path, rev: int) -> Graph | None`; `write(self, db_path: Path, graph: Graph, rev: int) -> None`. |
| `varde_code.graph_model` | `Graph(paths: dict[int, str] = {}, out: dict[int, list[int]] = {}, inc: dict[int, list[int]] = {})`; `.to_dict(self) -> dict[str, dict[str, object]]`; `.from_dict(value: Mapping[str, object]) -> Graph`. Maps serialize as JSON-compatible string keys and integer adjacency lists. |
| `varde_code.git` | `run_git` | `run_git(args: Sequence[str], cwd: Path) -> str | None`; stdout on success, None on launch or command failure. |
| `varde_code.pattern_match` | `Language` | `Language(name: str)`; named tuple for a canonical language. |
| `varde_code.pattern_match` | `LANGUAGES` | Tuple of `Language` entries for typescript, tsx, javascript, c, cpp, go, java, csharp, kotlin, swift, python, ruby, php, scala, dart, lua, elixir, solidity, haskell, bash, rust. |
| `varde_code.pattern_match` | `LANGUAGE_ALIASES` | `dict[str, str]`; accepted pattern-language aliases. |
| `varde_code.pattern_match` | `language_name` | `language_name(language: str) -> str`; resolves canonical language / alias or raises ValueError. |
| `varde_code.pattern_match` | `wrap_pattern` | `wrap_pattern(language: str, pattern: str) -> str`; wraps statement snippets where needed. |
| `varde_code.pattern_match` | `find_patterns` | `find_patterns(source: str, pattern: str, language: str) -> list[dict[str, object]]`; matches on an independent `ast_grep_py.SgRoot`. |
| `varde_code.pattern_match` | `find_patterns_unbounded` | `find_patterns_unbounded(repo_root: str | Path, language: str, patterns: list[str] | tuple[str, ...]) -> list[list[dict[str, object]]]`; searches readable files under a root. |

The test reads the import rows above and imports each module/name pair.



### Additional APIs already importable

These interfaces are frozen for planning and appear in the available-import table above; the separate post-freeze test checks their import contracts.

- `varde_core.redact`: `RedactConfig`; `Redactor(cfg)` raises `ValueError` for invalid patterns; `.redact(text)`, `.redact_spans(text)`, `SecretValue`, `Kind`, `Span`, `Notice`, and `values.*`. User patterns use Python's `re` dialect: lookarounds and backreferences are accepted, while Rust-only constructs such as `\\p{L}` and `[[:alpha:]]` are rejected.
- `varde_core.text_audit`: `audit(text, path) -> list[Finding]`, `skill_refs(text, path, own, known)`, `eval_content(json_text, path)` (warn-only `eval-content`), `Severity`, `Rule`, `expand_skill_dir`.
- `varde_core.skill_relations`: `parse(frontmatter) -> Relations` (raises `RelationError`), `closure(...)`, `IMPLICIT_SKILL`. `RelationError.kind` is `malformed`, `unknown`, or `cycle`; `.detail` contains the explanatory text.
- `varde_core.utc`: `as_utc`, `parse_datetime`, `utc_day`, `window_start`, and `in_window` provide pure UTC datetime and window helpers.
- `varde_learn.loop.errors`: error types ported from `error.rs` (84 lines).
- `varde_learn.loop.redact`: redaction APIs ported from `redact.rs` (44 lines).
- `varde_learn.loop.store_dir.resolve_store_dir(...)`: resolves the learn store directory and returns the learn error type from `errors.py`. The task plan does not give parameter annotations.

| `varde_core.redact` | `RedactConfig` | Configuration record for `Redactor`. |
| `varde_core.redact` | `Redactor` | `Redactor(cfg)`; raises `ValueError` for invalid patterns; `.redact(text)` and `.redact_spans(text)`. |
| `varde_core.redact` | `Redacted` | Redacted text and notices. |
| `varde_core.redact` | `Notice` | Redaction notice record. |
| `varde_core.redact` | `Kind` | Redaction kind enum. |
| `varde_core.redact` | `SecretValue` | Named secret value record. |
| `varde_core.redact` | `Span` | Redacted source span. |
| `varde_core.redact` | `values` | Secret value collection helpers. |
| `varde_core.text_audit` | `Finding` | Text audit finding record. |
| `varde_core.text_audit` | `Rule` | Text audit rule enum. |
| `varde_core.text_audit` | `Severity` | Finding severity enum. |
| `varde_core.text_audit` | `audit` | `audit(text, path) -> list[Finding]`. |
| `varde_core.text_audit` | `expand_skill_dir` | Expands a skill directory for audit. |
| `varde_core.skill_relations` | `RelationError` | Relation parsing error with `.kind` (`malformed`, `unknown`, or `cycle`) and `.detail`. |
| `varde_core.skill_relations` | `Relations` | Parsed skill relation record. |
| `varde_core.skill_relations` | `IMPLICIT_SKILL` | Implicit skill relation name. |
| `varde_core.skill_relations` | `closure` | Computes the transitive skill relation closure. |
| `varde_core.skill_relations` | `parse` | `parse(frontmatter) -> Relations`; raises `RelationError`. |
| `varde_learn.loop.errors` | `LearnError` | Base learn error type. |
| `varde_learn.loop.errors` | `NotImplemented` | Learn operation not implemented error. |
| `varde_learn.loop.errors` | `Usage` | Learn usage error. |
| `varde_learn.loop.errors` | `StoreConfig` | Store configuration error. |
| `varde_learn.loop.errors` | `StoreInvalid` | Invalid store error. |
| `varde_learn.loop.errors` | `StoreItemNotFound` | Store item not found error. |
| `varde_learn.loop.errors` | `StoreInsideGit` | Store inside Git repository error. |
| `varde_learn.loop.errors` | `StoreSchemaTooNew` | Store schema too new error. |
| `varde_learn.loop.errors` | `StoreSchemaVersion` | Store schema version error. |
| `varde_learn.loop.errors` | `StoreGitCheck` | Store Git check error. |
| `varde_learn.loop.errors` | `StoreIo` | Store I/O error. |
| `varde_learn.loop.errors` | `StoreDatabase` | Store database error. |
| `varde_learn.loop.errors` | `Diagnose` | Store diagnosis record. |
| `varde_learn.loop.redact` | `Redacted` | Redacted learn text and notices. |
| `varde_learn.loop.redact` | `apply` | Applies learn redaction. |
| `varde_learn.loop.store_dir` | `resolve_store_dir` | Resolves the learn store directory. |

## Dependency rules

Families and allowed edges follow the core plan: `varde-toz`; `varde-knowledge` + `varde-workflow`; `varde-learn`; `varde-doc`; `varde-code`. Core imports no `varde-*` package. Modules may import core and their own family. Only the `varde` app imports module packages. The test parses PEP 508 requirements, scans runtime, optional and dependency-group dependencies plus package imports, and seeds a violation for each rule in an isolated temporary source copy.


- `code/pyproject.toml` pins `ast-grep-py==0.50.0` (tree-sitter 0.26.0; language pack 1.22.1). Pattern matching uses an independent `ast_grep_py.SgRoot`.

## Ownership inventory by plan

This inventory unions every `owns` and `creates` list in task files under `python-port-*/tasks/` with `app/tests/fixtures/stub-manifest.json`. The manifest reflects only skeleton-created files. Repeated task claims within a plan are shown after the path.

### `app-glue`

- `app/src/varde/glue/contracts.py` (tasks: `edit-and-contracts`)
- `app/src/varde/glue/edit.py` (tasks: `edit-and-contracts`)
- `app/src/varde/glue/hook.py` (tasks: `hook-dispatch`)
- `app/src/varde/glue/search/__init__.py` (tasks: `search-core`)
- `app/src/varde/glue/search/code.py` (tasks: `search-sources`)
- `app/src/varde/glue/search/core.py` (tasks: `search-core`)
- `app/src/varde/glue/search/friction.py` (tasks: `search-sources`)
- `app/src/varde/glue/search/knowledge.py` (tasks: `search-sources`)
- `app/src/varde/glue/search/toz.py` (tasks: `search-sources`)
- `app/src/varde/glue/session_notes.py` (tasks: `session-notes`)
- `app/tests/glue/test_edit_contracts.py` (tasks: `edit-and-contracts`)
- `app/tests/glue/test_hook.py` (tasks: `hook-dispatch`)
- `app/tests/glue/test_search_core.py` (tasks: `search-core`)
- `app/tests/glue/test_search_sources.py` (tasks: `search-sources`)
- `app/tests/glue/test_session_notes.py` (tasks: `session-notes`)

### `app-setup`

- `app/src/varde/setup/autosave.py` (tasks: `autosave`)
- `app/src/varde/setup/cli.py` (tasks: `cli-and-help`)
- `app/src/varde/setup/help/**` (tasks: `cli-and-help`)
- `app/src/varde/setup/hooks_install.py` (tasks: `hooks-install`)
- `app/src/varde/setup/module.py` (tasks: `cli-and-help`)
- `app/src/varde/setup/old_store.py` (tasks: `session-notes-migrate`)
- `app/src/varde/setup/session_notes_migrate.py` (tasks: `session-notes-migrate`)
- `app/src/varde/setup/sync/__init__.py` (tasks: `sync-command`)
- `app/src/varde/setup/sync/agents.py` (tasks: `sync-agents`)
- `app/src/varde/setup/sync/command.py` (tasks: `sync-command`)
- `app/src/varde/setup/sync/config.py` (tasks: `sync-base`)
- `app/src/varde/setup/sync/fsops.py` (tasks: `sync-base`)
- `app/src/varde/setup/sync/harness.py` (tasks: `sync-base`)
- `app/src/varde/setup/sync/preserve.py` (tasks: `sync-skills`)
- `app/src/varde/setup/sync/skills.py` (tasks: `sync-skills`)
- `app/tests/setup/test_autosave.py` (tasks: `autosave`)
- `app/tests/setup/test_cli.py` (tasks: `cli-and-help`)
- `app/tests/setup/test_hooks_install.py` (tasks: `hooks-install`)
- `app/tests/setup/test_old_store_error.py` (tasks: `session-notes-migrate`)
- `app/tests/setup/test_session_notes_migrate.py` (tasks: `session-notes-migrate`)
- `app/tests/setup/test_sync_agents.py` (tasks: `sync-agents`)
- `app/tests/setup/test_sync_base.py` (tasks: `sync-base`)
- `app/tests/setup/test_sync_command.py` (tasks: `sync-command`)
- `app/tests/setup/test_sync_skills.py` (tasks: `sync-skills`)

### `app-shell`

- `/Users/alec/source/agent-memory/projects/varde-py/working/plans/2026-10-14-varde-python-port/evidence/app-shell/install.md` (tasks: `uv-tool-install`)
- `/Users/alec/source/agent-memory/projects/varde-py/working/plans/2026-10-14-varde-python-port/evidence/app-shell/startup.md` (tasks: `startup-budget`)
- `app/pex/**` (tasks: `pex-build`)
- `app/pyproject.toml` (tasks: `uv-tool-install`)
- `app/src/varde/cli.py` (tasks: `entry-and-discovery`)
- `app/src/varde/discovery.py` (tasks: `entry-and-discovery`)
- `app/src/varde/fastpath.py` (tasks: `startup-budget`)
- `app/src/varde/help/**` (tasks: `help-version`)
- `app/src/varde/help/.gitkeep` (tasks: `stub-manifest`)
- `app/src/varde/io.py` (tasks: `entry-and-discovery`)
- `app/src/varde/module.py` (tasks: `stub-manifest`)
- `app/src/varde/json_order.py` (tasks: `trim`)
- `app/src/varde/manifest.py` (tasks: `trim`)
- `app/src/varde/rewrites.py` (tasks: `router-table`)
- `app/src/varde/router.py` (tasks: `router-table`)
- `app/src/varde/routes.py` (tasks: `router-table`)
- `app/tests/check_licenses.py` (tasks: `pex-build`)
- `app/tests/install_smoke.py` (tasks: `uv-tool-install`)
- `app/tests/pex_smoke.py` (tasks: `pex-build`)
- `app/tests/test_entry.py` (tasks: `entry-and-discovery`)
- `app/tests/test_help_version.py` (tasks: `help-version`)
- `app/tests/test_json_order.py` (tasks: `trim`)
- `app/tests/test_manifest.py` (tasks: `trim`)
- `app/tests/test_modules_manifest.py` (tasks: `trim`)
- `app/tests/test_hook_imports.py` (tasks: `startup-budget`)
- `app/tests/test_router.py` (tasks: `router-table`)

### `code-extract`

- `/Users/alec/source/agent-memory/projects/varde-py/working/plans/2026-10-14-varde-python-port/evidence/code-extract/parser-decision.md` (tasks: `parser-decision`)
- `/Users/alec/source/agent-memory/projects/varde-py/working/plans/2026-10-14-varde-python-port/evidence/code-extract/versions.md` (tasks: `parser-decision`)
- `code/src/varde_code/cli_extract.py` (tasks: `extract-cli`, `stub-manifest`)
- `code/src/varde_code/complexity.py` (tasks: `complexity`)
- `code/src/varde_code/extract/__init__.py` (tasks: `framework`)
- `code/src/varde_code/extract/adapter.py` (tasks: `parser-decision`)
- `code/src/varde_code/extract/entity.py` (tasks: `framework`)
- `code/src/varde_code/extract/langs/__init__.py` (tasks: `framework`)
- `code/src/varde_code/extract/langs/base.py` (tasks: `framework`)
- `code/src/varde_code/extract/langs/bash.py` (tasks: `lang-bash`)
- `code/src/varde_code/extract/langs/c.py` (tasks: `lang-c-cpp`)
- `code/src/varde_code/extract/langs/cpp.py` (tasks: `lang-c-cpp`)
- `code/src/varde_code/extract/langs/go.py` (tasks: `lang-go`)
- `code/src/varde_code/extract/langs/java.py` (tasks: `lang-java`)
- `code/src/varde_code/extract/langs/javascript.py` (tasks: `lang-javascript-typescript`)
- `code/src/varde_code/extract/langs/python.py` (tasks: `lang-python`)
- `code/src/varde_code/extract/langs/role_tags.py` (tasks: `role-tags`)
- `code/src/varde_code/extract/langs/rust.py` (tasks: `lang-rust`)
- `code/src/varde_code/extract/langs/ts.py` (tasks: `lang-javascript-typescript`)
- `code/src/varde_code/extract/langs/tsx.py` (tasks: `lang-javascript-typescript`)
- `code/src/varde_code/extract/minhash.py` (tasks: `framework`)
- `code/src/varde_code/extract/preproc.py` (tasks: `framework`)
- `code/src/varde_code/extract/provider.py` (tasks: `provider`)
- `code/src/varde_code/extract/recursion.py` (tasks: `framework`)
- `code/src/varde_code/extract/symbol.py` (tasks: `framework`)
- `code/src/varde_code/extract/versions_check.py` (tasks: `parser-decision`)
- `code/src/varde_code/help/map_extract.txt` (tasks: `extract-cli`)
- `code/tests/extract/langs/test_bash.py` (tasks: `lang-bash`)
- `code/tests/extract/langs/test_c_cpp.py` (tasks: `lang-c-cpp`)
- `code/tests/extract/langs/test_go.py` (tasks: `lang-go`)
- `code/tests/extract/langs/test_java.py` (tasks: `lang-java`)
- `code/tests/extract/langs/test_javascript_typescript.py` (tasks: `lang-javascript-typescript`)
- `code/tests/extract/langs/test_python.py` (tasks: `lang-python`)
- `code/tests/extract/langs/test_rust.py` (tasks: `lang-rust`)
- `code/tests/extract/test_adapter.py` (tasks: `parser-decision`)
- `code/tests/extract/test_complexity.py` (tasks: `complexity`)
- `code/tests/extract/test_framework.py` (tasks: `framework`)
- `code/tests/extract/test_provider.py` (tasks: `provider`)
- `code/tests/extract/test_role_tags.py` (tasks: `role-tags`)
- `code/tests/test_cli_extract.py` (tasks: `extract-cli`)

### `code-gate`

- `/Users/alec/source/agent-memory/projects/varde-py/working/plans/2026-10-14-varde-python-port/evidence/code-gate/report.md` (tasks: `gate-report`)
- `/Users/alec/source/agent-memory/projects/varde-py/working/plans/2026-10-14-varde-python-port/evidence/code-gate/speed.md` (tasks: `speed-recompare`)

### `code-index`

- `/Users/alec/source/agent-memory/projects/varde-py/working/plans/2026-10-14-varde-python-port/evidence/code-index/derived-tables.md` (tasks: `db-schema`)
- `code/scripts/code-index/measure_index.py` (tasks: `measure-index`)
- `/Users/alec/source/agent-memory/projects/varde-py/working/plans/2026-10-14-varde-python-port/evidence/code-index/results/index-speed.json` (tasks: `measure-index`)
- `/Users/alec/source/agent-memory/projects/varde-py/working/plans/2026-10-14-varde-python-port/evidence/code-index/speed.md` (tasks: `measure-index`)
- `code/src/varde_code/cli_index.py` (tasks: `cli-index`, `stub-manifest`)
- `code/src/varde_code/help/map_build.txt` (tasks: `cli-index`)
- `code/src/varde_code/help/map_prune.txt` (tasks: `cli-index`)
- `code/src/varde_code/help/setup_watch.txt` (tasks: `cli-index`)
- `code/src/varde_code/index/__init__.py` (tasks: `db-schema`)
- `code/src/varde_code/index/build.py` (tasks: `build-full`)
- `code/src/varde_code/index/certified.py` (tasks: `git-churn`)
- `code/src/varde_code/index/churn.py` (tasks: `git-churn`)
- `code/src/varde_code/index/db.py` (tasks: `db-schema`)
- `code/src/varde_code/index/files.py` (tasks: `walker`)
- `code/src/varde_code/index/incremental.py` (tasks: `incremental`)
- `code/src/varde_code/index/paths.py` (tasks: `db-schema`)
- `code/src/varde_code/index/persist/__init__.py` (tasks: `persist-entities`)
- `code/src/varde_code/index/persist/edges.py` (tasks: `persist-edges`)
- `code/src/varde_code/index/persist/entities.py` (tasks: `persist-entities`)
- `code/src/varde_code/index/persist/graph.py` (tasks: `persist-edges`)
- `code/src/varde_code/index/prune.py` (tasks: `repo-lock-prune`)
- `code/src/varde_code/index/repo_lock.py` (tasks: `repo-lock-prune`)
- `code/src/varde_code/index/resolve/__init__.py` (tasks: `resolve-core`)
- `code/src/varde_code/index/resolve/aux.py` (tasks: `resolve-aux`)
- `code/src/varde_code/index/resolve/core.py` (tasks: `resolve-core`)
- `code/src/varde_code/index/slice.py` (tasks: `slice-state`)
- `code/src/varde_code/index/supervise.py` (tasks: `watch-ensure`)
- `code/src/varde_code/index/watch.py` (tasks: `watch-foreground`)
- `code/tests/index/test_build.py` (tasks: `build-full`)
- `code/tests/index/test_churn.py` (tasks: `git-churn`)
- `code/tests/index/test_db.py` (tasks: `db-schema`)
- `code/tests/index/test_files.py` (tasks: `walker`)
- `code/tests/index/test_incremental.py` (tasks: `incremental`)
- `code/tests/index/test_lock_prune.py` (tasks: `repo-lock-prune`)
- `code/tests/index/test_persist_edges.py` (tasks: `persist-edges`)
- `code/tests/index/test_persist_entities.py` (tasks: `persist-entities`)
- `code/tests/index/test_resolve_aux.py` (tasks: `resolve-aux`)
- `code/tests/index/test_resolve_core.py` (tasks: `resolve-core`)
- `code/tests/index/test_seam_contract.py` (tasks: `seam-contract-tests`)
- `code/tests/index/test_separate_paths.py` (tasks: `seam-contract-tests`)
- `code/tests/index/test_slice.py` (tasks: `slice-state`)
- `code/tests/index/test_supervise.py` (tasks: `watch-ensure`)
- `code/tests/index/test_watch.py` (tasks: `watch-foreground`)
- `code/tests/test_cli_index.py` (tasks: `cli-index`)

### `code-langs`

- `code/src/varde_code/extract/langs/cs.py` (tasks: `lang-csharp`)
- `code/src/varde_code/extract/langs/dart.py` (tasks: `lang-dart`)
- `code/src/varde_code/extract/langs/elixir.py` (tasks: `lang-elixir`)
- `code/src/varde_code/extract/langs/haskell.py` (tasks: `lang-haskell`)
- `code/src/varde_code/extract/langs/kotlin.py` (tasks: `lang-kotlin`)
- `code/src/varde_code/extract/langs/lua.py` (tasks: `lang-lua-solidity`)
- `code/src/varde_code/extract/langs/php.py` (tasks: `lang-php`)
- `code/src/varde_code/extract/langs/ruby.py` (tasks: `lang-ruby`)
- `code/src/varde_code/extract/langs/scala.py` (tasks: `lang-scala`)
- `code/src/varde_code/extract/langs/solidity.py` (tasks: `lang-lua-solidity`)
- `code/src/varde_code/extract/langs/swift.py` (tasks: `lang-swift`)
- `code/tests/extract/langs/test_csharp.py` (tasks: `lang-csharp`)
- `code/tests/extract/langs/test_dart.py` (tasks: `lang-dart`)
- `code/tests/extract/langs/test_elixir.py` (tasks: `lang-elixir`)
- `code/tests/extract/langs/test_haskell.py` (tasks: `lang-haskell`)
- `code/tests/extract/langs/test_kotlin.py` (tasks: `lang-kotlin`)
- `code/tests/extract/langs/test_lua_solidity.py` (tasks: `lang-lua-solidity`)
- `code/tests/extract/langs/test_php.py` (tasks: `lang-php`)
- `code/tests/extract/langs/test_ruby.py` (tasks: `lang-ruby`)
- `code/tests/extract/langs/test_scala.py` (tasks: `lang-scala`)
- `code/tests/extract/langs/test_swift.py` (tasks: `lang-swift`)

### `code-query`

- `code/src/varde_code/cli_query.py` (tasks: `cli-query`, `stub-manifest`)
- `code/src/varde_code/help/map.txt` (tasks: `cli-query`)
- `code/src/varde_code/help/map_batch.txt` (tasks: `cli-query`)
- `code/src/varde_code/help/map_blast_radius.txt` (tasks: `cli-query`)
- `code/src/varde_code/help/map_clusters.txt` (tasks: `cli-query`)
- `code/src/varde_code/help/map_context_pack.txt` (tasks: `cli-query`)
- `code/src/varde_code/help/map_dependencies.txt` (tasks: `cli-query`)
- `code/src/varde_code/help/map_dependents.txt` (tasks: `cli-query`)
- `code/src/varde_code/help/map_detect_changes.txt` (tasks: `cli-query`)
- `code/src/varde_code/help/map_explore.txt` (tasks: `cli-query`)
- `code/src/varde_code/help/map_filter_symbols.txt` (tasks: `cli-query`)
- `code/src/varde_code/help/map_find_imports.txt` (tasks: `cli-query`)
- `code/src/varde_code/help/map_find_pattern.txt` (tasks: `cli-query`)
- `code/src/varde_code/help/map_get_symbol.txt` (tasks: `cli-query`)
- `code/src/varde_code/help/map_hotspots.txt` (tasks: `cli-query`)
- `code/src/varde_code/help/map_map_file.txt` (tasks: `cli-query`)
- `code/src/varde_code/help/map_map_path.txt` (tasks: `cli-query`)
- `code/src/varde_code/help/map_map_symbol.txt` (tasks: `cli-query`)
- `code/src/varde_code/help/map_nav_map.txt` (tasks: `cli-query`)
- `code/src/varde_code/help/map_slice_state.txt` (tasks: `cli-query`)
- `code/src/varde_code/help/map_symbol_blast_radius.txt` (tasks: `cli-query`)
- `code/src/varde_code/help/map_symbols_in_file.txt` (tasks: `cli-query`)
- `code/src/varde_code/help/map_symbols_in_files.txt` (tasks: `cli-query`)
- `code/src/varde_code/help/map_tests_for_file.txt` (tasks: `cli-query`)
- `code/src/varde_code/help/map_type_hierarchy.txt` (tasks: `cli-query`)
- `code/src/varde_code/query/__init__.py` (tasks: `query-core`)
- `code/src/varde_code/query/entrypoints.py` (tasks: `query-entrypoints`)
- `code/src/varde_code/query/find_pattern.py` (tasks: `query-find-pattern`)
- `code/src/varde_code/query/flows.py` (tasks: `nav-map-flows`)
- `code/src/varde_code/query/foundational_files.py` (tasks: `mapping-and-nav-map`)
- `code/src/varde_code/query/graph.py` (tasks: `query-graph`)
- `code/src/varde_code/query/mapping.py` (tasks: `mapping-and-nav-map`)
- `code/src/varde_code/query/modes.py` (tasks: `query-core`)
- `code/src/varde_code/query/module_layers.py` (tasks: `nav-map-flows`)
- `code/src/varde_code/query/nav_map.py` (tasks: `mapping-and-nav-map`)
- `code/src/varde_code/query/noise_filter.py` (tasks: `query-core`)
- `code/src/varde_code/query/output.py` (tasks: `query-core`)
- `code/src/varde_code/query/params.py` (tasks: `query-core`)
- `code/src/varde_code/query/simple.py` (tasks: `query-simple`)
- `code/src/varde_code/query/subsystems.py` (tasks: `nav-map-flows`)
- `code/src/varde_code/query/symbol_impact.py` (tasks: `query-graph`)
- `code/src/varde_code/query/symbols_section.py` (tasks: `mapping-and-nav-map`)
- `code/tests/query/test_batch.py` (tasks: `cli-query`)
- `code/tests/query/test_core.py` (tasks: `query-core`)
- `code/tests/query/test_entrypoints.py` (tasks: `query-entrypoints`)
- `code/tests/query/test_find_pattern_languages.py` (tasks: `query-find-pattern`)
- `code/tests/query/test_graph.py` (tasks: `query-graph`)
- `code/tests/query/test_mapping_nav.py` (tasks: `mapping-and-nav-map`)
- `code/tests/query/test_nav_flows.py` (tasks: `nav-map-flows`)
- `code/tests/query/test_simple.py` (tasks: `query-simple`)
- `code/tests/test_cli_query.py` (tasks: `cli-query`)

### `code-rules`

- `/Users/alec/source/agent-memory/projects/varde-py/working/plans/2026-10-14-varde-python-port/evidence/code-rules/BUILT_IN_RULES.md` (tasks: `builtin-pack`)
- `/Users/alec/source/agent-memory/projects/varde-py/working/plans/2026-10-14-varde-python-port/evidence/code-rules/node-types.md` (tasks: `pattern`)
- `code/src/varde_code/rules/__init__.py` (tasks: `loader`)
- `code/src/varde_code/rules/__main__.py` (tasks: `runner`)
- `code/src/varde_code/rules/builtin/**` (tasks: `builtin-pack`)
- `code/src/varde_code/rules/clone_verification.py` (tasks: `findings`)
- `code/src/varde_code/rules/correlate.py` (tasks: `findings`)
- `code/src/varde_code/rules/dependency_facts/__init__.py` (tasks: `sql`)
- `code/src/varde_code/rules/dependency_facts/c_cpp.py` (tasks: `deps-core-python-rust-c`)
- `code/src/varde_code/rules/dependency_facts/csharp_swift.py` (tasks: `deps-jvm-dotnet-swift`)
- `code/src/varde_code/rules/dependency_facts/elixir_haskell.py` (tasks: `deps-others`)
- `code/src/varde_code/rules/dependency_facts/jvm.py` (tasks: `deps-jvm-dotnet-swift`)
- `code/src/varde_code/rules/dependency_facts/lua_bash.py` (tasks: `deps-others`)
- `code/src/varde_code/rules/dependency_facts/prepare.py` (tasks: `sql`)
- `code/src/varde_code/rules/dependency_facts/python.py` (tasks: `deps-core-python-rust-c`)
- `code/src/varde_code/rules/dependency_facts/ruby_php.py` (tasks: `deps-others`)
- `code/src/varde_code/rules/dependency_facts/rust.py` (tasks: `deps-core-python-rust-c`)
- `code/src/varde_code/rules/dependency_facts/types.py` (tasks: `deps-core-python-rust-c`)
- `code/src/varde_code/rules/engine.py` (tasks: `engine`)
- `code/src/varde_code/rules/finding.py` (tasks: `findings`)
- `code/src/varde_code/rules/index_reader.py` (tasks: `rule-model`)
- `code/src/varde_code/rules/loader.py` (tasks: `loader`)
- `code/src/varde_code/rules/model.py` (tasks: `rule-model`)
- `code/src/varde_code/rules/pattern.py` (tasks: `pattern`)
- `code/src/varde_code/rules/rewrite.py` (tasks: `rewrite`)
- `code/src/varde_code/rules/sql.py` (tasks: `sql`)
- `code/src/varde_code/rules/suppress.py` (tasks: `findings`)
- `code/src/varde_code/rules/test_runner.py` (tasks: `test-runner`)
- `code/tests/rules/deps/test_a.py` (tasks: `deps-core-python-rust-c`)
- `code/tests/rules/deps/test_b.py` (tasks: `deps-jvm-dotnet-swift`)
- `code/tests/rules/deps/test_c.py` (tasks: `deps-others`)
- `code/tests/rules/test_builtin_pack.py` (tasks: `builtin-pack`)
- `code/tests/rules/test_engine.py` (tasks: `engine`)
- `code/tests/rules/test_findings.py` (tasks: `findings`)
- `code/tests/rules/test_loader.py` (tasks: `loader`)
- `code/tests/rules/test_main.py` (tasks: `runner`)
- `code/tests/rules/test_model.py` (tasks: `rule-model`)
- `code/tests/rules/test_pattern.py` (tasks: `pattern`)
- `code/tests/rules/test_rewrite.py` (tasks: `rewrite`)
- `code/tests/rules/test_sql.py` (tasks: `sql`)
- `code/tests/rules/test_test_runner.py` (tasks: `test-runner`)

### `code-scan`

- `code/src/varde_code/ast_edit/**` (tasks: `ast-edit`)
- `code/src/varde_code/cli_edit.py` (tasks: `cli-wire`, `stub-manifest`)
- `code/src/varde_code/cli_scan.py` (tasks: `cli-wire`, `stub-manifest`)
- `code/src/varde_code/help/edit_*.txt` (tasks: `cli-wire`)
- `code/src/varde_code/help/scan_*.txt` (tasks: `cli-wire`)
- `code/src/varde_code/hooks.py` (tasks: `hooks`)
- `code/src/varde_code/scan/__init__.py` (tasks: `scan-core`)
- `code/src/varde_code/scan/core.py` (tasks: `scan-core`)
- `code/src/varde_code/scan/rules_cmd.py` (tasks: `scan-rules-and-setup`)
- `code/src/varde_code/scan/run.py` (tasks: `scan-run`)
- `code/src/varde_code/scan/setup.py` (tasks: `scan-rules-and-setup`)
- `code/src/varde_code/scan/test_cmd.py` (tasks: `scan-test`)
- `code/tests/ast_edit/**` (tasks: `ast-edit`)
- `code/tests/scan/test_core.py` (tasks: `scan-core`)
- `code/tests/scan/test_rules_setup.py` (tasks: `scan-rules-and-setup`)
- `code/tests/scan/test_run.py` (tasks: `scan-run`)
- `code/tests/scan/test_test_cmd.py` (tasks: `scan-test`)
- `code/tests/test_cli_scan.py` (tasks: `cli-wire`)
- `code/tests/test_hooks.py` (tasks: `hooks`)

### `core`

- `/Users/alec/source/agent-memory/projects/varde-py/working/plans/2026-10-14-varde-python-port/evidence/core/fixtures.md` (tasks: `code-fixtures`)
- `/Users/alec/source/agent-memory/projects/varde-py/working/plans/2026-10-14-varde-python-port/evidence/core/linux-wheels.md` (tasks: `linux-wheel-checks`)
- `app/tests/fixtures/stub-manifest.json` (tasks: `workspace-skeleton`)
- `code/tests/rules/fixtures/versions.md` (tasks: `linux-wheel-checks`)
- `pyproject.toml` (tasks: `workspace-skeleton`)
- `code/pyproject.toml` (tasks: `workspace-skeleton`)
- `code/src/varde_code/__init__.py` (tasks: `workspace-skeleton`)
- `code/src/varde_code/cli_edit.py` (tasks: `workspace-skeleton`)
- `code/src/varde_code/cli_extract.py` (tasks: `workspace-skeleton`)
- `code/src/varde_code/cli_index.py` (tasks: `workspace-skeleton`)
- `code/src/varde_code/cli_query.py` (tasks: `workspace-skeleton`)
- `code/src/varde_code/cli_scan.py` (tasks: `workspace-skeleton`)
- `code/src/varde_code/git.py` (tasks: `code-seams`)
- `code/src/varde_code/graph_model.py` (tasks: `code-seams`)
- `code/src/varde_code/help/.gitkeep` (tasks: `workspace-skeleton`)
- `code/src/varde_code/model.py` (tasks: `code-model-parse`)
- `code/src/varde_code/module.py` (tasks: `workspace-skeleton`)
- `code/src/varde_code/parse.py` (tasks: `code-model-parse`)
- `code/src/varde_code/pattern_match.py` (tasks: `find-pattern-lib`)
- `code/src/varde_code/seams.py` (tasks: `code-seams`)
- `code/src/varde_code/testing/**` (tasks: `code-seams`)
- `code/src/varde_code/toz_bridge.py` (tasks: `code-model-parse`)
- `code/tests/core/test_model_parse.py` (tasks: `code-model-parse`)
- `code/tests/core/test_pattern_match.py` (tasks: `find-pattern-lib`)
- `code/tests/core/test_seams.py` (tasks: `code-seams`)
- `code/tests/fixtures/**` (tasks: `code-fixtures`)
- `app/tests/test_skeletons.py` (tasks: `contracts`)
- `core/API-extra.md` (tasks: `api-complete`)
- `core/API.md` (tasks: `api-freeze`)
- `core/pyproject.toml` (tasks: `workspace-skeleton`)
- `core/src/varde_core/__init__.py` (tasks: `workspace-skeleton`)
- `core/src/varde_core/constants.py` (tasks: `core-small-modules`)
- `core/src/varde_core/envelope.py` (tasks: `core-small-modules`)
- `core/src/varde_core/jsonio.py` (tasks: `core-small-modules`)
- `core/src/varde_core/paths.py` (tasks: `core-small-modules`)
- `core/src/varde_core/redact/**` (tasks: `core-redact`)
- `core/src/varde_core/skill_relations.py` (tasks: `core-text-audit-skill-relations`)
- `core/src/varde_core/sqlite.py` (tasks: `core-small-modules`)
- `core/src/varde_core/text_audit.py` (tasks: `core-text-audit-skill-relations`)
- `core/tests/redact/**` (tasks: `core-redact`)
- `core/tests/small/**` (tasks: `core-small-modules`)
- `core/tests/test_api_contract.py` (tasks: `api-freeze`)
- `core/tests/test_api_contract_extra.py` (tasks: `api-complete`)
- `core/tests/test_dependency_rules.py` (tasks: `api-freeze`)
- `core/tests/test_shim_cases.py` (tasks: `api-complete`)
- `core/tests/text/**` (tasks: `core-text-audit-skill-relations`)
- `learn/pyproject.toml` (tasks: `workspace-skeleton`)
- `learn/src/varde_learn/docs/__init__.py` (tasks: `workspace-skeleton`)
- `learn/src/varde_learn/docs/help/.gitkeep` (tasks: `workspace-skeleton`)
- `learn/src/varde_learn/docs/module.py` (tasks: `workspace-skeleton`)
- `learn/pyproject.toml` (tasks: `workspace-skeleton`)
- `learn/src/varde_learn/__init__.py` (tasks: `workspace-skeleton`)
- `learn/src/varde_learn/loop/cli_diagnose.py` (tasks: `workspace-skeleton`)
- `learn/src/varde_learn/loop/cli_friction.py` (tasks: `workspace-skeleton`)
- `learn/src/varde_learn/loop/errors.py` (tasks: `learn-base`)
- `learn/src/varde_learn/loop/help/.gitkeep` (tasks: `workspace-skeleton`)
- `learn/src/varde_learn/module.py` (tasks: `workspace-skeleton`)
- `learn/src/varde_learn/loop/redact.py` (tasks: `learn-base`)
- `learn/src/varde_learn/loop/store_dir.py` (tasks: `learn-base`)
- `learn/tests/base/**` (tasks: `learn-base`)
- `learn/pyproject.toml` (tasks: `workspace-skeleton`)
- `learn/src/varde_learn/knowledge/__init__.py` (tasks: `workspace-skeleton`)
- `learn/src/varde_learn/knowledge/help/.gitkeep` (tasks: `workspace-skeleton`)
- `learn/src/varde_learn/knowledge/module.py` (tasks: `workspace-skeleton`)
- `workflow/pyproject.toml` (tasks: `workspace-skeleton`)
- `workflow/src/varde_workflow/__init__.py` (tasks: `workspace-skeleton`)
- `workflow/src/varde_workflow/help/.gitkeep` (tasks: `workspace-skeleton`)
- `workflow/src/varde_workflow/module.py` (tasks: `workspace-skeleton`)
- `app/pyproject.toml` (tasks: `workspace-skeleton`)
- `app/src/varde/__init__.py` (tasks: `workspace-skeleton`)
- `app/src/varde/help/.gitkeep` (tasks: `workspace-skeleton`)
- `app/src/varde/module.py` (tasks: `workspace-skeleton`)
- `/Users/alec/source/agent-memory/projects/varde-py/working/plans/2026-10-14-varde-python-port/evidence/spikes/prototype/**` (tasks: `workspace-skeleton`)
- `src/varde_py/**` (tasks: `workspace-skeleton`)
- `tests/test_index.py` (tasks: `workspace-skeleton`)

### `cutover`

- `AGENTS.md` (tasks: `docs-skills-update`)
- `README.md` (tasks: `docs-skills-update`)
- `workflow/src/varde_workflow/agents/**` (tasks: `docs-skills-update`, `import-repo-assets`)
- `/Users/alec/source/agent-memory/projects/varde-py/working/plans/2026-10-14-varde-python-port/evidence/**` (tasks: `docs-skills-update`)
- `/Users/alec/source/agent-memory/projects/varde-py/working/plans/2026-10-14-varde-python-port/evidence/cutover/docs-skills.md` (tasks: `docs-skills-update`)
- `/Users/alec/source/agent-memory/projects/varde-py/working/plans/2026-10-14-varde-python-port/evidence/cutover/import-assets.md` (tasks: `import-repo-assets`)
- `/Users/alec/source/agent-memory/projects/varde-py/working/plans/2026-10-14-varde-python-port/evidence/cutover/install.md` (tasks: `install-and-licences`)
- `/Users/alec/source/agent-memory/projects/varde-py/working/plans/2026-10-14-varde-python-port/evidence/cutover/latency.md` (tasks: `latency-final`)
- `/Users/alec/source/agent-memory/projects/varde-py/working/plans/2026-10-14-varde-python-port/evidence/cutover/memory-update.md` (tasks: `memory-update`)
- `/Users/alec/source/agent-memory/projects/varde-py/working/plans/2026-10-14-varde-python-port/evidence/cutover/references.md` (tasks: `rename-and-references`)
- `/Users/alec/source/agent-memory/projects/varde-py/working/plans/2026-10-14-varde-python-port/evidence/cutover/rollback.md` (tasks: `rename-and-references`)
- `/Users/alec/source/agent-memory/projects/varde-py/working/plans/2026-10-14-varde-python-port/evidence/cutover/rust-test-coverage.md` (tasks: `rust-test-coverage`)
- `/Users/alec/source/agent-memory/projects/varde-py/working/plans/2026-10-14-varde-python-port/evidence/cutover/signoff.md` (tasks: `dual-run-and-archive`)
- `justfile` (tasks: `import-repo-assets`)
- `skills/**` (tasks: `docs-skills-update`, `import-repo-assets`)
- `tests/**` (tasks: `import-repo-assets`)
- `tools/**` (tasks: `import-repo-assets`)

### `doc`

- `learn/pyproject.toml` (tasks: `cli-and-help`)
- `learn/src/varde_learn/docs/cli.py` (tasks: `cli-and-help`)
- `learn/src/varde_learn/docs/flow/__init__.py` (tasks: `flow-ledger-render`)
- `learn/src/varde_learn/docs/flow/analyze.py` (tasks: `flow-analyze`)
- `learn/src/varde_learn/docs/flow/ledger.py` (tasks: `flow-ledger-render`)
- `learn/src/varde_learn/docs/flow/render.py` (tasks: `flow-ledger-render`)
- `learn/src/varde_learn/docs/flow/scan.py` (tasks: `flow-scan`)
- `learn/src/varde_learn/docs/frontmatter.py` (tasks: `frontmatter`)
- `learn/src/varde_learn/docs/help/**` (tasks: `cli-and-help`)
- `learn/src/varde_learn/docs/help/.gitkeep` (tasks: `stub-manifest`)
- `learn/src/varde_learn/docs/lint.py` (tasks: `lint`)
- `learn/src/varde_learn/docs/module.py` (tasks: `cli-and-help`, `stub-manifest`)
- `learn/src/varde_learn/docs/spec_inventory.py` (tasks: `spec-inventory`)
- `learn/tests/docs/flow/test_analyze.py` (tasks: `flow-analyze`)
- `learn/tests/docs/flow/test_ledger_render.py` (tasks: `flow-ledger-render`)
- `learn/tests/docs/flow/test_scan.py` (tasks: `flow-scan`)
- `learn/tests/docs/test_frontmatter.py` (tasks: `frontmatter`)
- `learn/tests/docs/test_lint.py` (tasks: `lint`)
- `learn/tests/docs/test_spec_inventory.py` (tasks: `spec-inventory`)

### `learn-diagnose`

- `learn/src/varde_learn/loop/cli_diagnose.py` (tasks: `cli-diagnose`, `stub-manifest`)
- `learn/src/varde_learn/loop/codex.py` (tasks: `diagnose-codex`)
- `learn/src/varde_learn/loop/diagnose/__init__.py` (tasks: `diagnose-core`)
- `learn/src/varde_learn/loop/diagnose/claude.py` (tasks: `diagnose-claude`)
- `learn/src/varde_learn/loop/diagnose/codex/**` (tasks: `diagnose-codex`)
- `learn/src/varde_learn/loop/diagnose/context_usage.py` (tasks: `diagnose-core`)
- `learn/src/varde_learn/loop/diagnose/list.py` (tasks: `diagnose-core`)
- `learn/src/varde_learn/loop/diagnose/model.py` (tasks: `diagnose-core`)
- `learn/src/varde_learn/loop/diagnose/opencode.py` (tasks: `diagnose-opencode`)
- `learn/src/varde_learn/loop/help/diagnose/**` (tasks: `cli-diagnose`)
- `learn/src/varde_learn/loop/output/__init__.py` (tasks: `eval-run`)
- `learn/src/varde_learn/loop/output/adapter.py` (tasks: `eval-run`)
- `learn/src/varde_learn/loop/output/assertions.py` (tasks: `eval-grade`)
- `learn/src/varde_learn/loop/output/blocked.py` (tasks: `eval-grade`)
- `learn/src/varde_learn/loop/output/calibrate.py` (tasks: `eval-grade`)
- `learn/src/varde_learn/loop/output/cost.py` (tasks: `eval-grade`)
- `learn/src/varde_learn/loop/output/grade.py` (tasks: `eval-grade`)
- `learn/src/varde_learn/loop/output/paired.py` (tasks: `eval-grade`)
- `learn/src/varde_learn/loop/output/run.py` (tasks: `eval-run`)
- `learn/src/varde_learn/loop/process.py` (tasks: `eval-run`)
- `learn/src/varde_learn/loop/session_link.py` (tasks: `diagnose-codex`)
- `learn/src/varde_learn/loop/trigger.py` (tasks: `eval-run`)
- `learn/tests/diagnose/test_claude.py` (tasks: `diagnose-claude`)
- `learn/tests/diagnose/test_codex.py` (tasks: `diagnose-codex`)
- `learn/tests/diagnose/test_core.py` (tasks: `diagnose-core`)
- `learn/tests/diagnose/test_opencode.py` (tasks: `diagnose-opencode`)
- `learn/tests/output/test_grade.py` (tasks: `eval-grade`)
- `learn/tests/output/test_run.py` (tasks: `eval-run`)
- `learn/tests/test_cli_diagnose.py` (tasks: `cli-diagnose`)

### `learn-friction`

- `learn/src/varde_learn/loop/cli_friction.py` (tasks: `cli-friction`, `stub-manifest`)
- `learn/src/varde_learn/friction_log.py` (tasks: `friction-log`)
- `learn/src/varde_learn/loop/help/friction/**` (tasks: `cli-friction`)
- `learn/src/varde_learn/loop/importer.py` (tasks: `import`)
- `learn/src/varde_learn/loop/store/__init__.py` (tasks: `store-schema`)
- `learn/src/varde_learn/loop/store/open.py` (tasks: `store-schema`)
- `learn/src/varde_learn/loop/store/read.py` (tasks: `store-read`)
- `learn/src/varde_learn/loop/store/schema.py` (tasks: `store-schema`)
- `learn/src/varde_learn/loop/store/write.py` (tasks: `store-write`)
- `learn/tests/store/test_read.py` (tasks: `store-read`)
- `learn/tests/store/test_schema.py` (tasks: `store-schema`)
- `learn/tests/store/test_write.py` (tasks: `store-write`)
- `learn/tests/test_cli_friction.py` (tasks: `cli-friction`)
- `learn/tests/test_friction_log.py` (tasks: `friction-log`)
- `learn/tests/test_import.py` (tasks: `import`)

### `knowledge`

- `learn/pyproject.toml` (tasks: `cli-and-help`)
- `learn/src/varde_learn/knowledge/bundle.py` (tasks: `frontmatter-concept-walk`)
- `learn/src/varde_learn/knowledge/cli.py` (tasks: `cli-and-help`)
- `learn/src/varde_learn/knowledge/concept.py` (tasks: `frontmatter-concept-walk`)
- `learn/src/varde_learn/knowledge/crud/__init__.py` (tasks: `crud`)
- `learn/src/varde_learn/knowledge/crud/create.py` (tasks: `crud`)
- `learn/src/varde_learn/knowledge/crud/delete.py` (tasks: `crud`)
- `learn/src/varde_learn/knowledge/crud/list.py` (tasks: `crud`)
- `learn/src/varde_learn/knowledge/crud/search.py` (tasks: `crud-search`)
- `learn/src/varde_learn/knowledge/crud/show.py` (tasks: `crud`)
- `learn/src/varde_learn/knowledge/crud/timestamps.py` (tasks: `crud`)
- `learn/src/varde_learn/knowledge/crud/update.py` (tasks: `crud`)
- `learn/src/varde_learn/knowledge/frontmatter.py` (tasks: `frontmatter-concept-walk`)
- `learn/src/varde_learn/knowledge/help/**` (tasks: `cli-and-help`)
- `learn/src/varde_learn/knowledge/help/.gitkeep` (tasks: `stub-manifest`)
- `learn/src/varde_learn/knowledge/lint/**` (tasks: `lint`)
- `learn/src/varde_learn/knowledge/maps.py` (tasks: `registry-maps`)
- `learn/src/varde_learn/knowledge/memory.py` (tasks: `memory-paths`)
- `learn/src/varde_learn/knowledge/module.py` (tasks: `cli-and-help`, `stub-manifest`)
- `learn/src/varde_learn/knowledge/occ.py` (tasks: `frontmatter-concept-walk`)
- `learn/src/varde_learn/knowledge/registry.py` (tasks: `registry-maps`)
- `learn/src/varde_learn/knowledge/walk.py` (tasks: `frontmatter-concept-walk`)
- `learn/tests/knowledge/crud/**` (tasks: `crud`)
- `learn/tests/knowledge/lint/**` (tasks: `lint`)
- `learn/tests/knowledge/test_basics.py` (tasks: `frontmatter-concept-walk`)
- `learn/tests/knowledge/test_memory.py` (tasks: `memory-paths`)
- `learn/tests/knowledge/test_registry.py` (tasks: `registry-maps`)
- `learn/tests/knowledge/test_search.py` (tasks: `crud-search`)

### `spikes`

- `README.md` (tasks: `repo-setup`)
- `gate/` (tasks: `gate-report`)
- `pyproject.toml` (tasks: `repo-setup`)
- `scripts/` (tasks: `repo-setup`)
- `/Users/alec/source/agent-memory/projects/varde-py/working/plans/2026-10-14-varde-python-port/evidence/spikes/ast-grep/` (tasks: `ast-grep-feasibility`)
- `/Users/alec/source/agent-memory/projects/varde-py/working/plans/2026-10-14-varde-python-port/evidence/spikes/packaging/` (tasks: `packaging-spike`)
- `/Users/alec/source/agent-memory/projects/varde-py/working/plans/2026-10-14-varde-python-port/evidence/spikes/toz-hook/` (tasks: `toz-hook-spike`)
- `/Users/alec/source/agent-memory/projects/varde-py/working/plans/2026-10-14-varde-python-port/evidence/spikes/toz-report.md` (tasks: `toz-checkpoint`)
- `/Users/alec/source/agent-memory/projects/varde-py/working/plans/2026-10-14-varde-python-port/evidence/spikes/toz-scripting/` (tasks: `toz-scripting-count`)
- `/Users/alec/source/agent-memory/projects/varde-py/working/plans/2026-10-14-varde-python-port/evidence/spikes/toz-scripts/` (tasks: `toz-script-runner-spike`)
- `/Users/alec/source/agent-memory/projects/varde-py/working/plans/2026-10-14-varde-python-port/evidence/spikes/worktree-writes/` (tasks: `worktree-writes-spike`)

### `toz`

- `/Users/alec/source/agent-memory/projects/varde-py/working/plans/2026-10-14-varde-python-port/evidence/toz-port/report.md` (tasks: `measure-and-report`)
- `/Users/alec/source/agent-memory/projects/varde-py/working/plans/2026-10-14-varde-python-port/evidence/toz-port/results/` (tasks: `measure-and-report`)
- `/Users/alec/source/agent-memory/projects/varde-py/working/plans/2026-10-14-varde-python-port/evidence/toz-port/script-capabilities.md` (tasks: `script-runner`)
- `pyproject.toml` (tasks: `skeleton-core`)
- `toz/pyproject.toml` (tasks: `skeleton-core`)
- `toz/src/varde_toz/__init__.py` (tasks: `skeleton-core`)
- `toz/src/varde_toz/_core/` (tasks: `skeleton-core`)
- `toz/src/varde_toz/builtin_profiles.toml` (tasks: `capture-profiles`)
- `toz/src/varde_toz/capture.py` (tasks: `capture-profiles`)
- `toz/src/varde_toz/chunk.py` (tasks: `store-fts5`)
- `toz/src/varde_toz/cli.py` (tasks: `skeleton-core`)
- `toz/src/varde_toz/commands/__init__.py` (tasks: `skeleton-core`)
- `toz/src/varde_toz/commands/capture.py` (tasks: `capture-profiles`)
- `toz/src/varde_toz/commands/doctor.py` (tasks: `maintenance-commands`)
- `toz/src/varde_toz/commands/event_note.py` (tasks: `hook-dispatch`)
- `toz/src/varde_toz/commands/fetch.py` (tasks: `index-fetch`)
- `toz/src/varde_toz/commands/hook.py` (tasks: `hook-dispatch`)
- `toz/src/varde_toz/commands/index.py` (tasks: `index-fetch`)
- `toz/src/varde_toz/commands/migrate.py` (tasks: `maintenance-commands`)
- `toz/src/varde_toz/commands/profile.py` (tasks: `maintenance-commands`)
- `toz/src/varde_toz/commands/purge.py` (tasks: `maintenance-commands`)
- `toz/src/varde_toz/commands/query.py` (tasks: `query-search`)
- `toz/src/varde_toz/commands/run.py` (tasks: `script-runner`)
- `toz/src/varde_toz/commands/stats.py` (tasks: `maintenance-commands`)
- `toz/src/varde_toz/config.py` (tasks: `skeleton-core`)
- `toz/src/varde_toz/fetch.py` (tasks: `index-fetch`)
- `toz/src/varde_toz/hook.py` (tasks: `hook-dispatch`)
- `toz/src/varde_toz/hook_input/` (tasks: `hook-dispatch`)
- `toz/src/varde_toz/index_files.py` (tasks: `index-fetch`)
- `toz/src/varde_toz/metadata.py` (tasks: `store-fts5`)
- `toz/src/varde_toz/profile.py` (tasks: `capture-profiles`)
- `toz/src/varde_toz/project.py` (tasks: `store-fts5`)
- `toz/src/varde_toz/raw.py` (tasks: `store-fts5`)
- `toz/src/varde_toz/redact_toz.py` (tasks: `capture-profiles`)
- `toz/src/varde_toz/runner/` (tasks: `script-runner`)
- `toz/src/varde_toz/script.py` (tasks: `script-runner`)
- `toz/src/varde_toz/search.py` (tasks: `query-search`)
- `toz/src/varde_toz/store.py` (tasks: `store-fts5`)
- `toz/src/varde_toz/strategies.py` (tasks: `capture-profiles`)
- `toz/src/varde_toz/streaming.py` (tasks: `capture-profiles`)
- `toz/src/varde_toz/terms.py` (tasks: `store-fts5`)
- `toz/tests/test_capture.py` (tasks: `capture-profiles`)
- `toz/tests/test_config.py` (tasks: `skeleton-core`)
- `toz/tests/test_core_shim.py` (tasks: `skeleton-core`)
- `toz/tests/test_fetch_cache.py` (tasks: `index-fetch`)
- `toz/tests/test_fixtures.py` (tasks: `capture-profiles`)
- `toz/tests/test_index_refresh.py` (tasks: `index-fetch`)
- `toz/tests/test_profile_globs.py` (tasks: `capture-profiles`)
- `toz/tests/test_prune_maintenance.py` (tasks: `store-fts5`)
- `toz/tests/test_script*.py` (tasks: `script-runner`)
- `toz/tests/test_store*.py` (tasks: `store-fts5`)
- `toz/tests/test_write_budget.py` (tasks: `store-fts5`)
- `uv.lock` (tasks: `skeleton-core`)

### `toz-adopt`

- `/Users/alec/source/agent-memory/projects/varde-py/working/plans/2026-10-14-varde-python-port/evidence/toz-adopt/**` (tasks: `verify-latency-and-cross-read`)
- `toz/pyproject.toml` (tasks: `module-contract`)
- `toz/src/varde_toz/_core/**` (tasks: `swap-shim`)
- `toz/src/varde_toz/config.py` (tasks: `swap-shim`)
- `toz/src/varde_toz/doctor.py` (tasks: `doctor-and-retire`)
- `toz/src/varde_toz/help/**` (tasks: `module-contract`)
- `toz/src/varde_toz/install.py` (tasks: `doctor-and-retire`)
- `toz/src/varde_toz/module.py` (tasks: `module-contract`)
- `toz/src/varde_toz/redact_toz.py` (tasks: `swap-shim`)
- `toz/src/varde_toz/sandbox.py` (tasks: `sandbox`)
- `toz/src/varde_toz/store.py` (tasks: `swap-shim`)
- `toz/tests/test_core_shim.py` (tasks: `swap-shim`)
- `toz/tests/test_doctor_retire.py` (tasks: `doctor-and-retire`)
- `toz/tests/test_sandbox.py` (tasks: `sandbox`)

### `toz-latency`

- `/Users/alec/source/agent-memory/projects/varde-py/working/plans/2026-10-14-varde-python-port/evidence/toz-latency/packaging/README.md` (tasks: `packaging-startup-compare`)
- `toz/scripts/toz-latency/packaging/validate.py` (tasks: `packaging-startup-compare`)
- `/Users/alec/source/agent-memory/projects/varde-py/working/plans/2026-10-14-varde-python-port/evidence/toz-latency/phases.md` (tasks: `profile-phases`)
- `toz/scripts/toz-latency/profile_phases.py` (tasks: `profile-phases`)
- `/Users/alec/source/agent-memory/projects/varde-py/working/plans/2026-10-14-varde-python-port/evidence/toz-latency/report.md` (tasks: `measure-latency-report`)
- `/Users/alec/source/agent-memory/projects/varde-py/working/plans/2026-10-14-varde-python-port/evidence/toz-latency/results/algorithms.json` (tasks: `chunk-redact-algorithms`)
- `/Users/alec/source/agent-memory/projects/varde-py/working/plans/2026-10-14-varde-python-port/evidence/toz-latency/results/daemon.json` (tasks: `daemon-prototype`)
- `/Users/alec/source/agent-memory/projects/varde-py/working/plans/2026-10-14-varde-python-port/evidence/toz-latency/results/final.json` (tasks: `measure-latency-report`)
- `/Users/alec/source/agent-memory/projects/varde-py/working/plans/2026-10-14-varde-python-port/evidence/toz-latency/results/launcher.txt` (tasks: `startup-and-imports`)
- `/Users/alec/source/agent-memory/projects/varde-py/working/plans/2026-10-14-varde-python-port/evidence/toz-latency/results/packaging.json` (tasks: `packaging-startup-compare`)
- `/Users/alec/source/agent-memory/projects/varde-py/working/plans/2026-10-14-varde-python-port/evidence/toz-latency/results/phases.json` (tasks: `profile-phases`)
- `/Users/alec/source/agent-memory/projects/varde-py/working/plans/2026-10-14-varde-python-port/evidence/toz-latency/results/startup.json` (tasks: `startup-and-imports`)
- `/Users/alec/source/agent-memory/projects/varde-py/working/plans/2026-10-14-varde-python-port/evidence/toz-latency/results/store.json` (tasks: `store-open-and-write`)
- `toz/src/varde_toz/__init__.py` (tasks: `startup-and-imports`)
- `toz/src/varde_toz/__main__.py` (tasks: `startup-and-imports`)
- `toz/src/varde_toz/_core/redact.py` (tasks: `chunk-redact-algorithms`)
- `toz/src/varde_toz/capture.py` (tasks: `chunk-redact-algorithms`, `profile-phases`, `store-open-and-write`)
- `toz/src/varde_toz/chunk.py` (tasks: `chunk-redact-algorithms`, `profile-phases`)
- `toz/src/varde_toz/cli.py` (tasks: `startup-and-imports`)
- `toz/src/varde_toz/commands/event_note.py` (tasks: `profile-phases`, `store-open-and-write`)
- `toz/src/varde_toz/config.py` (tasks: `profile-phases`, `startup-and-imports`)
- `toz/src/varde_toz/daemon/` (tasks: `daemon-prototype`)
- `toz/src/varde_toz/hook.py` (tasks: `profile-phases`, `startup-and-imports`)
- `toz/src/varde_toz/hook_input/` (tasks: `startup-and-imports`)
- `toz/src/varde_toz/hook_main.py` (tasks: `startup-and-imports`)
- `toz/src/varde_toz/phase_trace.py` (tasks: `profile-phases`)
- `toz/src/varde_toz/project.py` (tasks: `profile-phases`, `store-open-and-write`)
- `toz/src/varde_toz/redact_toz.py` (tasks: `chunk-redact-algorithms`, `profile-phases`)
- `toz/src/varde_toz/store.py` (tasks: `profile-phases`, `store-open-and-write`)
- `toz/src/varde_toz/strategies.py` (tasks: `chunk-redact-algorithms`)
- `toz/src/varde_toz/streaming.py` (tasks: `chunk-redact-algorithms`)
- `toz/tests/test_algorithms.py` (tasks: `chunk-redact-algorithms`)
- `toz/tests/test_daemon.py` (tasks: `daemon-prototype`)
- `toz/tests/test_hook_startup.py` (tasks: `startup-and-imports`)
- `toz/tests/test_phase_marks.py` (tasks: `profile-phases`)
- `toz/tests/test_store_open.py` (tasks: `store-open-and-write`)

### `toz-perf`

- `toz/scripts/toz-latency/profile_phases.py` (tasks: `reprofile-phases`)
- `/Users/alec/source/agent-memory/projects/varde-py/working/plans/2026-10-14-varde-python-port/evidence/toz-perf/baseline.md` (tasks: `rebaseline`)
- `/Users/alec/source/agent-memory/projects/varde-py/working/plans/2026-10-14-varde-python-port/evidence/toz-perf/daemon-decision.md` (tasks: `daemon-decision`)
- `/Users/alec/source/agent-memory/projects/varde-py/working/plans/2026-10-14-varde-python-port/evidence/toz-perf/outlier-1mib.md` (tasks: `fix-command-pathology`)
- `toz/scripts/toz-perf/perf_run.py` (tasks: `load-recording-harness`)
- `/Users/alec/source/agent-memory/projects/varde-py/working/plans/2026-10-14-varde-python-port/evidence/toz-perf/phases-v2.md` (tasks: `reprofile-phases`)
- `toz/scripts/toz-perf/protocol.md` (tasks: `load-recording-harness`)
- `/Users/alec/source/agent-memory/projects/varde-py/working/plans/2026-10-14-varde-python-port/evidence/toz-perf/report.md` (tasks: `final-measurement`)
- `/Users/alec/source/agent-memory/projects/varde-py/working/plans/2026-10-14-varde-python-port/evidence/toz-perf/results/baseline.json` (tasks: `rebaseline`)
- `/Users/alec/source/agent-memory/projects/varde-py/working/plans/2026-10-14-varde-python-port/evidence/toz-perf/results/daemon-recheck.json` (tasks: `daemon-decision`)
- `/Users/alec/source/agent-memory/projects/varde-py/working/plans/2026-10-14-varde-python-port/evidence/toz-perf/results/final.json` (tasks: `final-measurement`)
- `/Users/alec/source/agent-memory/projects/varde-py/working/plans/2026-10-14-varde-python-port/evidence/toz-perf/results/large.json` (tasks: `optimize-large-payloads`)
- `/Users/alec/source/agent-memory/projects/varde-py/working/plans/2026-10-14-varde-python-port/evidence/toz-perf/results/outlier.json` (tasks: `fix-command-pathology`)
- `toz/tests/fixtures/phases-v2.json` (tasks: `reprofile-phases`)
- `/Users/alec/source/agent-memory/projects/varde-py/working/plans/2026-10-14-varde-python-port/evidence/toz-perf/results/small.json` (tasks: `optimize-small-payload-startup`)
- `toz/src/varde_toz/__init__.py` (tasks: `optimize-small-payload-startup`)
- `toz/src/varde_toz/_core/redact.py` (tasks: `optimize-large-payloads`)
- `toz/src/varde_toz/capture.py` (tasks: `optimize-large-payloads`, `optimize-small-payload-startup`, `reprofile-phases`)
- `toz/src/varde_toz/chunk.py` (tasks: `optimize-large-payloads`, `reprofile-phases`)
- `toz/src/varde_toz/cli.py` (tasks: `optimize-small-payload-startup`)
- `toz/src/varde_toz/commands/event_note.py` (tasks: `optimize-small-payload-startup`, `reprofile-phases`)
- `toz/src/varde_toz/config.py` (tasks: `optimize-small-payload-startup`, `reprofile-phases`)
- `toz/src/varde_toz/hook.py` (tasks: `fix-command-pathology`, `optimize-large-payloads`, `optimize-small-payload-startup`, `reprofile-phases`)
- `toz/src/varde_toz/hook_input/` (tasks: `fix-command-pathology`, `optimize-small-payload-startup`)
- `toz/src/varde_toz/phase_trace.py` (tasks: `reprofile-phases`)
- `toz/src/varde_toz/project.py` (tasks: `optimize-small-payload-startup`, `reprofile-phases`)
- `toz/src/varde_toz/redact_toz.py` (tasks: `optimize-large-payloads`, `reprofile-phases`)
- `toz/src/varde_toz/store.py` (tasks: `optimize-large-payloads`, `reprofile-phases`)
- `toz/src/varde_toz/strategies.py` (tasks: `optimize-large-payloads`)
- `toz/src/varde_toz/streaming.py` (tasks: `optimize-large-payloads`)
- `toz/tests/test_large_payload_budget.py` (tasks: `fix-command-pathology`)
- `toz/tests/test_perf_algorithms.py` (tasks: `optimize-large-payloads`)
- `toz/tests/test_phase_marks.py` (tasks: `reprofile-phases`)
- `dev/scripts/quiet_check.py` (tasks: `load-recording-harness`)
- `dev/scripts/test_quiet_check.py` (tasks: `load-recording-harness`)
- `dev/scripts/with-lock.sh` (tasks: `load-recording-harness`)

### `workflow`

- `workflow/pyproject.toml` (tasks: `cli-and-help`)
- `workflow/src/varde_workflow/artifact.py` (tasks: `artifact-schema-graph`)
- `workflow/src/varde_workflow/blocks.py` (tasks: `instructions`)
- `workflow/src/varde_workflow/cli.py` (tasks: `cli-and-help`)
- `workflow/src/varde_workflow/commands/__init__.py` (tasks: `base`)
- `workflow/src/varde_workflow/commands/check_task_ownership.py` (tasks: `ownership-and-waves`)
- `workflow/src/varde_workflow/commands/common.py` (tasks: `base`)
- `workflow/src/varde_workflow/commands/conclude.py` (tasks: `lifecycle`)
- `workflow/src/varde_workflow/commands/create.py` (tasks: `lifecycle`)
- `workflow/src/varde_workflow/commands/delete.py` (tasks: `lifecycle`)
- `workflow/src/varde_workflow/commands/distill.py` (tasks: `lifecycle`)
- `workflow/src/varde_workflow/commands/error.py` (tasks: `base`)
- `workflow/src/varde_workflow/commands/execution_wave.py` (tasks: `ownership-and-waves`)
- `workflow/src/varde_workflow/commands/graph.py` (tasks: `artifact-schema-graph`)
- `workflow/src/varde_workflow/commands/hook.py` (tasks: `inbox`)
- `workflow/src/varde_workflow/commands/input.py` (tasks: `base`)
- `workflow/src/varde_workflow/commands/instructions.py` (tasks: `instructions`)
- `workflow/src/varde_workflow/commands/lint.py` (tasks: `artifact-schema-graph`)
- `workflow/src/varde_workflow/commands/list.py` (tasks: `lifecycle`)
- `workflow/src/varde_workflow/commands/maps.py` (tasks: `lifecycle`)
- `workflow/src/varde_workflow/commands/msg.py` (tasks: `inbox`)
- `workflow/src/varde_workflow/commands/now.py` (tasks: `status-readiness-now`)
- `workflow/src/varde_workflow/commands/owner.py` (tasks: `lifecycle`)
- `workflow/src/varde_workflow/commands/readiness.py` (tasks: `status-readiness-now`)
- `workflow/src/varde_workflow/commands/search.py` (tasks: `lifecycle`)
- `workflow/src/varde_workflow/commands/set_field.py` (tasks: `lifecycle`)
- `workflow/src/varde_workflow/commands/show.py` (tasks: `lifecycle`)
- `workflow/src/varde_workflow/commands/status.py` (tasks: `status-readiness-now`)
- `workflow/src/varde_workflow/commands/update.py` (tasks: `lifecycle`)
- `workflow/src/varde_workflow/commands/validate.py` (tasks: `artifact-schema-graph`)
- `workflow/src/varde_workflow/commands/wake.py` (tasks: `inbox`)
- `workflow/src/varde_workflow/commands/watch.py` (tasks: `watch`)
- `workflow/src/varde_workflow/commands/watch_block.py` (tasks: `watch`)
- `workflow/src/varde_workflow/commands/watch_cache.py` (tasks: `watch`)
- `workflow/src/varde_workflow/commands/watch_state.py` (tasks: `watch`)
- `workflow/src/varde_workflow/conclusion.py` (tasks: `lifecycle`)
- `workflow/src/varde_workflow/errors.py` (tasks: `base`)
- `workflow/src/varde_workflow/execution_wave.py` (tasks: `ownership-and-waves`)
- `workflow/src/varde_workflow/execution_wave_paths.py` (tasks: `ownership-and-waves`)
- `workflow/src/varde_workflow/execution_wave_tools.py` (tasks: `ownership-and-waves`)
- `workflow/src/varde_workflow/graph.py` (tasks: `artifact-schema-graph`)
- `workflow/src/varde_workflow/help/**` (tasks: `cli-and-help`)
- `workflow/src/varde_workflow/help/.gitkeep` (tasks: `stub-manifest`)
- `workflow/src/varde_workflow/inbox.py` (tasks: `inbox`)
- `workflow/src/varde_workflow/module.py` (tasks: `cli-and-help`, `stub-manifest`)
- `workflow/src/varde_workflow/output.py` (tasks: `base`)
- `workflow/src/varde_workflow/schema.py` (tasks: `artifact-schema-graph`)
- `workflow/src/varde_workflow/task_ownership.py` (tasks: `ownership-and-waves`)
- `workflow/tests/test_artifact.py` (tasks: `artifact-schema-graph`)
- `workflow/tests/test_base.py` (tasks: `base`)
- `workflow/tests/test_inbox.py` (tasks: `inbox`)
- `workflow/tests/test_instructions.py` (tasks: `instructions`)
- `workflow/tests/test_lifecycle.py` (tasks: `lifecycle`)
- `workflow/tests/test_status.py` (tasks: `status-readiness-now`)
- `workflow/tests/test_watch.py` (tasks: `watch`)
- `workflow/tests/test_waves.py` (tasks: `ownership-and-waves`)

## Duplicate ownership claims

Every path below is claimed by multiple plans or by core and another plan. These need explicit ownership resolution during integration; this task records the claims without changing the plans.

| Path | Claiming plans and tasks |
|---|---|
| `README.md` | `cutover`: `docs-skills-update`; `spikes`: `repo-setup` |
| `toz/scripts/toz-latency/profile_phases.py` | `toz-latency`: `profile-phases`; `toz-perf`: `reprofile-phases` |
| `pyproject.toml` | `core`: `workspace-skeleton`; `spikes`: `repo-setup`; `toz`: `skeleton-core` |
| `code/src/varde_code/cli_edit.py` | `code-scan`: `cli-wire`, `stub-manifest`; `core`: `workspace-skeleton` |
| `code/src/varde_code/cli_extract.py` | `code-extract`: `extract-cli`, `stub-manifest`; `core`: `workspace-skeleton` |
| `code/src/varde_code/cli_index.py` | `code-index`: `cli-index`, `stub-manifest`; `core`: `workspace-skeleton` |
| `code/src/varde_code/cli_query.py` | `code-query`: `cli-query`, `stub-manifest`; `core`: `workspace-skeleton` |
| `code/src/varde_code/cli_scan.py` | `code-scan`: `cli-wire`, `stub-manifest`; `core`: `workspace-skeleton` |
| `learn/pyproject.toml` | `core`: `workspace-skeleton`; `doc`: `cli-and-help` |
| `learn/src/varde_learn/docs/help/.gitkeep` | `core`: `workspace-skeleton`; `doc`: `stub-manifest` |
| `learn/src/varde_learn/docs/module.py` | `core`: `workspace-skeleton`; `doc`: `cli-and-help`, `stub-manifest` |
| `learn/src/varde_learn/loop/cli_diagnose.py` | `core`: `workspace-skeleton`; `learn-diagnose`: `cli-diagnose`, `stub-manifest` |
| `learn/src/varde_learn/loop/cli_friction.py` | `core`: `workspace-skeleton`; `learn-friction`: `cli-friction`, `stub-manifest` |
| `learn/pyproject.toml` | `core`: `workspace-skeleton`; `knowledge`: `cli-and-help` |
| `learn/src/varde_learn/knowledge/help/.gitkeep` | `core`: `workspace-skeleton`; `knowledge`: `stub-manifest` |
| `learn/src/varde_learn/knowledge/module.py` | `core`: `workspace-skeleton`; `knowledge`: `cli-and-help`, `stub-manifest` |
| `toz/pyproject.toml` | `toz`: `skeleton-core`; `toz-adopt`: `module-contract` |
| `toz/src/varde_toz/__init__.py` | `toz`: `skeleton-core`; `toz-latency`: `startup-and-imports`; `toz-perf`: `optimize-small-payload-startup` |
| `toz/src/varde_toz/_core/redact.py` | `toz-latency`: `chunk-redact-algorithms`; `toz-perf`: `optimize-large-payloads` |
| `toz/src/varde_toz/capture.py` | `toz`: `capture-profiles`; `toz-latency`: `chunk-redact-algorithms`, `profile-phases`, `store-open-and-write`; `toz-perf`: `optimize-large-payloads`, `optimize-small-payload-startup`, `reprofile-phases` |
| `toz/src/varde_toz/chunk.py` | `toz`: `store-fts5`; `toz-latency`: `chunk-redact-algorithms`, `profile-phases`; `toz-perf`: `optimize-large-payloads`, `reprofile-phases` |
| `toz/src/varde_toz/cli.py` | `toz`: `skeleton-core`; `toz-latency`: `startup-and-imports`; `toz-perf`: `optimize-small-payload-startup` |
| `toz/src/varde_toz/commands/event_note.py` | `toz`: `hook-dispatch`; `toz-latency`: `profile-phases`, `store-open-and-write`; `toz-perf`: `optimize-small-payload-startup`, `reprofile-phases` |
| `toz/src/varde_toz/config.py` | `toz`: `skeleton-core`; `toz-adopt`: `swap-shim`; `toz-latency`: `profile-phases`, `startup-and-imports`; `toz-perf`: `optimize-small-payload-startup`, `reprofile-phases` |
| `toz/src/varde_toz/hook.py` | `toz`: `hook-dispatch`; `toz-latency`: `profile-phases`, `startup-and-imports`; `toz-perf`: `fix-command-pathology`, `optimize-large-payloads`, `optimize-small-payload-startup`, `reprofile-phases` |
| `toz/src/varde_toz/hook_input/` | `toz`: `hook-dispatch`; `toz-latency`: `startup-and-imports`; `toz-perf`: `fix-command-pathology`, `optimize-small-payload-startup` |
| `toz/src/varde_toz/phase_trace.py` | `toz-latency`: `profile-phases`; `toz-perf`: `reprofile-phases` |
| `toz/src/varde_toz/project.py` | `toz`: `store-fts5`; `toz-latency`: `profile-phases`, `store-open-and-write`; `toz-perf`: `optimize-small-payload-startup`, `reprofile-phases` |
| `toz/src/varde_toz/redact_toz.py` | `toz`: `capture-profiles`; `toz-adopt`: `swap-shim`; `toz-latency`: `chunk-redact-algorithms`, `profile-phases`; `toz-perf`: `optimize-large-payloads`, `reprofile-phases` |
| `toz/src/varde_toz/store.py` | `toz`: `store-fts5`; `toz-adopt`: `swap-shim`; `toz-latency`: `profile-phases`, `store-open-and-write`; `toz-perf`: `optimize-large-payloads`, `reprofile-phases` |
| `toz/src/varde_toz/strategies.py` | `toz`: `capture-profiles`; `toz-latency`: `chunk-redact-algorithms`; `toz-perf`: `optimize-large-payloads` |
| `toz/src/varde_toz/streaming.py` | `toz`: `capture-profiles`; `toz-latency`: `chunk-redact-algorithms`; `toz-perf`: `optimize-large-payloads` |
| `toz/tests/test_core_shim.py` | `toz`: `skeleton-core`; `toz-adopt`: `swap-shim` |
| `toz/tests/test_phase_marks.py` | `toz-latency`: `profile-phases`; `toz-perf`: `reprofile-phases` |
| `workflow/pyproject.toml` | `core`: `workspace-skeleton`; `workflow`: `cli-and-help` |
| `workflow/src/varde_workflow/help/.gitkeep` | `core`: `workspace-skeleton`; `workflow`: `stub-manifest` |
| `workflow/src/varde_workflow/module.py` | `core`: `workspace-skeleton`; `workflow`: `cli-and-help`, `stub-manifest` |
| `app/pyproject.toml` | `app-shell`: `uv-tool-install`; `core`: `workspace-skeleton` |
| `app/src/varde/help/.gitkeep` | `app-shell`: `stub-manifest`; `core`: `workspace-skeleton` |
| `app/src/varde/module.py` | `app-shell`: `stub-manifest`; `core`: `workspace-skeleton` |
