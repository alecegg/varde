//! Integration tests for the graph-traversal query modes: dependencies,
//! dependents, blast_radius, symbol_blast_radius, type_hierarchy, explore.
//!
//! Fixtures are built two ways: real resolved fixture projects
//! (extract → resolve → persist) and synthetic graphs (constructed
//! `ExtractOutput`/`ResolvedGraph` persisted directly) for cycle and
//! scale cases.

use std::path::PathBuf;

use varde_code::model::{Entity, EntityKind, ExtractOutput, FileMeta, Span, Symbol, SymbolKind};
use varde_code::persist;
use varde_code::query;
use varde_code::resolve::{self, EdgeKind, EdgeTarget, FileNode, ResolvedEdge, ResolvedGraph};

static SEQ: std::sync::atomic::AtomicUsize = std::sync::atomic::AtomicUsize::new(0);

fn temp_db(tag: &str) -> PathBuf {
    // Unique dir per call: parallel tests sharing a tag must not race.
    let seq = SEQ.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
    let dir = std::env::temp_dir().join(format!(
        "varde-qgraph-{}-{}-{}",
        tag,
        std::process::id(),
        seq
    ));
    std::fs::create_dir_all(&dir).expect("temp dir creates");
    std::fs::create_dir_all(dir.join(".git")).expect("fixture metadata dir");
    let db = dir.join(".git/index.db");
    let _ = std::fs::remove_file(&db);
    db
}

fn span() -> Span {
    Span {
        start_byte: 0,
        end_byte: 1,
        start_line: 1,
        start_col: 0,
        end_line: 1,
        end_col: 1,
    }
}

fn fn_entity(file_id: u32, name: &str) -> Entity {
    Entity {
        kind: EntityKind::Function,
        name: name.to_string(),
        file_id,
        span: span(),
        enclosing_function: None,
        method: None,
        path: None,
        status: None,
        body_shape: None,
        body_minhash: None,
        is_async: None,
        is_test: false,
        owner_type: None,
    }
}

fn persist_fixture(db: &std::path::Path, mut output: ExtractOutput, graph: &ResolvedGraph) {
    let root = db.parent().unwrap().parent().unwrap();
    output.file_meta.clear();
    for file in &mut output.files {
        let path = root.join(&*file);
        std::fs::write(&path, "fn fixture() {}\n").expect("fixture source");
        let state = varde_code::scan::list_source_files(path.to_str().unwrap())
            .expect("source metadata")
            .remove(0);
        output.file_meta.push(FileMeta {
            mtime: state.mtime,
            size: state.size,
            content_hash: state.content_hash.unwrap_or_default(),
        });
        *file = path.to_string_lossy().into_owned();
    }
    persist::persist(db, &[output], graph, root).expect("persist succeeds");
}

/// Persist a synthetic graph: files 0..n with edges given as (from, to)
/// pairs (import kind, resolved).
fn persist_synthetic(tag: &str, n: usize, edges: &[(usize, usize)]) -> PathBuf {
    let db = temp_db(tag);
    let mut entities = Vec::new();
    let mut nodes = Vec::new();
    let mut files = Vec::new();
    for i in 0..n {
        let file = format!("f{i}.rs");
        entities.push(fn_entity(i as u32, &format!("fn{i}")));
        nodes.push(FileNode {
            path: file.clone(),
            community_id: None,
            fan_in: 0,
            fan_out: 0,
        });
        files.push(file);
    }
    let resolved: Vec<ResolvedEdge> = edges
        .iter()
        .map(|(from, to)| ResolvedEdge {
            from: *from as u32,
            to: EdgeTarget::File(*to as u32),
            kind: EdgeKind::Import,
            resolved: true,
            from_entity: None,
        })
        .collect();
    let graph = ResolvedGraph {
        nodes,
        edges: resolved,
        communities: vec![],
        clone_bands: vec![],
    };
    let output = ExtractOutput {
        entities,
        symbols: vec![],
        diagnostics: vec![],
        file_meta: vec![
            FileMeta {
                mtime: 0,
                size: 0,
                content_hash: "0000000000000000".to_string()
            };
            files.len()
        ],
        files,
    };
    persist_fixture(&db, output, &graph);
    db
}

