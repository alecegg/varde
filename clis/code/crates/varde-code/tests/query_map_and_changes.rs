//! Integration tests for the mapping/diff query modes: map_file, map_symbol,
//! map_path, detect_changes, hotspots.

use std::path::PathBuf;
use std::sync::{Mutex, OnceLock};

use varde_code::model::{Entity, EntityKind, ExtractOutput, FileMeta, Span};
use varde_code::persist;
use varde_code::query;
use varde_code::resolve::{self, EdgeKind, EdgeTarget, FileNode, ResolvedEdge, ResolvedGraph};

static SEQ: std::sync::atomic::AtomicUsize = std::sync::atomic::AtomicUsize::new(0);

fn temp_dir(tag: &str) -> PathBuf {
    let seq = SEQ.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
    let dir =
        std::env::temp_dir().join(format!("varde-qmap-{}-{}-{}", tag, std::process::id(), seq));
    std::fs::create_dir_all(&dir).expect("temp dir creates");
    dir
}

mod context_pack_mode {
    use super::*;

    fn context_db(entities: Vec<Entity>, files: Vec<String>) -> PathBuf {
        let db = temp_db("context-pack");
        let output = ExtractOutput {
            entities,
            symbols: vec![],
            diagnostics: vec![],
            file_meta: vec![
                FileMeta {
                    mtime: 0,
                    size: 0,
                    content_hash: "0000000000000000".to_string(),
                };
                files.len()
            ],
            files,
        };
        let graph =
            resolve::resolve(&output.entities, &output.symbols, &output.files).expect("resolve");
        persist_fixture(&db, output, &graph);
        db
    }

    fn test_hint_db() -> PathBuf {
        let db = temp_db("context-pack-test-hints");
        let files = vec!["src/product.ts".into(), "tests/product_test.ts".into()];
        let entities = vec![
            context_entity(0, EntityKind::Function, "needle_handler", 1, 1),
            context_entity(1, EntityKind::Import, "../src/product.ts", 1, 1),
        ];
        let graph = resolve::resolve(&entities, &[], &files).expect("resolve fixture imports");
        assert!(
            graph.edges.iter().any(|edge| {
                edge.from == 1
                    && edge.to == EdgeTarget::File(0)
                    && edge.kind == EdgeKind::Import
                    && edge.resolved
            }),
            "test fixture must contain a resolved import from the test file"
        );
        let output = ExtractOutput {
            entities,
            symbols: vec![],
            diagnostics: vec![],
            file_meta: vec![
                FileMeta {
                    mtime: 0,
                    size: 0,
                    content_hash: "0000000000000000".to_string(),
                };
                files.len()
            ],
            files,
        };
        persist_fixture(&db, output, &graph);
        db
    }

    fn context_entity(
        file_id: u32,
        kind: EntityKind,
        name: &str,
        start_line: u32,
        end_line: u32,
    ) -> Entity {
        let mut entity = fn_entity(file_id, name);
        entity.kind = kind;
        entity.span.start_line = start_line;
        entity.span.end_line = end_line;
        entity
    }

    fn declaration_contract_db() -> PathBuf {
        context_db(
            vec![
                context_entity(0, EntityKind::Function, "route", 1, 1),
                context_entity(0, EntityKind::Function, "route_handler", 2, 4),
                context_entity(0, EntityKind::Function, "route_handler", 8, 10),
                context_entity(0, EntityKind::Class, "route_class", 12, 14),
                context_entity(0, EntityKind::Interface, "route_interface", 16, 18),
                context_entity(0, EntityKind::Variable, "route_value", 20, 20),
                context_entity(0, EntityKind::Export, "route_export", 22, 23),
                context_entity(0, EntityKind::Route, "route_endpoint", 25, 27),
                context_entity(1, EntityKind::Parameter, "route_parameter", 2, 2),
                context_entity(1, EntityKind::Call, "route_call", 4, 4),
                context_entity(1, EntityKind::ControlFlow, "route_branch", 6, 7),
            ],
            vec!["src/route.rs".into(), "src/occurrence_only.rs".into()],
        )
    }

