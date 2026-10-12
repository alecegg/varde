use rusqlite::Connection;
use tempfile::TempDir;
use varde_code::{
    build, db,
    slice::{Scope, Slice, ensure_fresh},
};
use varde_core::write_meter::{WriteMeter, available};

static ENV_LOCK: std::sync::Mutex<()> = std::sync::Mutex::new(());

struct Fixture {
    _tmp: TempDir,
    repo: std::path::PathBuf,
    previous: Option<std::ffi::OsString>,
}
impl Fixture {
    fn new() -> Self {
        let tmp = tempfile::tempdir().unwrap();
        let repo = tmp.path().join("repo");
        let config = tmp.path().join("config");
        std::fs::create_dir_all(&repo).unwrap();
        std::fs::create_dir_all(&config).unwrap();
        std::fs::write(
            repo.join("main.py"),
            "def alpha():\n    return 1\n\ndef beta():\n    return alpha()\n",
        )
        .unwrap();
        let previous = std::env::var_os("VARDE_CONFIG_DIR");
        unsafe {
            std::env::set_var("VARDE_CONFIG_DIR", &config);
        }
        Self {
            _tmp: tmp,
            repo,
            previous,
        }
    }
    fn db(&self) -> std::path::PathBuf {
        db::path::repo_db_path(&self.repo)
    }
    fn refresh(&self) {
        ensure_fresh(
            &[
                Slice::Raw,
                Slice::Churn,
                Slice::Imports,
                Slice::Edges,
                Slice::Global,
            ],
            self.repo.to_str().unwrap(),
            &Scope::Repo,
        )
        .unwrap();
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        match self.previous.take() {
            Some(v) => unsafe { std::env::set_var("VARDE_CONFIG_DIR", v) },
            None => unsafe { std::env::remove_var("VARDE_CONFIG_DIR") },
        }
    }
}

fn ids(conn: &Connection, table: &str) -> Vec<(String, i64)> {
    conn.prepare(&format!("SELECT name,id FROM {table} ORDER BY name"))
        .unwrap()
        .query_map([], |r| Ok((r.get(0)?, r.get(1)?)))
        .unwrap()
        .map(Result::unwrap)
        .collect()
}

fn labeled_ids(conn: &Connection, table: &str) -> Vec<(String, i64)> {
    conn.prepare(&format!("SELECT label,id FROM {table} ORDER BY label"))
        .unwrap()
        .query_map([], |r| Ok((r.get(0)?, r.get(1)?)))
        .unwrap()
        .map(Result::unwrap)
        .collect()
}

fn function_ids(conn: &Connection) -> Vec<(String, i64)> {
    conn.prepare("SELECT name,id FROM entities WHERE kind=0 ORDER BY name")
        .unwrap()
        .query_map([], |r| Ok((r.get(0)?, r.get(1)?)))
        .unwrap()
        .map(Result::unwrap)
        .collect()
}

fn edge_set(
    conn: &Connection,
) -> Vec<(
    String,
    Option<String>,
    Option<String>,
    Option<String>,
    i64,
    i64,
)> {
    let mut rows = conn
        .prepare(
            "SELECT ff.path, fe.name, tf.path, te.name, e.kind, e.resolved
        FROM resolved_edges e
        JOIN files ff ON ff.id=e.from_file_id
        LEFT JOIN entities fe ON fe.id=e.from_entity_id
        LEFT JOIN files tf ON tf.id=e.to_file_id
        LEFT JOIN entities te ON te.id=e.to_entity_id",
        )
        .unwrap()
        .query_map([], |r| {
            Ok((
                r.get(0)?,
                r.get(1)?,
                r.get(2)?,
                r.get(3)?,
                r.get(4)?,
                r.get(5)?,
            ))
        })
        .unwrap()
        .map(Result::unwrap)
        .collect::<Vec<_>>();
    rows.sort();
    rows
}