/// Like [`persist_synthetic`], but also persists one binding symbol per
/// file (`sym{i}`) into the `symbols` table, for `explore`'s symbol-name
/// seed-resolution fallback.
fn persist_synthetic_with_symbols(tag: &str, n: usize, edges: &[(usize, usize)]) -> PathBuf {
    let db = temp_db(tag);
    let mut entities = Vec::new();
    let mut symbols = Vec::new();
    let mut nodes = Vec::new();
    let mut files = Vec::new();
    for i in 0..n {
        let file = format!("f{i}.rs");
        entities.push(fn_entity(i as u32, &format!("fn{i}")));
        symbols.push(Symbol {
            kind: SymbolKind::Binding,
            name: format!("sym{i}"),
            file_id: i as u32,
            span: span(),
        });
        nodes.push(FileNode {
            path: file.clone(),
            community_id: None,
            fan_in: 0,
            fan_out: 0,
        });
        files.push(file);
    }
    let resolved: Vec<ResolvedEdge> = edges
        .iter()
        .map(|(from, to)| ResolvedEdge {
            from: *from as u32,
            to: EdgeTarget::File(*to as u32),
            kind: EdgeKind::Import,
            resolved: true,
            from_entity: None,
        })
        .collect();
    let graph = ResolvedGraph {
        nodes,
        edges: resolved,
        communities: vec![],
        clone_bands: vec![],
    };
    let output = ExtractOutput {
        entities,
        symbols,
        diagnostics: vec![],
        file_meta: vec![
            FileMeta {
                mtime: 0,
                size: 0,
                content_hash: "0000000000000000".to_string()
            };
            files.len()
        ],
        files,
    };
    persist_fixture(&db, output, &graph);
    db
}