    #[test]
    fn defaults_to_declarations_with_persisted_spans_and_keeps_occurrence_seeds() {
        let db = declaration_contract_db();
        let env = envelope(
            "context_pack",
            &format!(
                r#"{{"dbPath":"{}","query":"route handler route route_handler","fullResults":true}}"#,
                db.display()
            ),
        );

        assert_eq!(env["ok"], true, "{env}");
        let symbols = env["data"]["symbols"].as_array().expect("symbols array");
        let names: Vec<_> = symbols
            .iter()
            .map(|symbol| symbol["name"].as_str().unwrap())
            .collect();
        for name in [
            "route",
            "route_handler",
            "route_class",
            "route_interface",
            "route_value",
            "route_export",
            "route_endpoint",
        ] {
            assert!(names.contains(&name), "missing declaration {name}: {env}");
        }
        assert_eq!(
            names.iter().filter(|name| **name == "route").count(),
            1,
            "{env}"
        );
        assert_eq!(
            names
                .iter()
                .filter(|name| **name == "route_handler")
                .count(),
            2,
            "same-name declarations with distinct persisted spans must survive: {env}"
        );
        assert!(
            symbols.iter().all(|symbol| matches!(
                symbol["kind"].as_str(),
                Some("function" | "class" | "interface" | "variable" | "export" | "route")
            )),
            "default symbols must contain declaration kinds only: {env}"
        );

        let handler_spans: Vec<_> = symbols
            .iter()
            .filter(|symbol| symbol["name"] == "route_handler")
            .map(|symbol| symbol["span"].clone())
            .collect();
        assert_eq!(
            handler_spans,
            vec![
                serde_json::json!({"start_line": 2, "end_line": 4}),
                serde_json::json!({"start_line": 8, "end_line": 10}),
            ],
            "persisted line spans must be preserved in deterministic entity order: {env}"
        );

        let occurrence_seed = env["data"]["files"]
            .as_array()
            .expect("files array")
            .iter()
            .find(|file| file["path"] == "src/occurrence_only.rs")
            .expect("occurrence-only file remains discoverable");
        assert_eq!(occurrence_seed["relevance"], "seed", "{env}");
    }

    #[test]
    fn test_hints_can_be_disabled_without_changing_navigation_facts() {
        let db = test_hint_db();
        let default = envelope(
            "context_pack",
            &format!(
                r#"{{"dbPath":"{}","query":"needle","fullResults":true}}"#,
                db.display()
            ),
        );
        let explicit_true = envelope(
            "context_pack",
            &format!(
                r#"{{"dbPath":"{}","query":"needle","includeTests":true,"fullResults":true}}"#,
                db.display()
            ),
        );
        let without_tests = envelope(
            "context_pack",
            &format!(
                r#"{{"dbPath":"{}","query":"needle","includeTests":false,"fullResults":true}}"#,
                db.display()
            ),
        );

        assert_eq!(default["ok"], true, "{default}");
        assert_eq!(explicit_true["ok"], true, "{explicit_true}");
        assert_eq!(without_tests["ok"], true, "{without_tests}");
        assert_eq!(
            default["data"]["tests"],
            serde_json::json!([{
                "path": "tests/product_test.ts",
                "coversFile": "src/product.ts"
            }])
        );
        assert_eq!(explicit_true["data"], default["data"]);
        assert_eq!(without_tests["data"]["tests"], serde_json::json!([]));
        for key in ["files", "symbols", "readingOrder"] {
            assert_eq!(without_tests["data"][key], default["data"][key], "{key}");
        }

        for invalid in [
            serde_json::json!("false"),
            serde_json::json!(0),
            serde_json::Value::Null,
            serde_json::json!([]),
        ] {
            let input = serde_json::json!({
                "dbPath": db.display().to_string(),
                "query": "needle",
                "includeTests": invalid,
                "fullResults": true
            });
            let invalid_env = envelope("context_pack", &input.to_string());
            assert_eq!(invalid_env["ok"], false, "{invalid_env}");
            assert_eq!(invalid_env["data"]["error"]["code"], "invalid_input");
        }
    }