fn qi_row_counts(conn: &Connection) -> (i64, i64, i64) {
    conn.query_row(
        "SELECT (SELECT count(*) FROM entities),
                (SELECT count(*) FROM symbols),
                (SELECT count(*) FROM resolved_edges)",
        [],
        |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
    )
    .unwrap()
}

fn qi_extraction_counts(sources: &[String]) -> (i64, i64) {
    use ast_grep_language::SupportLang;
    use varde_code::{extract, model::EntityKind, parse};

    sources.iter().fold((0, 0), |(entities, symbols), source| {
        let parsed = parse::parse_source(&SupportLang::Swift, source);
        let extracted = extract::extract(&parsed, 0);
        let kept_entities = extracted
            .entities
            .iter()
            .filter(|entity| {
                !matches!(
                    entity.kind,
                    EntityKind::Literal
                        | EntityKind::MemberAccess
                        | EntityKind::Catch
                        | EntityKind::Throw
                )
            })
            .count() as i64;
        (
            entities + kept_entities,
            symbols + extracted.symbols.len() as i64,
        )
    })
}

fn edge_row_changes(conn: &Connection) -> i64 {
    conn.query_row("SELECT changes FROM edge_write_count", [], |r| r.get(0))
        .unwrap()
}

fn global_rows(conn: &Connection) -> std::collections::BTreeSet<String> {
    let mut rows = std::collections::BTreeSet::new();
    for sql in [
        "SELECT 'c:'||label FROM communities",
        "SELECT 'cm:'||c.label||':'||f.path FROM community_members cm JOIN communities c ON c.id=cm.community_id JOIN files f ON f.id=cm.file_id",
        "SELECT 'b:'||label FROM clone_bands",
        "SELECT 'bm:'||cb.label||':'||f.path||':'||e.start_byte||':'||e.end_byte||':'||e.kind||':'||e.name FROM clone_band_members cbm JOIN clone_bands cb ON cb.id=cbm.band_id JOIN entities e ON e.id=cbm.entity_id JOIN files f ON f.id=e.file_id",
        "SELECT 'f:'||path||':'||coalesce(c.label,'')||':'||fan_in||':'||fan_out FROM files LEFT JOIN communities c ON c.id=files.community_id",
    ] {
        let mut stmt = conn.prepare(sql).unwrap();
        rows.extend(
            stmt.query_map([], |r| r.get::<_, String>(0))
                .unwrap()
                .map(Result::unwrap),
        );
    }
    rows
}

fn qi_full_rows(conn: &Connection) -> Vec<String> {
    let mut rows = Vec::new();
    for (table, sql) in [
        (
            "entities",
            "SELECT f.path,e.kind,e.name,e.start_byte,e.end_byte,e.start_line,e.start_col,
                    e.end_line,e.end_col,e.enclosing_function,e.method,e.path,e.status,
                    e.body_shape,e.body_minhash,e.is_async,e.is_test,e.owner_type
             FROM entities e JOIN files f ON f.id=e.file_id",
        ),
        (
            "symbols",
            "SELECT f.path,s.kind,s.name,s.start_byte,s.end_byte,s.start_line,s.start_col,
                    s.end_line,s.end_col
             FROM symbols s JOIN files f ON f.id=s.file_id",
        ),
        (
            "diagnostics",
            "SELECT d.path,d.message,d.severity,coalesce(f.path,'')
             FROM diagnostics d LEFT JOIN files f ON f.id=d.file_id",
        ),
        (
            "function_metrics",
            "SELECT f.path,m.identity,m.name,m.owner_type,m.start_byte,m.end_byte,
                    m.start_line,m.start_col,m.end_line,m.end_col,m.cyclomatic,m.cognitive,
                    m.max_nesting,m.line_span,m.byte_size,m.confidence,m.confidence_reasons,
                    m.metric_version
             FROM function_metrics m JOIN files f ON f.id=m.file_id",
        ),
    ] {
        let mut stmt = conn.prepare(sql).unwrap();
        let column_count = stmt.column_count();
        rows.extend(
            stmt.query_map([], |row| {
                let values = (0..column_count)
                    .map(|index| row.get_ref(index).map(|value| format!("{value:?}")))
                    .collect::<rusqlite::Result<Vec<_>>>()?;
                Ok(format!("{table}:{values:?}"))
            })
            .unwrap()
            .map(Result::unwrap),
        );
    }
    rows.extend(
        edge_set(conn)
            .into_iter()
            .map(|row| format!("edge:{row:?}")),
    );
    rows.extend(
        global_rows(conn)
            .into_iter()
            .map(|row| format!("global:{row}")),
    );
    rows.sort();
    rows
}