/// Run a mode against a db path; returns the envelope.
fn envelope(mode: &str, db_path: &std::path::Path, extra: &str) -> serde_json::Value {
    let repo = if db_path.to_string_lossy().contains("rust-mod-") {
        PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("resolve_fixtures/rust/modules")
    } else {
        db_path.parent().unwrap().parent().unwrap().to_path_buf()
    };
    let input = format!(r#"{{"repoRoot":"{repo}","dbPath":"{db}",{extra}}}"#, repo = repo.display(), db = db_path.display());
    let stdout = query::run_mode(mode, &input);
    serde_json::from_str(&stdout).expect("envelope is JSON")
}

fn data(mode: &str, db_path: &std::path::Path, extra: &str) -> serde_json::Value {
    envelope(mode, db_path, extra)["data"].clone()
}

fn paths_array(value: &serde_json::Value) -> Vec<String> {
    value
        .as_array()
        .unwrap_or_else(|| panic!("data is an array: {value}"))
        .iter()
        .map(|v| {
            let path = v.as_str().unwrap();
            if path.contains("/varde-qgraph-") {
                std::path::Path::new(path)
                    .file_name()
                    .unwrap()
                    .to_string_lossy()
                    .into_owned()
            } else {
                path.to_string()
            }
        })
        .collect()
}

mod cycle_termination {
    use super::*;

    /// a→b→c→a: every traversal must terminate with a finite result.
    #[test]
    fn cyclic_graph_terminates_for_all_traversals() {
        let db = persist_synthetic("cycle", 3, &[(0, 1), (1, 2), (2, 0)]);
        for mode in ["dependencies", "dependents", "blast_radius"] {
            let env = envelope(mode, &db, r#""filePath":"f0.rs""#);
            assert_eq!(env["ok"], true, "{mode} terminated: {env}");
            let arr = env["data"].as_array().expect("array");
            assert!(
                !arr.is_empty(),
                "{mode} on a cycle returns a finite non-empty set"
            );
            // f0 reaches f1 and f2 via the cycle — both must appear, no dupes.
            let files = paths_array(&env["data"]);
            assert_eq!(files.len(), 2, "{mode} result: {files:?}");
        }
    }
}

mod dependencies_mode {
    use super::*;

    fn fan_db() -> PathBuf {
        // a→b, a→c, b→c (resolved imports).
        persist_synthetic("fan", 3, &[(0, 1), (0, 2), (1, 2)])
    }

    #[test]
    fn outgoing_matches_expected_traversal() {
        let db = fan_db();
        let result = data("dependencies", &db, r#""filePath":"f0.rs""#);
        assert_eq!(paths_array(&result), vec!["f1.rs", "f2.rs"]);
    }

    #[test]
    fn incoming_direction_supported() {
        let db = fan_db();
        let result = data(
            "dependencies",
            &db,
            r#""filePath":"f2.rs","direction":"incoming""#,
        );
        assert_eq!(paths_array(&result), vec!["f0.rs", "f1.rs"]);
    }

    #[test]
    fn max_depth_limits_traversal() {
        // Chain f0→f1→f2: depth 1 reaches f1 only, depth 2 reaches f1+f2.
        let db = persist_synthetic("fan-depth", 3, &[(0, 1), (1, 2)]);
        let result = data("dependencies", &db, r#""filePath":"f0.rs","maxDepth":1"#);
        assert_eq!(paths_array(&result), vec!["f1.rs"]);
        let full = data("dependencies", &db, r#""filePath":"f0.rs""#);
        assert_eq!(paths_array(&full), vec!["f1.rs", "f2.rs"]);
    }
}

mod dependents_mode {
    use super::*;

    #[test]
    fn reverse_traversal_matches_expected() {
        let db = persist_synthetic("dep", 3, &[(0, 1), (0, 2), (1, 2)]);
        let result = data("dependents", &db, r#""filePath":"f2.rs""#);
        assert_eq!(paths_array(&result), vec!["f0.rs", "f1.rs"]);
    }

    #[test]
    fn leaf_has_no_dependents() {
        // f1 depends on f0, so nothing depends on f1.
        let db = persist_synthetic("dep-leaf", 2, &[(1, 0)]);
        let env = envelope("dependents", &db, r#""filePath":"f1.rs""#);
        assert_eq!(env["ok"], true);
        assert_eq!(env["data"], serde_json::json!([]));
    }
}

mod blast_radius_mode {
    use super::*;

    #[test]
    fn transitive_dependents_exclude_dependencies() {
        let db = persist_synthetic("br", 5, &[(0, 1), (1, 2), (3, 1), (4, 0)]);
        // f1 depends on f2; f0, f3, and transitively f4 depend on f1.
        let result = data("blast_radius", &db, r#""filePath":"f1.rs""#);
        assert_eq!(paths_array(&result), vec!["f0.rs", "f3.rs", "f4.rs"]);
    }

    #[test]
    fn consumer_without_dependents_has_empty_blast_radius() {
        let db = persist_synthetic("br-consumer", 3, &[(0, 1), (1, 2)]);
        let result = data("blast_radius", &db, r#""filePath":"f0.rs""#);
        assert_eq!(paths_array(&result), Vec::<String>::new());
    }

    #[test]
    fn cycle_excludes_seed_and_outgoing_only_tail() {
        let db = persist_synthetic("br-cycle", 4, &[(0, 1), (1, 0), (0, 2), (3, 1)]);
        let result = data("blast_radius", &db, r#""filePath":"f0.rs""#);
        assert_eq!(paths_array(&result), vec!["f1.rs", "f3.rs"]);
    }

    #[test]
    fn isolated_file_has_empty_blast_radius() {
        let db = persist_synthetic("br-isolated", 3, &[(0, 1)]);
        let result = data("blast_radius", &db, r#""filePath":"f2.rs""#);
        assert_eq!(paths_array(&result), Vec::<String>::new());
    }
}

mod symbol_blast_radius_mode {
    use super::*;

    #[test]
    fn file_imports_are_not_symbol_references() {
        let db = persist_synthetic("sbr", 3, &[(0, 1), (1, 2)]);
        let result = data("symbol_blast_radius", &db, r#""name":"fn1""#);
        assert!(result["declaring_file"].as_str().unwrap().ends_with("/f1.rs"));
        assert_eq!(paths_array(&result["blast_radius"]), Vec::<String>::new());
        assert_eq!(result["analysis"]["status"], "partial");
    }

    #[test]
    fn unknown_symbol_is_not_found() {
        let db = persist_synthetic("sbr-nf", 2, &[(0, 1)]);
        let env = envelope("symbol_blast_radius", &db, r#""name":"ghost_fn""#);
        assert_eq!(env["ok"], false);
        assert_eq!(env["data"]["error"]["code"], "not_found");
    }
}

mod type_hierarchy_mode {
    use super::*;

    #[test]
    fn returns_inheritance_hierarchy() {
        let db = temp_db("th");
        // `Thing extends Base`, encoded as an Extends entity (kind 15) whose
        // `enclosing_function` is the subtype and `name` is the supertype.
        let mut base = fn_entity(0, "Base");
        base.kind = EntityKind::Class;
        let mut thing = fn_entity(0, "Thing");
        thing.kind = EntityKind::Class;
        let mut extends = fn_entity(0, "Base");
        extends.kind = EntityKind::Extends;
        extends.enclosing_function = Some("Thing".to_string());
        let output = ExtractOutput {
            entities: vec![base, thing, extends],
            symbols: vec![],
            diagnostics: vec![],
            files: vec!["a.rs".to_string()],
            file_meta: vec![
                FileMeta {
                    mtime: 0,
                    size: 0,
                    content_hash: "0000000000000000".to_string()
                };
                1
            ],
        };
        let graph =
            resolve::resolve(&output.entities, &output.symbols, &output.files).expect("resolve");
        persist_fixture(&db, output, &graph);

        // Seed prefers the class declaration over the same-named Extends edge.
        let result = data("type_hierarchy", &db, r#""name":"Thing","filePath":"a.rs""#);
        assert_eq!(result["symbol"]["name"], "Thing");
        assert_eq!(result["symbol"]["kind"], "class");
        let supers = result["supertypes"].as_array().expect("supertypes array");
        assert_eq!(supers.len(), 1, "Thing has one supertype: {result}");
        assert_eq!(supers[0]["name"], "Base");
        // hierarchy = ancestor chain parent-first, ending in the seed.
        let chain = result["hierarchy"].as_array().expect("hierarchy array");
        assert_eq!(chain.len(), 2, "Base + Thing: {result}");
        assert_eq!(chain[0]["name"], "Base");
        assert_eq!(chain[1]["name"], "Thing");

        // From the base, Thing is reported as a subtype (implementer).
        let base_res = data("type_hierarchy", &db, r#""name":"Base","filePath":"a.rs""#);
        let subs = base_res["subtypes"].as_array().expect("subtypes array");
        assert_eq!(subs.len(), 1, "Base has one subtype: {base_res}");
        assert_eq!(subs[0]["name"], "Thing");
    }

    #[test]
    fn unknown_type_is_not_found() {
        let db = persist_synthetic("th-nf", 2, &[(0, 1)]);
        let env = envelope("type_hierarchy", &db, r#""name":"Ghost""#);
        assert_eq!(env["ok"], false);
        assert_eq!(env["data"]["error"]["code"], "not_found");
    }

    /// Regression: a mutually-recursive inheritance cycle (`A extends B` and
    /// `B extends A`) must not loop forever. The BFS carries its own visited
    /// set so the walk terminates once both A and B are seen.
    #[test]
    fn cyclic_inheritance_terminates_instead_of_looping_forever() {
        let db = temp_db("th-cycle");
        let mut a = fn_entity(0, "A");
        a.kind = EntityKind::Class;
        let mut b = fn_entity(0, "B");
        b.kind = EntityKind::Class;
        // A extends B, B extends A.
        let mut a_ext_b = fn_entity(0, "B");
        a_ext_b.kind = EntityKind::Extends;
        a_ext_b.enclosing_function = Some("A".to_string());
        let mut b_ext_a = fn_entity(0, "A");
        b_ext_a.kind = EntityKind::Extends;
        b_ext_a.enclosing_function = Some("B".to_string());
        let output = ExtractOutput {
            entities: vec![a, b, a_ext_b, b_ext_a],
            symbols: vec![],
            diagnostics: vec![],
            files: vec!["a.rs".to_string()],
            file_meta: vec![
                FileMeta {
                    mtime: 0,
                    size: 0,
                    content_hash: "0000000000000000".to_string()
                };
                1
            ],
        };
        let graph =
            resolve::resolve(&output.entities, &output.symbols, &output.files).expect("resolve");
        persist_fixture(&db, output, &graph);

        let result = data("type_hierarchy", &db, r#""name":"A","filePath":"a.rs""#);
        // Walk terminates; A's only supertype is B (B's back-edge to A is
        // pruned by the visited set).
        let supers = result["supertypes"].as_array().expect("supertypes array");
        assert_eq!(
            supers.len(),
            1,
            "cycle must terminate once both A and B are seen: {result}"
        );
        assert_eq!(supers[0]["name"], "B");
    }
}

mod explore_mode {
    use super::*;

    #[test]
    fn explores_neighborhood_from_seed() {
        let db = persist_synthetic("explore", 3, &[(0, 1), (0, 2)]);
        let result = data(
            "explore",
            &db,
            r#""query":{"kind":"dependency","params":{"input":"f0.rs"}}"#,
        );
        assert_eq!(result["input"], "f0.rs");
        assert_eq!(paths_array(&result["reachable"]), vec!["f1.rs", "f2.rs"]);
    }

    #[test]
    fn max_items_caps_results() {
        let db = persist_synthetic("explore-cap", 4, &[(0, 1), (0, 2), (0, 3)]);
        let result = data(
            "explore",
            &db,
            r#""query":{"kind":"dependency","params":{"input":"f0.rs","maxItems":1}}"#,
        );
        assert_eq!(paths_array(&result["reachable"]).len(), 1);
    }

    #[test]
    fn falls_back_to_symbol_name_when_seed_is_not_a_file() {
        let db = persist_synthetic_with_symbols("explore-symbol", 3, &[(0, 1), (0, 2)]);
        let result = data("explore", &db, r#""query":{"params":{"input":"sym0"}}"#);
        assert_eq!(result["resolvedVia"], "symbol_exact");
        assert_eq!(paths_array(&result["seedFiles"]), vec!["f0.rs"]);
        assert_eq!(paths_array(&result["reachable"]), vec!["f1.rs", "f2.rs"]);
    }

    #[test]
    fn falls_back_to_partial_symbol_match() {
        let db = persist_synthetic_with_symbols("explore-symbol-partial", 3, &[(0, 1), (0, 2)]);
        let result = data("explore", &db, r#""query":{"params":{"input":"YM0"}}"#);
        assert_eq!(result["resolvedVia"], "symbol_partial");
        assert_eq!(paths_array(&result["seedFiles"]), vec!["f0.rs"]);
    }

    #[test]
    fn incoming_direction_walks_reverse_edges() {
        let db = persist_synthetic("explore-incoming", 3, &[(0, 1), (0, 2)]);
        let result = data(
            "explore",
            &db,
            r#""query":{"params":{"input":"f1.rs","direction":"incoming"}}"#,
        );
        assert_eq!(paths_array(&result["reachable"]), vec!["f0.rs"]);
    }

    #[test]
    fn both_direction_unions_forward_and_reverse() {
        // f0 -> f1 -> f2: from f1, "both" reaches f0 (incoming) and f2 (outgoing).
        let db = persist_synthetic("explore-both", 3, &[(0, 1), (1, 2)]);
        let result = data(
            "explore",
            &db,
            r#""query":{"params":{"input":"f1.rs","direction":"both"}}"#,
        );
        assert_eq!(paths_array(&result["reachable"]), vec!["f0.rs", "f2.rs"]);
    }

    #[test]
    fn unresolvable_seed_is_not_found() {
        let db = persist_synthetic("explore-miss", 2, &[(0, 1)]);
        let env = envelope(
            "explore",
            &db,
            r#""query":{"params":{"input":"nonexistent"}}"#,
        );
        assert_eq!(env["ok"], false, "{env}");
    }
}

/// File-graph queries over a real Rust project: `mod` declarations and
/// `crate::`/`super::` paths must produce file edges, or every file-level
/// query is empty for Rust.
mod rust_module_graph {
    use super::*;

    /// Extract → resolve → persist `resolve_fixtures/rust/modules`.
    fn persist_rust_modules(tag: &str) -> (PathBuf, PathBuf) {
        let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("resolve_fixtures/rust/modules");
        let mut paths = Vec::new();
        collect_rust_files(&root, &mut paths);
        paths.sort();
        let files: Vec<String> = paths
            .iter()
            .map(|path| path.to_string_lossy().into_owned())
            .collect();
        let mut entities = Vec::new();
        let mut symbols = Vec::new();
        for (file_id, path) in paths.iter().enumerate() {
            let parsed = varde_code::parse::parse_file(path)
                .expect("parse ok")
                .expect("Rust source parses");
            let result = varde_code::extract::extract(&parsed, file_id as u32);
            entities.extend(result.entities);
            symbols.extend(result.symbols);
        }
        let mut output = ExtractOutput {
            entities,
            symbols,
            diagnostics: vec![],
            file_meta: files.iter().map(|file| {
                let state = varde_code::scan::list_source_files(file).expect("source metadata").remove(0);
                FileMeta {
                    mtime: state.mtime,
                    size: state.size,
                    content_hash: state.content_hash.unwrap_or_default(),
                }
            }).collect(),
            files,
        };
        let mut graph =
            resolve::resolve(&output.entities, &output.symbols, &output.files).expect("resolve");
        for state in varde_code::scan::list_source_listing(root.to_str().unwrap()).unwrap().files {
            if output.files.contains(&state.path) {
                continue;
            }
            graph.nodes.push(FileNode {
                path: state.path.clone(),
                community_id: None,
                fan_in: 0,
                fan_out: 0,
            });
            output.files.push(state.path);
            output.file_meta.push(FileMeta {
                mtime: state.mtime,
                size: state.size,
                content_hash: state.content_hash.unwrap_or_default(),
            });
        }
        let db = temp_db(tag);
        persist::persist(&db, std::slice::from_ref(&output), &graph, &root).expect("persist");
        let conn = varde_code::db::open_read_only(&db).unwrap();
        assert!(varde_code::slice::check_fresh(&conn, &[varde_code::slice::Slice::Edges], root.to_str().unwrap(), &varde_code::slice::Scope::Repo).unwrap(), "fixture index stale");
        (db, root)
    }

    fn collect_rust_files(dir: &std::path::Path, paths: &mut Vec<PathBuf>) {
        for entry in std::fs::read_dir(dir).expect("fixture dir").flatten() {
            let path = entry.path();
            if path.is_dir() {
                collect_rust_files(&path, paths);
            } else if path.extension().is_some_and(|ext| ext == "rs") {
                paths.push(path);
            }
        }
    }

    /// Query result paths relative to the fixture root.
    fn relative(result: &serde_json::Value, root: &std::path::Path) -> Vec<String> {
        let prefix = format!("{}/", root.display());
        let mut paths: Vec<String> = paths_array(result)
            .into_iter()
            .map(|path| path.strip_prefix(&prefix).unwrap_or(&path).to_string())
            .collect();
        paths.sort();
        paths
    }

    fn file_arg(root: &std::path::Path, file: &str) -> String {
        format!(r#""filePath":"{}""#, root.join(file).display())
    }

    #[test]
    fn dependents_follow_mod_declarations_and_use_paths() {
        let (db, root) = persist_rust_modules("rust-mod-dependents");
        // child.rs is declared by parent.rs (`mod child;`) and named by
        // file_form.rs (`use crate::parent::child::Thing`).
        let dependents = data(
            "dependents",
            &db,
            &file_arg(&root, "app/src/parent/child.rs"),
        );
        let dependents = relative(&dependents, &root);
        for expected in [
            "app/src/parent.rs",
            "app/src/file_form.rs",
            "app/src/lib.rs",
        ] {
            assert!(
                dependents.iter().any(|path| path == expected),
                "{expected} depends on child.rs: {dependents:?}"
            );
        }
        assert!(
            !dependents
                .iter()
                .any(|path| path.starts_with("helper_lib/")),
            "helper_lib never reaches app modules: {dependents:?}"
        );
    }

    #[test]
    fn blast_radius_and_find_imports_cover_rust_modules() {
        let (db, root) = persist_rust_modules("rust-mod-blast");
        let blast = relative(
            &data(
                "blast_radius",
                &db,
                &file_arg(&root, "helper_lib/src/util.rs"),
            ),
            &root,
        );
        assert_eq!(blast, ["app/src/main.rs", "helper_lib/src/lib.rs"]);

        let imports = data("find_imports", &db, &file_arg(&root, "app/src/lib.rs"));
        let resolved = imports
            .as_array()
            .expect("find_imports array")
            .iter()
            .filter(|import| import["resolved"] == true)
            .count();
        assert_eq!(resolved, 5, "lib.rs declares five module files: {imports}");
    }
}
