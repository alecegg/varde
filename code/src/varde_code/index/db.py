"""SQLite schema and connection setup for the derived code index."""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

SCHEMA_VERSION = 20
TABLES = (
    "graph_cache",
    "slice_state",
    "slice_meta",
    "community_members",
    "clone_band_members",
    "function_metrics",
    "lexical",
    "resolved_edges",
    "diagnostics",
    "symbols",
    "entities",
    "communities",
    "clone_bands",
    "files",
)

SCHEMA_DDL = r"""CREATE TABLE files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT NOT NULL UNIQUE,
    -- Derived from `path` alone (test/tests/__tests__/spec/specs/fixtures
    -- directory segments, or a .test./.spec. filename infix), so it's a
    -- SQLite generated column rather than a value threaded through
    -- extract/persist: no extraction-time work, and it can't drift out of
    -- sync with path. Shared by every scan rule that wants to exclude
    -- test/fixture code from a structural-smell signal (see
    -- low_fan_in_high_fan_out_file.toml, circular_import.toml,
    -- debug_statement_strict.toml) instead of each rule reimplementing its
    -- own path heuristic.
    is_test_path BOOLEAN GENERATED ALWAYS AS (
        path LIKE '%/test/%' OR path LIKE '%/tests/%'
        OR path LIKE '%/__tests__/%' OR path LIKE '%/spec/%' OR path LIKE '%/specs/%'
        OR path LIKE '%/fixture/%' OR path LIKE '%/fixtures/%'
        OR path LIKE '%.test.%' OR path LIKE '%.spec.%'
        OR path LIKE 'test/%' OR path LIKE 'tests/%'
        -- Go convention: `foo_test.go` files live alongside the code they
        -- test, not under a `test/`-segment directory.
        OR path LIKE '%\_test.go' ESCAPE '\'
        -- Python convention: `test_foo.py` / `foo_test.py` at any depth.
        OR path LIKE '%/test\_%.py' ESCAPE '\' OR path LIKE 'test\_%.py' ESCAPE '\'
        OR path LIKE '%\_test.py' ESCAPE '\'
        -- Java/Kotlin convention: `FooTest.java` / `FooTests.java` outside a
        -- `test/`-segment directory (e.g. flat single-module layouts).
        OR path LIKE '%Test.java' OR path LIKE '%Tests.java'
        OR path LIKE '%Test.kt' OR path LIKE '%Tests.kt'
        -- C#/.NET convention: `FooTests.cs` files, plus the dominant .NET
        -- solution layout of a separate `<Project>.Tests` test project. The
        -- `.Tests/` directory segment isn't caught by `%/tests/%` above
        -- (the separator before `Tests` is `.`, not `/`), so match the
        -- `.<suffix>/` project-dir forms explicitly. Bounding with the `.`
        -- avoids false hits like `Contests/` that a bare `%Tests/%` would take.
        OR path LIKE '%Test.cs' OR path LIKE '%Tests.cs'
        OR path LIKE '%.Test/%' OR path LIKE '%.Tests/%'
        OR path LIKE '%.UnitTests/%' OR path LIKE '%.IntegrationTests/%'
        OR path LIKE '%.FunctionalTests/%' OR path LIKE '%.AcceptanceTests/%'
        -- C++ convention: GoogleTest `foo_test.cc`/`.cpp`/`.cxx` files live
        -- alongside the code they test (like Go's `_test.go`), not under a
        -- `test/`-segment directory. The escaped `_` requires a literal
        -- underscore, so `latest.cpp` is not swept up.
        OR path LIKE '%\_test.cc' ESCAPE '\' OR path LIKE '%\_test.cpp' ESCAPE '\'
        OR path LIKE '%\_test.cxx' ESCAPE '\'
        -- Solidity convention: Foundry test contracts use the `.t.sol` double
        -- extension (`Counter.t.sol`); this is the runner's discovery signal
        -- and files may sit outside a `test/` dir. Scripts use `.s.sol` and
        -- are intentionally left unmatched.
        OR path LIKE '%.t.sol'
        -- Bash convention: Bats test files carry the `.bats` extension.
        OR path LIKE '%.bats'
        -- Ruby convention: RSpec `foo_spec.rb` / Minitest `foo_test.rb`
        -- outside the usual `spec/`/`test/` dirs (already caught above). The
        -- escaped `_` keeps `latest.rb` out.
        OR path LIKE '%\_spec.rb' ESCAPE '\' OR path LIKE '%\_test.rb' ESCAPE '\'
        -- Rust convention: a unit-test submodule extracted to its own file is
        -- named `test.rs` / `tests.rs` (declared `mod test;` / `mod tests;`),
        -- sitting beside the code it tests rather than under a `test/`-segment
        -- dir. The `/test/%` rule above only catches a *directory* named test,
        -- so a *file* `.../foo/test.rs` slips through. The `/` anchor before
        -- `test.rs`/`tests.rs` keeps production files like `latest.rs` /
        -- `contest.rs` / `test_utils.rs` out.
        OR path LIKE '%/test.rs' OR path LIKE '%/tests.rs'
        OR path LIKE 'test.rs' OR path LIKE 'tests.rs'
    ) STORED,
    -- Non-test tooling that legitimately behaves differently from shipped
    -- production code: benchmark harnesses, build/dev scripts, and docs
    -- generators. `console-log-strict`/`duplicate-code-clone` treat this the
    -- same as `is_test_path` — see debug_statement_strict.toml and
    -- duplicate_code_clone.toml — kept as a separate column instead of
    -- folding into `is_test_path` so "is this a test" and "is this shipped"
    -- stay independently queryable.
    is_tooling_path BOOLEAN GENERATED ALWAYS AS (
        path LIKE '%/bench/%' OR path LIKE '%/benches/%' OR path LIKE '%/benchmark/%' OR path LIKE '%/benchmarks/%'
        OR path LIKE 'bench/%' OR path LIKE 'benches/%'
        OR path LIKE '%/scripts/%' OR path LIKE '%/script/%' OR path LIKE 'scripts/%' OR path LIKE 'script/%'
        OR path LIKE '%/docs/%' OR path LIKE 'docs/%'
        OR path LIKE '%/.claude/%' OR path LIKE '.claude/%'
    ) STORED,
    mtime INTEGER NOT NULL DEFAULT 0,
    size INTEGER NOT NULL DEFAULT 0,
    content_hash TEXT NOT NULL DEFAULT '',
    complexity INTEGER,
    churn INTEGER,
    fan_in INTEGER NOT NULL DEFAULT 0,
    fan_out INTEGER NOT NULL DEFAULT 0,
    community_id INTEGER,
    rev INTEGER NOT NULL DEFAULT 0,
    edges_built_rev INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE entities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind INTEGER NOT NULL,
    name TEXT NOT NULL,
    file_id INTEGER NOT NULL,
    start_byte INTEGER NOT NULL,
    end_byte INTEGER NOT NULL,
    start_line INTEGER NOT NULL,
    start_col INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    end_col INTEGER NOT NULL,
    enclosing_function TEXT,
    method TEXT,
    path TEXT,
    status TEXT,
    body_shape TEXT,
    body_minhash BLOB,
    is_async BOOLEAN,
    is_test BOOLEAN NOT NULL DEFAULT 0,
    -- Function entities only: name of the immediately enclosing
    -- class/interface/impl-target type, when the function is a method.
    -- Drives SOLID class-membership rules (interface method-coverage,
    -- fat-interface member counts) that need "which methods belong to
    -- this type" without span-containment math.
    owner_type TEXT
);

CREATE TABLE symbols (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind INTEGER NOT NULL,
    name TEXT NOT NULL,
    file_id INTEGER NOT NULL,
    start_byte INTEGER NOT NULL,
    end_byte INTEGER NOT NULL,
    start_line INTEGER NOT NULL,
    start_col INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    end_col INTEGER NOT NULL
);

CREATE TABLE diagnostics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    -- NULL for a directory-traversal failure: the walk never reached a file,
    -- so there is no `files` row to key it to. `path` is the locator instead,
    -- and is required for every diagnostic.
    file_id INTEGER,
    path TEXT NOT NULL,
    message TEXT NOT NULL,
    severity TEXT NOT NULL
);

CREATE TABLE function_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER NOT NULL,
    identity TEXT NOT NULL,
    name TEXT NOT NULL,
    owner_type TEXT,
    start_byte INTEGER NOT NULL,
    end_byte INTEGER NOT NULL,
    start_line INTEGER NOT NULL,
    start_col INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    end_col INTEGER NOT NULL,
    cyclomatic INTEGER NOT NULL,
    cognitive INTEGER NOT NULL,
    max_nesting INTEGER NOT NULL,
    line_span INTEGER NOT NULL,
    byte_size INTEGER NOT NULL,
    confidence TEXT NOT NULL,
    confidence_reasons TEXT NOT NULL,
    metric_version INTEGER NOT NULL
);

CREATE TABLE resolved_edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_file_id INTEGER NOT NULL,
    to_file_id INTEGER,
    kind INTEGER NOT NULL,
    resolved INTEGER NOT NULL,
    from_entity_id INTEGER,
    to_entity_id INTEGER
);

CREATE TABLE communities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    label TEXT NOT NULL
);

CREATE TABLE community_members (
    community_id INTEGER NOT NULL,
    file_id INTEGER NOT NULL
);

CREATE TABLE clone_bands (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    label TEXT NOT NULL
);

CREATE TABLE clone_band_members (
    band_id INTEGER NOT NULL,
    entity_id INTEGER NOT NULL
);

CREATE TABLE slice_state (
    slice TEXT PRIMARY KEY,
    built_through_rev INTEGER NOT NULL,
    schema_version INTEGER NOT NULL
);

CREATE TABLE slice_meta (
    key TEXT PRIMARY KEY,
    value INTEGER NOT NULL
);

CREATE TABLE graph_cache (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    blob BLOB NOT NULL,
    rev INTEGER NOT NULL
);"""

