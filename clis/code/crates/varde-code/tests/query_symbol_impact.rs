//! Symbol impact must follow the selected declaration, not its whole file.
use std::path::PathBuf;
use std::sync::atomic::{AtomicUsize, Ordering};
use varde_code::model::{Entity, EntityKind, ExtractOutput, FileMeta, Span};
use varde_code::resolve::{EdgeKind, EdgeTarget, FileNode, ResolvedEdge, ResolvedGraph};
use varde_code::{persist, query};

static SEQ: AtomicUsize = AtomicUsize::new(0);

struct Fixture {
    root: PathBuf,
    db: PathBuf,
}

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.root);
    }
}

fn entity(file_id: u32, kind: EntityKind, name: &str, start: u32, end: u32) -> Entity {
    Entity {
        kind,
        name: name.into(),
        file_id,
        span: Span {
            start_byte: start,
            end_byte: end,
            start_line: 1,
            start_col: start,
            end_line: 1,
            end_col: end,
        },
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

fn fixture(entities: Vec<Entity>, edges: &[(usize, usize, EdgeKind)]) -> Fixture {
    let seq = SEQ.fetch_add(1, Ordering::Relaxed);
    let root = std::env::temp_dir().join(format!("varde-symbol-{}-{seq}", std::process::id()));
    std::fs::create_dir_all(root.join(".git")).unwrap();
    let nfiles = entities.iter().map(|e| e.file_id).max().unwrap_or(0) as usize + 1;
    let files: Vec<_> = (0..nfiles)
        .map(|i| root.join(format!("f{i}.rs")).to_string_lossy().into_owned())
        .collect();
    let metadata: Vec<FileMeta> = files
        .iter()
        .map(|file| {
            std::fs::write(file, format!("// {}\n", "x".repeat(400))).unwrap();
            let state = varde_code::scan::list_source_files(file).unwrap().remove(0);
            FileMeta {
                mtime: state.mtime,
                size: state.size,
                content_hash: state.content_hash.unwrap_or_default(),
            }
        })
        .collect();
    let graph = ResolvedGraph {
        nodes: files
            .iter()
            .map(|path| FileNode {
                path: path.clone(),
                community_id: None,
                fan_in: 0,
                fan_out: 0,
            })
            .collect(),
        edges: edges
            .iter()
            .map(|&(from, to, kind)| ResolvedEdge {
                from: entities[from].file_id,
                to: EdgeTarget::Entity(to as u32),
                kind,
                resolved: true,
                from_entity: Some(from as u32),
            })
            .collect(),
        communities: vec![],
        clone_bands: vec![],
    };
    let output = ExtractOutput {
        entities,
        symbols: vec![],
        diagnostics: vec![],
        file_meta: metadata,
        files,
    };
    let db = root.join(".git/index.db");
    persist::persist(&db, &[output], &graph, &root).unwrap();
    Fixture { root, db }
}

fn run(fixture: &Fixture, mut input: serde_json::Value) -> serde_json::Value {
    input["repoRoot"] = serde_json::json!(fixture.root);
    input["dbPath"] = serde_json::json!(fixture.db);
    input["fullResults"] = serde_json::json!(true);
    serde_json::from_str(&query::run_mode("symbol_blast_radius", &input.to_string())).unwrap()
}

fn paths(result: &serde_json::Value) -> Vec<String> {
    assert_eq!(result["ok"], true, "{result}");
    result["data"]["blast_radius"]
        .as_array()
        .unwrap()
        .iter()
        .map(|path| {
            PathBuf::from(path.as_str().unwrap())
                .file_name()
                .unwrap()
                .to_string_lossy()
                .into_owned()
        })
        .collect()
}

fn chain_entities() -> Vec<Entity> {
    use EntityKind::{Call, Function};
    vec![
        entity(0, Function, "target", 10, 100),
        entity(0, Function, "sibling", 110, 200),
        entity(0, Function, "local", 210, 300),
        entity(1, Function, "caller", 10, 100),
        entity(1, Function, "unrelated", 110, 200),
        entity(2, Function, "outer", 10, 100),
        entity(3, Function, "outsider", 10, 100),
        entity(0, Call, "target", 230, 240),
        entity(1, Call, "target", 30, 40),
        entity(2, Call, "caller", 30, 40),
        entity(1, Call, "sibling", 130, 140),
        entity(3, Call, "unrelated", 30, 40),
    ]
}

#[test]
fn symbol_chain_excludes_unrelated_siblings_and_their_consumers() {
    use EdgeKind::Call;
    let fixture = fixture(
        chain_entities(),
        &[
            (7, 0, Call),
            (8, 0, Call),
            (9, 3, Call),
            (10, 1, Call),
            (11, 4, Call),
        ],
    );
    let result = run(&fixture, serde_json::json!({"name":"target"}));
    assert_eq!(paths(&result), ["f0.rs", "f1.rs", "f2.rs"]);
    assert_eq!(result["data"]["analysis"]["status"], "partial");
}

#[test]
fn cycles_terminate_and_do_not_report_seed_alone() {
    use EntityKind::{Call, Function};
    let fixture = fixture(
        vec![
            entity(0, Function, "a", 0, 100),
            entity(1, Function, "b", 0, 100),
            entity(0, Call, "b", 10, 20),
            entity(1, Call, "a", 10, 20),
        ],
        &[(2, 1, EdgeKind::Call), (3, 0, EdgeKind::Call)],
    );
    assert_eq!(
        paths(&run(&fixture, serde_json::json!({"name":"a"}))),
        ["f1.rs"]
    );
}

#[test]
fn duplicate_declarations_require_file_disambiguation() {
    let fixture = fixture(
        vec![
            entity(0, EntityKind::Function, "same", 0, 100),
            entity(1, EntityKind::Function, "same", 0, 100),
        ],
        &[],
    );
    let result = run(&fixture, serde_json::json!({"name":"same"}));
    assert_eq!(result["data"]["error"]["code"], "ambiguous_symbol");
    assert!(
        paths(&run(
            &fixture,
            serde_json::json!({"name":"same","filePath":"f1.rs"})
        ))
        .is_empty()
    );
}

#[test]
fn kind_filter_selects_a_declaration_and_rejects_occurrence_kinds() {
    let fixture = fixture(
        vec![
            entity(0, EntityKind::Function, "same", 0, 100),
            entity(0, EntityKind::Variable, "same", 120, 130),
        ],
        &[],
    );
    assert!(
        paths(&run(
            &fixture,
            serde_json::json!({"name":"same","kind":"function"})
        ))
        .is_empty()
    );
    let result = run(&fixture, serde_json::json!({"name":"same","kind":"call"}));
    assert_eq!(result["data"]["error"]["code"], "invalid_input");
}

#[test]
fn call_occurrence_is_not_selected_as_a_declaration() {
    let fixture = fixture(
        vec![
            entity(0, EntityKind::Call, "target", 0, 10),
            entity(1, EntityKind::Function, "target", 0, 100),
        ],
        &[],
    );
    let result = run(&fixture, serde_json::json!({"name":"target"}));
    assert!(
        result["data"]["declaring_file"]
            .as_str()
            .unwrap()
            .ends_with("f1.rs")
    );
}

#[test]
fn same_file_overloads_remain_explicitly_ambiguous() {
    let fixture = fixture(
        vec![
            entity(0, EntityKind::Function, "same", 0, 100),
            entity(0, EntityKind::Function, "same", 110, 200),
        ],
        &[],
    );
    let result = run(
        &fixture,
        serde_json::json!({"name":"same","filePath":"f0.rs"}),
    );
    assert_eq!(result["data"]["error"]["code"], "ambiguous_symbol");
}

#[test]
fn inheritance_sources_retain_their_declaration_identity() {
    use EntityKind::{Call, Class, Function};
    let fixture = fixture(
        vec![
            entity(0, Class, "Base", 0, 100),
            entity(1, Class, "Child", 0, 100),
            entity(2, Function, "construct", 0, 100),
            entity(2, Call, "Child", 10, 20),
        ],
        &[(1, 0, EdgeKind::Extends), (3, 1, EdgeKind::Call)],
    );
    assert_eq!(
        paths(&run(&fixture, serde_json::json!({"name":"Base"}))),
        ["f1.rs", "f2.rs"]
    );
}

#[test]
fn anonymous_callable_does_not_infect_unrelated_outer_callers() {
    use EntityKind::{Call, CallableBoundary, Function};
    let fixture = fixture(
        vec![
            entity(0, Function, "target", 0, 100),
            entity(1, Function, "outer", 0, 200),
            entity(1, CallableBoundary, "", 20, 100),
            entity(1, Call, "target", 30, 40),
            entity(2, Function, "consumer", 0, 100),
            entity(2, Call, "outer", 10, 20),
        ],
        &[(3, 0, EdgeKind::Call), (5, 1, EdgeKind::Call)],
    );
    let result = run(&fixture, serde_json::json!({"name":"target"}));
    assert_eq!(paths(&result), ["f1.rs"]);
    assert_eq!(result["data"]["analysis"]["unmapped_owners"], 1);
}

#[test]
fn top_level_call_reports_its_file_without_guessing_a_caller() {
    let fixture = fixture(
        vec![
            entity(0, EntityKind::Function, "target", 0, 100),
            entity(1, EntityKind::Call, "target", 10, 20),
        ],
        &[(1, 0, EdgeKind::Call)],
    );
    let result = run(&fixture, serde_json::json!({"name":"target"}));
    assert_eq!(paths(&result), ["f1.rs"]);
    assert_eq!(result["data"]["analysis"]["unmapped_owners"], 1);
}

#[test]
fn extracted_typescript_call_chain_does_not_follow_an_unrelated_function() {
    let fixture = fixture(vec![entity(0, EntityKind::Function, "dummy", 0, 10)], &[]);
    std::fs::remove_file(fixture.root.join("f0.rs")).unwrap();
    for (file, source) in [
        (
            "target.ts",
            "export function target() { return 1; }\nexport function sibling() { return 2; }\n",
        ),
        (
            "middle.ts",
            "import { target, sibling } from './target';\nexport function caller() { return target(); }\nexport function other() { return sibling(); }\n",
        ),
        (
            "consumer.ts",
            "import { caller } from './middle';\nexport function consume() { return caller(); }\n",
        ),
        (
            "outsider.ts",
            "import { other } from './middle';\nexport function outside() { return other(); }\n",
        ),
    ] {
        std::fs::write(fixture.root.join(file), source).unwrap();
    }
    let output = varde_code::scan::run(fixture.root.to_str().unwrap()).unwrap();
    let graph =
        varde_code::resolve::resolve(&output.entities, &output.symbols, &output.files).unwrap();
    assert!(
        graph
            .edges
            .iter()
            .any(|edge| edge.kind == EdgeKind::Call && edge.resolved),
        "no resolved calls: {:?}; entities: {:?}",
        graph.edges,
        output
            .entities
            .iter()
            .map(|e| (e.kind, &e.name, e.file_id))
            .collect::<Vec<_>>()
    );
    persist::persist(&fixture.db, &[output], &graph, &fixture.root).unwrap();
    let result = run(
        &fixture,
        serde_json::json!({"name":"target","kind":"function"}),
    );
    assert_eq!(paths(&result), ["consumer.ts", "middle.ts"], "{result}");
    assert_eq!(result["data"]["analysis"]["unmapped_owners"], 0);
}

#[test]
fn reexport_does_not_resolve_to_an_unrelated_local_declaration() {
    use EntityKind::{Call, Export, Function};
    let fixture = fixture(
        vec![
            entity(0, Export, "target", 200, 230),
            entity(0, Function, "target", 0, 100),
            entity(1, Function, "caller", 0, 100),
            entity(1, Call, "target", 10, 20),
        ],
        &[(3, 0, EdgeKind::Call)],
    );
    let result = run(&fixture, serde_json::json!({"name":"target"}));
    assert!(paths(&result).is_empty());
    assert_eq!(result["data"]["analysis"]["unresolved_edges"], 1);
}