#[test]
fn stable_ids_comment_edit_keeps_global_ids_and_graph_cache_blob() {
    let _guard = ENV_LOCK
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner);
    let f = Fixture::new();
    std::fs::write(f.repo.join("probe.rs"), "fn probe() {}\n").unwrap();
    f.refresh();
    let conn = Connection::open(f.db()).unwrap();
    let communities_before = labeled_ids(&conn, "communities");
    let bands_before = labeled_ids(&conn, "clone_bands");
    let file_communities_before: Vec<(String, Option<i64>)> = conn
        .prepare("SELECT path, community_id FROM files ORDER BY path")
        .unwrap()
        .query_map([], |r| Ok((r.get(0)?, r.get(1)?)))
        .unwrap()
        .map(Result::unwrap)
        .collect();
    conn.execute_batch(
        "CREATE TABLE graph_cache_blob_writes(n INTEGER); INSERT INTO graph_cache_blob_writes VALUES(0);
         CREATE TRIGGER count_graph_cache_blob_write AFTER UPDATE OF blob ON graph_cache
         BEGIN UPDATE graph_cache_blob_writes SET n=n+1; END;",
    )
    .unwrap();
    drop(conn);

    std::fs::write(
        f.repo.join("probe.rs"),
        "// stable id probe\nfn probe() {}\n",
    )
    .unwrap();
    f.refresh();

    let conn = Connection::open(f.db()).unwrap();
    assert_eq!(communities_before, labeled_ids(&conn, "communities"));
    assert_eq!(bands_before, labeled_ids(&conn, "clone_bands"));
    let file_communities_after: Vec<(String, Option<i64>)> = conn
        .prepare("SELECT path, community_id FROM files ORDER BY path")
        .unwrap()
        .query_map([], |r| Ok((r.get(0)?, r.get(1)?)))
        .unwrap()
        .map(Result::unwrap)
        .collect();
    assert_eq!(file_communities_before, file_communities_after);
    assert_eq!(
        conn.query_row("SELECT n FROM graph_cache_blob_writes", [], |r| r
            .get::<_, i64>(0))
            .unwrap(),
        0
    );
}