INDEX_DDL = r"""CREATE INDEX idx_resolved_edges_from ON resolved_edges(from_file_id);
CREATE INDEX idx_resolved_edges_to ON resolved_edges(to_file_id);
CREATE INDEX idx_resolved_edges_from_entity ON resolved_edges(from_entity_id);
CREATE INDEX idx_resolved_edges_to_entity ON resolved_edges(to_entity_id);
CREATE INDEX idx_entities_file ON entities(file_id);
CREATE INDEX idx_symbols_file ON symbols(file_id);
CREATE INDEX idx_function_metrics_file ON function_metrics(file_id);
CREATE INDEX idx_function_metrics_identity ON function_metrics(identity);
CREATE INDEX idx_entities_name ON entities(name);
CREATE INDEX idx_symbols_name ON symbols(name);"""


def build_version_fingerprint() -> int:
    """Return a stable signed 64-bit fingerprint of this package's sources."""
    package = Path(__file__).resolve().parent
    digest = hashlib.blake2b(digest_size=8)
    for source in sorted(package.rglob("*.py")):
        digest.update(source.relative_to(package).as_posix().encode())
        digest.update(source.read_bytes())
    return int.from_bytes(digest.digest(), "big", signed=True)


def open_database(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA page_size=16384")
    connection.execute("PRAGMA synchronous=OFF")
    connection.execute("PRAGMA journal_mode=OFF")
    connection.execute("PRAGMA locking_mode=EXCLUSIVE")
    return connection


def initialize(path: Path) -> sqlite3.Connection:
    """Create (or replace) the schema at path and return its connection."""
    connection = open_database(path)
    for table in TABLES:
        connection.execute(f"DROP TABLE IF EXISTS {table}")
    connection.executescript(SCHEMA_DDL)
    try:
        connection.execute(
            "CREATE VIRTUAL TABLE lexical USING fts5(name, doc, body, "
            "content='', contentless_delete=1)"
        )
    except sqlite3.OperationalError as error:
        message = str(error).lower()
        if "fts5" not in message and "unrecognized option" not in message:
            raise
    connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
    connection.executescript(INDEX_DDL)
    connection.execute(
        "INSERT INTO slice_meta(key, value) VALUES ('build_version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (build_version_fingerprint(),),
    )
    connection.commit()
    return connection