    #[test]
    fn occurrences_are_opt_in_and_full_results_only_bypass_caps() {
        let db = declaration_contract_db();
        let bounded = envelope(
            "context_pack",
            &format!(
                r#"{{"dbPath":"{}","query":"route","maxTokensEstimate":4000}}"#,
                db.display()
            ),
        );
        assert_eq!(bounded["ok"], true, "{bounded}");
        let bounded_symbols = bounded["data"]["symbols"]
            .as_array()
            .expect("symbols array");
        assert!(
            bounded_symbols.iter().all(|symbol| matches!(
                symbol["kind"].as_str(),
                Some("function" | "class" | "interface" | "variable" | "export" | "route")
            )),
            "bounded results must still apply declaration filtering: {bounded}"
        );

        let bounded_with_occurrences = envelope(
            "context_pack",
            &format!(
                r#"{{"dbPath":"{}","query":"route","includeOccurrences":true,"maxTokensEstimate":4000}}"#,
                db.display()
            ),
        );
        let bounded_occurrence_symbols = bounded_with_occurrences["data"]["symbols"]
            .as_array()
            .expect("symbols array");
        assert!(
            bounded_occurrence_symbols.len() < 11,
            "{bounded_with_occurrences}"
        );
        assert!(
            bounded_occurrence_symbols
                .iter()
                .any(|symbol| symbol["kind"] == "call"),
            "occurrence selection still respects caps: {bounded_with_occurrences}"
        );

        let complete = envelope(
            "context_pack",
            &format!(
                r#"{{"dbPath":"{}","query":"route","fullResults":true,"resultsLimit":1,"maxTokensEstimate":1}}"#,
                db.display()
            ),
        );
        assert_eq!(complete["ok"], true, "{complete}");
        let complete_symbols = complete["data"]["symbols"]
            .as_array()
            .expect("symbols array");
        assert!(complete_symbols.len() > bounded_symbols.len(), "{complete}");
        assert_eq!(
            complete_symbols.len(),
            8,
            "fullResults returns every declaration: {complete}"
        );
        assert!(
            complete_symbols.iter().all(|symbol| matches!(
                symbol["kind"].as_str(),
                Some("function" | "class" | "interface" | "variable" | "export" | "route")
            )),
            "fullResults must not disable declaration filtering: {complete}"
        );
        assert_eq!(
            complete["data"]["files"].as_array().unwrap().len(),
            2,
            "fullResults bypasses the file result cap: {complete}"
        );

        let with_occurrences = envelope(
            "context_pack",
            &format!(
                r#"{{"dbPath":"{}","query":"route","includeOccurrences":true,"fullResults":true}}"#,
                db.display()
            ),
        );
        assert_eq!(with_occurrences["ok"], true, "{with_occurrences}");
        let symbols = with_occurrences["data"]["symbols"]
            .as_array()
            .expect("symbols array");
        assert_eq!(symbols.len(), 11, "{with_occurrences}");
        assert!(symbols.iter().any(|symbol| symbol["kind"] == "parameter"));
        assert!(symbols.iter().any(|symbol| symbol["kind"] == "call"));
        assert!(
            symbols
                .iter()
                .any(|symbol| symbol["kind"] == "control_flow")
        );
        assert!(
            symbols[..8].iter().all(|symbol| matches!(
                symbol["kind"].as_str(),
                Some("function" | "class" | "interface" | "variable" | "export" | "route")
            )),
            "declarations remain ahead of occurrence rows: {with_occurrences}"
        );
    }

    #[test]
    fn unions_exact_and_fuzzy_tokens_and_ranks_declarations_first() {
        let mut declaration = fn_entity(0, "router_handler");
        declaration.kind = EntityKind::Function;
        let mut exact_call = fn_entity(1, "router");
        exact_call.kind = EntityKind::Call;
        let mut incidental_var = fn_entity(2, "handler");
        incidental_var.kind = EntityKind::Variable;
        let db = context_db(
            vec![declaration, exact_call, incidental_var],
            vec![
                "src/handler.rs".into(),
                "src/router.rs".into(),
                "src/other.rs".into(),
            ],
        );

        let env = envelope(
            "context_pack",
            &format!(
                r#"{{"dbPath":"{}","query":"router handler"}}"#,
                db.display()
            ),
        );
        assert_eq!(env["ok"], true, "{env}");
        let symbols = env["data"]["symbols"].as_array().expect("symbols array");
        let names: Vec<_> = symbols
            .iter()
            .map(|symbol| symbol["name"].as_str().unwrap())
            .collect();
        assert!(names.contains(&"router_handler"), "{env}");
        assert!(names.contains(&"handler"), "{env}");
        assert!(
            !names.contains(&"router"),
            "occurrence rows are hidden by default: {env}"
        );
        assert_eq!(symbols[0]["name"], "router_handler", "{env}");
    }