#[test]
fn stable_ids_singleton_community_survives_edit_and_disappears_on_delete() {
    let _guard = ENV_LOCK
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner);
    let f = Fixture::new();
    std::fs::write(f.repo.join("probe.rs"), "fn probe() {}\n").unwrap();
    build::run(f.repo.to_str().unwrap()).unwrap();

    let conn = Connection::open(f.db()).unwrap();
    let community_before: (i64, String) = conn
        .query_row(
            "SELECT c.id, c.label FROM communities c
             JOIN community_members cm ON cm.community_id=c.id
             JOIN files f ON f.id=cm.file_id WHERE f.path LIKE '%/probe.rs'",
            [],
            |row| Ok((row.get(0)?, row.get(1)?)),
        )
        .expect("isolated probe file should form a singleton community");
    assert_eq!(
        conn.query_row(
            "SELECT count(*) FROM community_members WHERE community_id=?1",
            [community_before.0],
            |row| row.get::<_, i64>(0),
        )
        .unwrap(),
        1,
        "probe community must be a singleton"
    );
    let file_community_before: Option<i64> = conn
        .query_row(
            "SELECT community_id FROM files WHERE path LIKE '%/probe.rs'",
            [],
            |row| row.get(0),
        )
        .unwrap();
    assert_eq!(file_community_before, Some(community_before.0));
    drop(conn);

    std::fs::write(f.repo.join("probe.rs"), "// edit\nfn probe() {}\n").unwrap();
    build::run(f.repo.to_str().unwrap()).unwrap();
    let conn = Connection::open(f.db()).unwrap();
    let community_after: (i64, String) = conn
        .query_row(
            "SELECT c.id, c.label FROM communities c
             JOIN community_members cm ON cm.community_id=c.id
             JOIN files f ON f.id=cm.file_id WHERE f.path LIKE '%/probe.rs'",
            [],
            |row| Ok((row.get(0)?, row.get(1)?)),
        )
        .unwrap();
    let file_community_after: Option<i64> = conn
        .query_row(
            "SELECT community_id FROM files WHERE path LIKE '%/probe.rs'",
            [],
            |row| row.get(0),
        )
        .unwrap();
    assert_eq!(community_after, community_before);
    assert_eq!(file_community_after, file_community_before);
    drop(conn);

    std::fs::remove_file(f.repo.join("probe.rs")).unwrap();
    build::run(f.repo.to_str().unwrap()).unwrap();
    let conn = Connection::open(f.db()).unwrap();
    let incremental = global_rows(&conn);
    drop(conn);
    build::run_with_force(f.repo.to_str().unwrap(), true).unwrap();
    let conn = Connection::open(f.db()).unwrap();
    assert_eq!(incremental, global_rows(&conn));
    assert!(!labeled_ids(&conn, "communities")
        .iter()
        .any(|(_, id)| *id == community_before.0));
}

#[test]
fn diff_write_global_edit_sequences_match_full_rewrite_and_noop_writes_zero_rows() {
    let _guard = ENV_LOCK
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner);
    let f = Fixture::new();
    std::fs::write(f.repo.join("lib.py"), "def helper():\n    return 1\n").unwrap();
    build::run(f.repo.to_str().unwrap()).unwrap();
    let edits: Vec<Box<dyn Fn()>> = vec![
        Box::new({
            let p = f.repo.join("main.py");
            move || {
                std::fs::write(
                    &p,
                    "from lib import helper\ndef alpha():\n    return helper()\n",
                )
                .unwrap()
            }
        }),
        Box::new({
            let p = f.repo.join("main.py");
            move || std::fs::write(&p, "def alpha():\n    return 2\n").unwrap()
        }),
        Box::new({
            let p = f.repo.join("main.py");
            move || std::fs::write(&p, "def alpha():\n    return 3\n").unwrap()
        }),
        Box::new({
            let p = f.repo.join("added.py");
            move || std::fs::write(&p, "def added():\n    return 1\n").unwrap()
        }),
        Box::new({
            let p = f.repo.join("added.py");
            move || std::fs::remove_file(&p).unwrap()
        }),
        Box::new({
            let p = f.repo.join("main.py");
            let q = f.repo.join("renamed.py");
            move || std::fs::rename(&p, &q).unwrap()
        }),
        Box::new({
            let p = f.repo.join("renamed.py");
            let q = f.repo.join("renamed.rs");
            move || {
                std::fs::rename(&p, &q).unwrap();
                std::fs::write(&q, "fn alpha() { let same = 3; }\n").unwrap();
            }
        }),
    ];
    for edit in edits {
        edit();
        f.refresh();
        let conn = Connection::open(f.db()).unwrap();
        let incremental = qi_full_rows(&conn);
        drop(conn);
        build::run_with_force(f.repo.to_str().unwrap(), true).unwrap();
        let conn = Connection::open(f.db()).unwrap();
        assert_eq!(incremental, qi_full_rows(&conn));
    }
    let conn = Connection::open(f.db()).unwrap();
    conn.execute_batch("CREATE TABLE global_write_count(n INTEGER); INSERT INTO global_write_count VALUES(0);
        CREATE TRIGGER gc_ci AFTER INSERT ON communities BEGIN UPDATE global_write_count SET n=n+1; END;
        CREATE TRIGGER gc_cd AFTER DELETE ON communities BEGIN UPDATE global_write_count SET n=n+1; END;
        CREATE TRIGGER gm_ci AFTER INSERT ON community_members BEGIN UPDATE global_write_count SET n=n+1; END;
        CREATE TRIGGER gm_cd AFTER DELETE ON community_members BEGIN UPDATE global_write_count SET n=n+1; END;
        CREATE TRIGGER gb_ci AFTER INSERT ON clone_bands BEGIN UPDATE global_write_count SET n=n+1; END;
        CREATE TRIGGER gb_cd AFTER DELETE ON clone_bands BEGIN UPDATE global_write_count SET n=n+1; END;
        CREATE TRIGGER gbm_ci AFTER INSERT ON clone_band_members BEGIN UPDATE global_write_count SET n=n+1; END;
        CREATE TRIGGER gbm_cd AFTER DELETE ON clone_band_members BEGIN UPDATE global_write_count SET n=n+1; END;
        CREATE TRIGGER gf_u AFTER UPDATE OF community_id,fan_in,fan_out ON files WHEN old.community_id IS NOT new.community_id OR old.fan_in IS NOT new.fan_in OR old.fan_out IS NOT new.fan_out BEGIN UPDATE global_write_count SET n=n+1; END;").unwrap();
    drop(conn);
    f.refresh();
    let conn = Connection::open(f.db()).unwrap();
    assert_eq!(
        conn.query_row("SELECT n FROM global_write_count", [], |r| r
            .get::<_, i64>(0))
            .unwrap(),
        0
    );
}

#[test]
fn edge_comment_edit_writes_zero_edge_rows_and_matches_rebuild() {
    let _guard = ENV_LOCK
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner);
    let f = Fixture::new();
    build::run(f.repo.to_str().unwrap()).unwrap();
    let conn = Connection::open(f.db()).unwrap();
    conn.execute_batch("CREATE TABLE edge_write_count(changes INTEGER); INSERT INTO edge_write_count VALUES(0);
        CREATE TRIGGER count_edge_insert AFTER INSERT ON resolved_edges BEGIN UPDATE edge_write_count SET changes=changes+1; END;
        CREATE TRIGGER count_edge_delete AFTER DELETE ON resolved_edges BEGIN UPDATE edge_write_count SET changes=changes+1; END;").unwrap();
    let before = edge_set(&conn);
    drop(conn);
    std::fs::write(
        f.repo.join("main.py"),
        "# comment\ndef alpha():\n    return 1\n\ndef beta():\n    return alpha()\n",
    )
    .unwrap();
    let meter = available().then(WriteMeter::start);
    f.refresh();
    let conn = Connection::open(f.db()).unwrap();
    conn.execute_batch("PRAGMA wal_checkpoint(TRUNCATE);")
        .unwrap();
    drop(conn);
    if let Some(meter) = meter {
        eprintln!("edge comment edit write bytes: {}", meter.bytes());
    }
    let conn = Connection::open(f.db()).unwrap();
    assert_eq!(edge_row_changes(&conn), 0);
    assert_eq!(before, edge_set(&conn));
    drop(conn);
    build::run_with_force(f.repo.to_str().unwrap(), true).unwrap();
    let conn = Connection::open(f.db()).unwrap();
    assert_eq!(before, edge_set(&conn));
}