    #[test]
    fn ranks_files_matching_more_query_tokens_before_complexity() {
        let topical = fn_entity(0, "route_handler");
        let mut incidental = fn_entity(1, "route");
        incidental.kind = EntityKind::ControlFlow;
        let mut entities = vec![topical];
        entities.extend((0..8).map(|_| incidental.clone()));
        let db = context_db(
            entities,
            vec!["src/topical.rs".into(), "src/incidental.rs".into()],
        );

        let env = envelope(
            "context_pack",
            &format!(r#"{{"dbPath":"{}","query":"route handler"}}"#, db.display()),
        );
        assert_eq!(env["ok"], true, "{env}");
        let files = env["data"]["files"].as_array().expect("files array");
        assert_eq!(files[0]["path"], "src/topical.rs", "{env}");
    }

    #[test]
    fn exact_declaration_outranks_complex_fuzzy_helper_and_exact_call() {
        let declaration = fn_entity(0, "route_handler");
        let helper = fn_entity(1, "test_route_handler_helper");
        let mut call = fn_entity(1, "route_handler");
        call.kind = EntityKind::Call;
        let mut entities = vec![declaration, helper, call];
        entities.extend((0..12).map(|_| {
            let mut flow = fn_entity(1, "if");
            flow.kind = EntityKind::ControlFlow;
            flow
        }));
        let db = context_db(
            entities,
            vec![
                "src/route.rs".into(),
                "tests/test_route_handler_helper.rs".into(),
            ],
        );

        let env = envelope(
            "context_pack",
            &format!(r#"{{"dbPath":"{}","query":"route_handler"}}"#, db.display()),
        );
        assert_eq!(env["ok"], true, "{env}");
        let files = env["data"]["files"].as_array().expect("files array");
        assert_eq!(files[0]["path"], "src/route.rs", "{env}");
    }

    #[test]
    fn exact_path_or_basename_outranks_a_complex_fuzzy_path() {
        let mut entities = vec![fn_entity(0, "primary"), fn_entity(1, "secondary")];
        entities.extend((0..12).map(|_| {
            let mut flow = fn_entity(1, "if");
            flow.kind = EntityKind::ControlFlow;
            flow
        }));
        let db = context_db(
            entities,
            vec!["src/router.rs".into(), "src/router.rs_helper.rs".into()],
        );

        for query in ["src/router.rs", "router.rs"] {
            let env = envelope(
                "context_pack",
                &format!(r#"{{"dbPath":"{}","query":"{query}"}}"#, db.display()),
            );
            assert_eq!(env["ok"], true, "{env}");
            let files = env["data"]["files"].as_array().expect("files array");
            assert_eq!(files[0]["path"], "src/router.rs", "{env}");
        }
    }

    #[test]
    fn treats_like_wildcards_as_literal_query_text() {
        let literal = fn_entity(0, "literal%_route");
        let wildcard_lookalike = fn_entity(1, "literalXXroute");
        let db = context_db(
            vec![literal, wildcard_lookalike],
            vec![
                "src/literal%_route.rs".into(),
                "src/literalXXroute.rs".into(),
            ],
        );

        let env = envelope(
            "context_pack",
            &format!(r#"{{"dbPath":"{}","query":"%_"}}"#, db.display()),
        );
        assert_eq!(env["ok"], true, "{env}");
        let files = env["data"]["files"].as_array().expect("files array");
        assert!(
            files
                .iter()
                .any(|file| file["path"] == "src/literal%_route.rs"),
            "{env}"
        );
        assert!(
            !files
                .iter()
                .any(|file| file["path"] == "src/literalXXroute.rs"),
            "{env}"
        );
    }
}

fn temp_db(tag: &str) -> PathBuf {
    let dir = temp_dir(tag);
    std::fs::create_dir_all(dir.join(".git")).expect("fixture metadata dir");
    let db = dir.join(".git/index.db");
    let _ = std::fs::remove_file(&db);
    db
}

static REPO_ROOTS: OnceLock<Mutex<std::collections::HashMap<String, PathBuf>>> = OnceLock::new();

fn persist_fixture(db: &std::path::Path, mut output: ExtractOutput, graph: &ResolvedGraph) {
    let default_root = db.parent().unwrap().parent().unwrap();
    let absolute: Vec<_> = output
        .files
        .iter()
        .filter(|file| std::path::Path::new(file).is_absolute())
        .collect();
    let mut root = if let Some(first) = absolute.first() {
        std::path::Path::new(first).parent().unwrap().to_path_buf()
    } else {
        default_root.to_path_buf()
    };
    for file in &absolute {
        while !std::path::Path::new(file).starts_with(&root) {
            root = root.parent().unwrap().to_path_buf();
        }
    }
    output.file_meta.clear();
    for file in &output.files {
        let path = root.join(file);
        if !path.exists() {
            std::fs::create_dir_all(path.parent().unwrap()).expect("fixture source dir");
            std::fs::write(&path, "fn fixture() {}\n").expect("fixture source");
        }
        let state = varde_code::scan::list_source_files(path.to_str().unwrap())
            .expect("source metadata")
            .remove(0);
        output.file_meta.push(FileMeta {
            mtime: state.mtime,
            size: state.size,
            content_hash: state.content_hash.unwrap_or_default(),
        });
    }
    persist::persist(db, &[output], graph, &root).expect("persist");
    REPO_ROOTS
        .get_or_init(Default::default)
        .lock()
        .unwrap()
        .insert(db.display().to_string(), root);
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

fn envelope(mode: &str, input: &str) -> serde_json::Value {
    let mut value: serde_json::Value = serde_json::from_str(input).expect("query JSON");
    if let Some(db) = value.get("dbPath").and_then(|value| value.as_str())
        && let Some(root) = REPO_ROOTS
            .get_or_init(Default::default)
            .lock()
            .unwrap()
            .get(db)
    {
        value["repoRoot"] = serde_json::json!(root);
    }
    let stdout = query::run_mode(mode, &value.to_string());
    serde_json::from_str(&stdout).expect("envelope is JSON")
}

fn git(repo: &std::path::Path, args: &[&str]) {
    let status = std::process::Command::new("git")
        .args(args)
        .current_dir(repo)
        .status()
        .expect("git runs");
    assert!(status.success(), "git {args:?} failed");
}

fn git_init(repo: &std::path::Path) {
    git(repo, &["init", "-q"]);
    git(repo, &["config", "user.email", "test@example.com"]);
    git(repo, &["config", "user.name", "Query Test"]);
}

mod map_file_mode {
    use super::*;

    #[test]
    fn returns_persisted_node_info() {
        let db = temp_db("map-file");
        let a = fn_entity(0, "fn_a");
        let output = ExtractOutput {
            entities: vec![a],
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

        let env = envelope(
            "map_file",
            &format!(r#"{{"dbPath":"{}","filePath":"a.rs"}}"#, db.display()),
        );
        assert_eq!(env["ok"], true, "{env}");
        assert_eq!(env["data"]["path"], "a.rs");
        assert_eq!(env["data"]["complexity"], 1);
        assert_eq!(env["data"]["fan_in"], 0);
        assert_eq!(env["data"]["fan_out"], 0);
    }

    #[test]
    fn unknown_file_is_not_found() {
        let db = temp_db("map-file-nf");
        let output = ExtractOutput {
            entities: vec![fn_entity(0, "fn_a")],
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
        let env = envelope(
            "map_file",
            &format!(r#"{{"dbPath":"{}","filePath":"ghost.rs"}}"#, db.display()),
        );
        assert_eq!(env["ok"], false);
        assert_eq!(env["data"]["error"]["code"], "not_found");
    }
}

mod map_symbol_mode {
    use super::*;

    #[test]
    fn returns_persisted_entity_fields() {
        let db = temp_db("map-symbol");
        let mut route = fn_entity(0, "handler");
        route.kind = EntityKind::Route;
        route.method = Some("get".to_string());
        route.path = Some("/api/items".to_string());
        route.status = Some("200".to_string());
        route.body_shape = Some("json".to_string());
        route.enclosing_function = Some("outer".to_string());
        let output = ExtractOutput {
            entities: vec![route],
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

        let env = envelope(
            "map_symbol",
            &format!(r#"{{"dbPath":"{}","name":"handler"}}"#, db.display()),
        );
        assert_eq!(env["ok"], true, "{env}");
        assert_eq!(env["data"]["kind"], "route");
        assert_eq!(env["data"]["file"], "a.rs");
        assert_eq!(env["data"]["method"], "get");
        assert_eq!(env["data"]["path"], "/api/items");
        assert_eq!(env["data"]["status"], "200");
        assert_eq!(env["data"]["body_shape"], "json");
        assert_eq!(env["data"]["enclosing_function"], "outer");
    }

    #[test]
    fn unknown_symbol_is_not_found() {
        let db = temp_db("map-symbol-nf");
        let output = ExtractOutput {
            entities: vec![fn_entity(0, "fn_a")],
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
        let env = envelope(
            "map_symbol",
            &format!(r#"{{"dbPath":"{}","name":"ghost"}}"#, db.display()),
        );
        assert_eq!(env["ok"], false);
        assert_eq!(env["data"]["error"]["code"], "not_found");
    }
}

mod map_path_mode {
    use super::*;

    fn chain_db() -> PathBuf {
        let db = temp_db("map-path");
        let mut entities = Vec::new();
        let mut nodes = Vec::new();
        let mut files = Vec::new();
        for i in 0..3 {
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
        let edges = vec![
            ResolvedEdge {
                from: 0,
                to: EdgeTarget::File(1),
                kind: EdgeKind::Import,
                resolved: true,
                from_entity: None,
            },
            ResolvedEdge {
                from: 1,
                to: EdgeTarget::File(2),
                kind: EdgeKind::Import,
                resolved: true,
                from_entity: None,
            },
        ];
        let graph = ResolvedGraph {
            nodes,
            edges,
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

    #[test]
    fn returns_shortest_dependency_path() {
        let db = chain_db();
        let env = envelope(
            "map_path",
            &format!(
                r#"{{"dbPath":"{}","sourceFile":"f0.rs","targetFile":"f2.rs"}}"#,
                db.display()
            ),
        );
        assert_eq!(env["ok"], true, "{env}");
        let arr = env["data"].as_array().expect("array");
        let paths: Vec<String> = arr
            .iter()
            .map(|v| v.as_str().unwrap().to_string())
            .collect();
        assert_eq!(paths, vec!["f0.rs", "f1.rs", "f2.rs"]);
    }

    #[test]
    fn unreachable_target_is_empty_not_error() {
        let db = chain_db();
        let env = envelope(
            "map_path",
            &format!(
                r#"{{"dbPath":"{}","sourceFile":"f2.rs","targetFile":"f0.rs"}}"#,
                db.display()
            ),
        );
        assert_eq!(env["ok"], true);
        assert_eq!(env["data"], serde_json::json!([]));
    }

    #[test]
    fn unknown_file_is_not_found() {
        let db = chain_db();
        let env = envelope(
            "map_path",
            &format!(
                r#"{{"dbPath":"{}","sourceFile":"ghost.rs","targetFile":"f0.rs"}}"#,
                db.display()
            ),
        );
        assert_eq!(env["ok"], false);
        assert_eq!(env["data"]["error"]["code"], "not_found");
    }
}

mod detect_changes_mode {
    use super::*;

    const V1: &str = "fn alpha() {}\nfn beta() {}\nfn main() { alpha(); beta(); }\n";
    const V2: &str = "fn alpha(x: i32) -> i32 { x }\nfn gamma() {}\nfn main() { alpha(1); }\n";

    #[test]
    fn classifies_added_removed_modified() {
        let repo = temp_dir("dc-repo");
        git_init(&repo);
        let file = repo.join("v1.rs");
        std::fs::write(&file, V1).expect("writes");
        git(&repo, &["add", "v1.rs"]);
        git(&repo, &["commit", "-q", "-m", "before"]);

        // Persist the BEFORE state.
        let db = temp_db("dc-db");
        let abs = file.to_string_lossy().into_owned();
        let parsed = varde_code::parse::parse_source(
            &varde_code::parse::language_for_path(&file).expect("supported"),
            V1,
        );
        let result = varde_code::extract::extract(&parsed, 0);
        let output = ExtractOutput {
            entities: result.entities.clone(),
            symbols: result.symbols.clone(),
            diagnostics: vec![],
            files: vec![abs],
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

        // Apply the AFTER state (uncommitted → working_tree diff).
        std::fs::write(&file, V2).expect("writes");

        let env = envelope(
            "detect_changes",
            &format!(
                r#"{{"dbPath":"{}","repoRoot":"{}","diffMode":"working_tree"}}"#,
                db.display(),
                repo.display()
            ),
        );
        assert_eq!(env["ok"], true, "{env}");
        let arr = env["data"].as_array().expect("array");
        assert_eq!(arr.len(), 1, "one changed file: {env}");
        let entry = &arr[0];
        assert_eq!(entry["file"], "v1.rs");
        assert_eq!(entry["status"], "M");

        let symbols = entry["symbols"].as_array().expect("symbols array");
        let summarize: Vec<(String, String)> = symbols
            .iter()
            .map(|s| {
                (
                    s["name"].as_str().unwrap().to_string(),
                    s["change"].as_str().unwrap().to_string(),
                )
            })
            .collect();
        // beta removed; gamma + x added; main modified (span moved).
        assert!(
            summarize.contains(&("beta".into(), "removed".into())),
            "{summarize:?}"
        );
        assert!(
            summarize.contains(&("gamma".into(), "added".into())),
            "{summarize:?}"
        );
        assert!(
            summarize.contains(&("x".into(), "added".into())),
            "{summarize:?}"
        );
        assert!(
            summarize.contains(&("main".into(), "modified".into())),
            "{summarize:?}"
        );
        assert!(
            !summarize.contains(&("alpha".into(), "modified".into())),
            "alpha span unchanged: {summarize:?}"
        );
    }
}

mod hotspots_mode {
    use super::*;

    #[test]
    fn orders_by_descending_complexity_times_churn() {
        let repo = temp_dir("hot-repo");
        git_init(&repo);

        // hot_a.rs: control flow (if + for) → complexity 3; committed twice.
        let a = repo.join("hot_a.rs");
        std::fs::write(
            &a,
            "pub fn hot_a() {\n    let mut s = 0;\n    for i in 0..3 { s += i; }\n    if s > 2 { s } else { 0 };\n}\n",
        )
        .expect("writes");
        git(&repo, &["add", "hot_a.rs"]);
        git(&repo, &["commit", "-q", "-m", "a1"]);
        std::fs::write(
            &a,
            "pub fn hot_a() {\n    let mut s = 0;\n    for i in 0..5 { s += i; }\n    if s > 2 { s } else { 0 };\n}\n",
        )
        .expect("writes");
        git(&repo, &["add", "hot_a.rs"]);
        git(&repo, &["commit", "-q", "-m", "a2"]);

        // hot_b.rs: no control flow → complexity 1; committed once.
        let b = repo.join("hot_b.rs");
        std::fs::write(&b, "pub fn hot_b() {}\n").expect("writes");
        git(&repo, &["add", "hot_b.rs"]);
        git(&repo, &["commit", "-q", "-m", "b1"]);

        // Extract both files and persist.
        let db = temp_db("hot-db");
        let mut entities = Vec::new();
        let mut files = Vec::new();
        for (i, path) in [&a, &b].into_iter().enumerate() {
            let abs = path.to_string_lossy().into_owned();
            let parsed = varde_code::parse::parse_source(
                &varde_code::parse::language_for_path(path).expect("supported"),
                &std::fs::read_to_string(path).expect("reads"),
            );
            let result = varde_code::extract::extract(&parsed, i as u32);
            entities.extend(result.entities);
            files.push(abs);
        }
        let output = ExtractOutput {
            entities: entities.clone(),
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
        let graph =
            resolve::resolve(&output.entities, &output.symbols, &output.files).expect("resolve");
        persist_fixture(&db, output, &graph);

        let env = envelope("hotspots", &format!(r#"{{"dbPath":"{}"}}"#, db.display()));
        assert_eq!(env["ok"], true, "{env}");
        let arr = env["data"].as_array().expect("array");
        assert_eq!(arr.len(), 2);

        let first = &arr[0];
        let second = &arr[1];
        let a_name = first["file"].as_str().unwrap();
        let b_name = second["file"].as_str().unwrap();
        assert!(a_name.ends_with("hot_a.rs"), "hot_a first: {env}");
        assert!(b_name.ends_with("hot_b.rs"), "hot_b second: {env}");
        // hot_a: complexity 3 * churn 2 = 6; hot_b: 1 * 1 = 1.
        assert_eq!(first["complexity"], 3, "{env}");
        assert_eq!(first["churn"], 2, "{env}");
        assert_eq!(first["score"], 6, "{env}");
        assert_eq!(second["score"], 1, "{env}");
    }

    #[test]
    fn excludes_generated_or_vendored_paths_despite_high_churn() {
        let repo = temp_dir("hot-noise-repo");
        git_init(&repo);

        // A normal source file, committed once → low churn.
        let src = repo.join("real_source.rs");
        std::fs::write(&src, "pub fn real_source() {}\n").expect("writes");
        git(&repo, &["add", "real_source.rs"]);
        git(&repo, &["commit", "-q", "-m", "src1"]);

        // A file under target/ (generated/vendored), committed many times →
        // deliberately high raw churn, to prove the noise filter — not the
        // scoring algorithm — is what excludes it.
        let noisy_dir = repo.join("target");
        std::fs::create_dir_all(&noisy_dir).expect("mkdir");
        let noisy = noisy_dir.join("generated.rs");
        for i in 0..5 {
            std::fs::write(&noisy, format!("pub fn generated_{i}() {{}}\n")).expect("writes");
            git(&repo, &["add", "target/generated.rs"]);
            git(&repo, &["commit", "-q", "-m", &format!("gen{i}")]);
        }

        let db = temp_db("hot-noise-db");
        let mut entities = Vec::new();
        let mut files = Vec::new();
        for (i, path) in [&src, &noisy].into_iter().enumerate() {
            let abs = path.to_string_lossy().into_owned();
            let parsed = varde_code::parse::parse_source(
                &varde_code::parse::language_for_path(path).expect("supported"),
                &std::fs::read_to_string(path).expect("reads"),
            );
            let result = varde_code::extract::extract(&parsed, i as u32);
            entities.extend(result.entities);
            files.push(abs);
        }
        let output = ExtractOutput {
            entities: entities.clone(),
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
        let graph =
            resolve::resolve(&output.entities, &output.symbols, &output.files).expect("resolve");
        persist_fixture(&db, output, &graph);

        let env = envelope("hotspots", &format!(r#"{{"dbPath":"{}"}}"#, db.display()));
        assert_eq!(env["ok"], true, "{env}");
        let arr = env["data"].as_array().expect("array");

        // Only the real source file should be present; the target/ file is
        // excluded despite its higher raw churn.
        assert_eq!(arr.len(), 1, "{env}");
        let only = &arr[0];
        let name = only["file"].as_str().unwrap();
        assert!(
            name.ends_with("real_source.rs"),
            "expected only real_source.rs, got: {env}"
        );
        assert!(
            !arr.iter()
                .any(|e| e["file"].as_str().unwrap_or("").contains("target")),
            "target/ file leaked into hotspots output: {env}"
        );
    }

    #[test]
    fn excludes_non_source_files_despite_high_churn() {
        let repo = temp_dir("hot-nonsource-repo");
        git_init(&repo);

        // A normal source file, committed once → low churn.
        let src = repo.join("real_source.rs");
        std::fs::write(&src, "pub fn real_source() {}\n").expect("writes");
        git(&repo, &["add", "real_source.rs"]);
        git(&repo, &["commit", "-q", "-m", "src1"]);

        // A docs file (non-source — the extractor never parses `.md`), churned
        // many times → deliberately high raw churn, to prove the non-source
        // filter excludes it rather than the scoring collapsing it.
        let doc = repo.join("README.md");
        for i in 0..5 {
            std::fs::write(&doc, format!("# heading {i}\n")).expect("writes");
            git(&repo, &["add", "README.md"]);
            git(&repo, &["commit", "-q", "-m", &format!("doc{i}")]);
        }

        let db = temp_db("hot-nonsource-db");
        // The source file carries an entity; the doc file is a bare `files`
        // row with no entity (exactly how the real build records non-source
        // files it walked but could not parse).
        let src_abs = src.to_string_lossy().into_owned();
        let doc_abs = doc.to_string_lossy().into_owned();
        let parsed = varde_code::parse::parse_source(
            &varde_code::parse::language_for_path(&src).expect("supported"),
            &std::fs::read_to_string(&src).expect("reads"),
        );
        let entities = varde_code::extract::extract(&parsed, 0).entities;
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
                2
            ],
            files: vec![src_abs, doc_abs],
        };
        let graph =
            resolve::resolve(&output.entities, &output.symbols, &output.files).expect("resolve");
        persist_fixture(&db, output, &graph);

        let env = envelope("hotspots", &format!(r#"{{"dbPath":"{}"}}"#, db.display()));
        assert_eq!(env["ok"], true, "{env}");
        let arr = env["data"].as_array().expect("array");

        // Only the real source file should be present; README.md is excluded
        // despite its higher raw churn.
        assert_eq!(arr.len(), 1, "{env}");
        assert!(
            arr[0]["file"].as_str().unwrap().ends_with("real_source.rs"),
            "expected only real_source.rs, got: {env}"
        );
        assert!(
            !arr.iter()
                .any(|e| e["file"].as_str().unwrap_or("").ends_with(".md")),
            "non-source .md file leaked into hotspots output: {env}"
        );
    }
}