#[test]
fn qi_repeated_entity_keys_survive_cold_and_incremental_writes() {
    let _guard = ENV_LOCK
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner);
    let f = Fixture::new();
    std::fs::remove_file(f.repo.join("main.py")).unwrap();
    let main = "func caller() {\n    do { let same = 1; _ = same }\n    do { let same = 2; _ = same }\n    target()\n    target()\n}\n";
    let leaf = "func target() {}\n";
    std::fs::write(f.repo.join("main.swift"), main).unwrap();
    std::fs::write(f.repo.join("leaf.swift"), leaf).unwrap();
    let mut sources = vec![main.to_string(), leaf.to_string()];
    for index in 0..520 {
        let source = format!("func filler_{index}() {{}}\n");
        std::fs::write(f.repo.join(format!("filler_{index}.swift")), &source).unwrap();
        sources.push(source);
    }
    build::run(f.repo.to_str().unwrap()).unwrap();

    let conn = Connection::open(f.db()).unwrap();
    let expected = qi_extraction_counts(&sources);
    let counts = qi_row_counts(&conn);
    assert_eq!(
        (counts.0, counts.1),
        expected,
        "cold rows must match extraction"
    );
    assert!(
        counts.2 >= 2,
        "the repeated calls must produce persisted edges"
    );
    let leaf_dependents = conn
        .prepare(
            "SELECT from_file_id FROM resolved_edges
             WHERE to_file_id=(SELECT id FROM files WHERE path LIKE '%/leaf.swift')
             ORDER BY from_file_id",
        )
        .unwrap()
        .query_map([], |row| row.get::<_, i64>(0))
        .unwrap()
        .map(Result::unwrap)
        .collect::<Vec<_>>();
    assert!(!leaf_dependents.is_empty(), "edges: {:?}", edge_set(&conn));
    drop(conn);

    let edited_leaf = "// edit that forces Swift's repo-wide edge fallback\nfunc target() {}\n";
    std::fs::write(f.repo.join("leaf.swift"), edited_leaf).unwrap();
    f.refresh();
    let conn = Connection::open(f.db()).unwrap();
    let incremental_counts = qi_row_counts(&conn);
    let incremental_edges = edge_set(&conn);
    let incremental_globals = global_rows(&conn);
    let incremental_dependents = conn
        .prepare(
            "SELECT ff.path FROM resolved_edges e
             JOIN files ff ON ff.id=e.from_file_id
             WHERE e.to_file_id=(SELECT id FROM files WHERE path LIKE '%/leaf.swift')
             ORDER BY ff.path",
        )
        .unwrap()
        .query_map([], |row| row.get::<_, String>(0))
        .unwrap()
        .map(Result::unwrap)
        .collect::<Vec<_>>();
    drop(conn);

    build::run_with_force(f.repo.to_str().unwrap(), true).unwrap();
    let conn = Connection::open(f.db()).unwrap();
    assert_eq!(incremental_counts, qi_row_counts(&conn));
    assert_eq!(incremental_edges, edge_set(&conn));
    assert_eq!(incremental_globals, global_rows(&conn));
    let rebuilt_dependents = conn
        .prepare(
            "SELECT ff.path FROM resolved_edges e
             JOIN files ff ON ff.id=e.from_file_id
             WHERE e.to_file_id=(SELECT id FROM files WHERE path LIKE '%/leaf.swift')
             ORDER BY ff.path",
        )
        .unwrap()
        .query_map([], |row| row.get::<_, String>(0))
        .unwrap()
        .map(Result::unwrap)
        .collect::<Vec<_>>();
    assert_eq!(incremental_dependents, rebuilt_dependents);
}

#[test]
fn qi_deleted_file_with_clone_band_matches_forced_rebuild() {
    let _guard = ENV_LOCK
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner);
    let f = Fixture::new();
    std::fs::remove_file(f.repo.join("main.py")).unwrap();
    let source = "fn shared() {\n    let a = 1;\n    let b = 2;\n    let c = 3;\n    let d = 4;\n    let e = 5;\n    let f = 6;\n    let g = 7;\n    let h = 8;\n}\n";
    std::fs::write(f.repo.join("a.rs"), source).unwrap();
    std::fs::write(f.repo.join("b.rs"), source).unwrap();
    build::run(f.repo.to_str().unwrap()).unwrap();
    let conn = Connection::open(f.db()).unwrap();
    let membership: i64 = conn
        .query_row(
            "SELECT count(*) FROM clone_band_members cbm
             JOIN entities e ON e.id=cbm.entity_id JOIN files f ON f.id=e.file_id
             WHERE f.path LIKE '%/b.rs'",
            [],
            |row| row.get(0),
        )
        .unwrap();
    assert!(
        membership > 0,
        "fixture must exercise clone band membership"
    );
    drop(conn);

    std::fs::remove_file(f.repo.join("b.rs")).unwrap();
    f.refresh();
    let conn = Connection::open(f.db()).unwrap();
    let incremental = qi_full_rows(&conn);
    drop(conn);
    build::run_with_force(f.repo.to_str().unwrap(), true).unwrap();
    let conn = Connection::open(f.db()).unwrap();
    assert_eq!(incremental, qi_full_rows(&conn));
}

#[test]
fn edge_import_and_call_edits_match_full_rebuild() {
    let _guard = ENV_LOCK
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner);
    let f = Fixture::new();
    std::fs::write(f.repo.join("lib.py"), "def helper():\n    return 1\n").unwrap();
    build::run(f.repo.to_str().unwrap()).unwrap();
    for source in [
        "from lib import helper\ndef alpha():\n    return helper()\n",
        "def alpha():\n    return 2\n",
        "def renamed():\n    return 2\n",
    ] {
        std::fs::write(f.repo.join("main.py"), source).unwrap();
        f.refresh();
        let conn = Connection::open(f.db()).unwrap();
        let incremental = edge_set(&conn);
        drop(conn);
        build::run_with_force(f.repo.to_str().unwrap(), true).unwrap();
        let conn = Connection::open(f.db()).unwrap();
        assert_eq!(incremental, edge_set(&conn));
    }
}

#[test]
fn full_edge_comment_edit_writes_zero_edge_rows_and_matches_rebuild() {
    let _guard = ENV_LOCK
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner);
    let f = Fixture::new();
    std::fs::remove_file(f.repo.join("main.py")).unwrap();
    std::fs::write(
        f.repo.join("main.rs"),
        "fn alpha() {}\nfn beta() { alpha(); }\n",
    )
    .unwrap();
    std::fs::write(f.repo.join("fallback.swift"), "func unrelated() {}\n").unwrap();
    build::run(f.repo.to_str().unwrap()).unwrap();
    let conn = Connection::open(f.db()).unwrap();
    conn.execute_batch("CREATE TABLE edge_write_count(changes INTEGER); INSERT INTO edge_write_count VALUES(0);
        CREATE TRIGGER count_edge_insert AFTER INSERT ON resolved_edges BEGIN UPDATE edge_write_count SET changes=changes+1; END;
        CREATE TRIGGER count_edge_delete AFTER DELETE ON resolved_edges BEGIN UPDATE edge_write_count SET changes=changes+1; END;").unwrap();
    let before = edge_set(&conn);
    drop(conn);

    std::fs::write(
        f.repo.join("main.rs"),
        "// comment\nfn alpha() {}\nfn beta() { alpha(); }\n",
    )
    .unwrap();
    build::run(f.repo.to_str().unwrap()).unwrap();

    let conn = Connection::open(f.db()).unwrap();
    assert_eq!(edge_row_changes(&conn), 0);
    assert_eq!(before, edge_set(&conn));
    drop(conn);
    build::run_with_force(f.repo.to_str().unwrap(), true).unwrap();
    let conn = Connection::open(f.db()).unwrap();
    assert_eq!(before, edge_set(&conn));
}

#[test]
fn full_edge_call_edits_match_cold_build() {
    let _guard = ENV_LOCK
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner);
    let f = Fixture::new();
    std::fs::remove_file(f.repo.join("main.py")).unwrap();
    std::fs::write(
        f.repo.join("main.rs"),
        "fn alpha() {}\nfn beta() { alpha(); }\n",
    )
    .unwrap();
    std::fs::write(f.repo.join("fallback.swift"), "func unrelated() {}\n").unwrap();
    build::run(f.repo.to_str().unwrap()).unwrap();
    for source in [
        "fn alpha() {}\nfn beta() { alpha(); alpha(); }\n",
        "fn alpha() {}\nfn beta() {}\n",
        "fn renamed() {}\nfn beta() { renamed(); }\n",
    ] {
        std::fs::write(f.repo.join("main.rs"), source).unwrap();
        build::run(f.repo.to_str().unwrap()).unwrap();
        let conn = Connection::open(f.db()).unwrap();
        let incremental = edge_set(&conn);
        drop(conn);
        build::run_with_force(f.repo.to_str().unwrap(), true).unwrap();
        let conn = Connection::open(f.db()).unwrap();
        assert_eq!(incremental, edge_set(&conn));
    }
}

#[test]
fn entity_comment_edit_keeps_entity_and_symbol_rowids() {
    let _guard = ENV_LOCK
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner);
    let f = Fixture::new();
    build::run(f.repo.to_str().unwrap()).unwrap();
    let conn = Connection::open(f.db()).unwrap();
    let entities = ids(&conn, "entities");
    let symbols = ids(&conn, "symbols");
    drop(conn);
    std::fs::write(
        f.repo.join("main.py"),
        "def alpha():\n    return 1\n\ndef beta():\n    return alpha()\n\n# trailing comment\n",
    )
    .unwrap();
    f.refresh();
    let conn = Connection::open(f.db()).unwrap();
    assert_eq!(entities, ids(&conn, "entities"));
    assert_eq!(symbols, ids(&conn, "symbols"));
}

#[test]
fn entity_add_remove_changes_only_affected_rows() {
    let _guard = ENV_LOCK
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner);
    let f = Fixture::new();
    build::run(f.repo.to_str().unwrap()).unwrap();
    let conn = Connection::open(f.db()).unwrap();
    let before = function_ids(&conn);
    drop(conn);
    std::fs::write(f.repo.join("main.py"), "def alpha():\n    return 1\n\ndef beta():\n    return alpha()\n\ndef gamma():\n    return beta()\n").unwrap();
    f.refresh();
    let conn = Connection::open(f.db()).unwrap();
    let after = function_ids(&conn);
    for (name, id) in &before {
        assert_eq!(
            after.iter().find(|(n, _)| n == name).map(|(_, id)| id),
            Some(id)
        );
    }
    let gamma = after.iter().find(|(n, _)| n == "gamma").unwrap().1;
    assert!(!before.iter().any(|(_, id)| *id == gamma));
    drop(conn);
    std::fs::write(
        f.repo.join("main.py"),
        "def alpha():\n    return 1\n\ndef beta():\n    return alpha()\n",
    )
    .unwrap();
    f.refresh();
    let conn = Connection::open(f.db()).unwrap();
    let final_ids = function_ids(&conn);
    assert_eq!(before, final_ids);
    assert!(!final_ids.iter().any(|(_, id)| *id == gamma));
    let edges = edge_set(&conn);
    drop(conn);
    build::run_with_force(f.repo.to_str().unwrap(), true).unwrap();
    let conn = Connection::open(f.db()).unwrap();
    assert_eq!(
        edges,
        edge_set(&conn),
        "loaded graph is compared as a set of file/entity edge keys"
    );
}
