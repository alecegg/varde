//! Resolve evidence for Ruby, PHP, Lua, and Bash.

use varde_code::model::{Entity, EntityKind};
use varde_code::resolve::{EdgeKind, EdgeTarget, ResolvedGraph};

use super::load_fixture_project;

fn entity_id(entities: &[Entity], kind: EntityKind, name: &str) -> u32 {
    entities
        .iter()
        .position(|entity| entity.kind == kind && entity.name == name)
        .unwrap_or_else(|| panic!("missing {kind:?} entity {name}")) as u32
}

fn assert_call_target(graph: &ResolvedGraph, target: u32, context: &str) {
    let calls: Vec<_> = graph
        .edges
        .iter()
        .filter(|edge| edge.kind == EdgeKind::Call && edge.resolved)
        .collect();
    assert_eq!(calls.len(), 1, "{context}: {calls:?}");
    assert_eq!(calls[0].to, EdgeTarget::Entity(target), "{context}");
}

fn assert_resolved_import(graph: &ResolvedGraph, from: &str, to: &str, context: &str) {
    let file_id = |suffix: &str| {
        graph
            .nodes
            .iter()
            .position(|file| file.path.ends_with(suffix))
            .unwrap_or_else(|| panic!("missing file {suffix}")) as u32
    };
    let (from, to) = (file_id(from), file_id(to));
    assert!(
        graph.edges.iter().any(|edge| {
            edge.kind == EdgeKind::Import
                && edge.from == from
                && edge.to == EdgeTarget::File(to)
                && edge.resolved
        }),
        "{context}: {:?}",
        graph.edges
    );
}

#[test]
#[ignore = "Ruby call extraction emits no call edges for method calls in the current resolver pipeline"]
fn ruby_same_file_call_resolves() {
    let (entities, symbols, files) = load_fixture_project("ruby/evidence_calls/same");
    let graph =
        varde_code::resolve::resolve(&entities, &symbols, &files).expect("resolve succeeds");
    assert_call_target(
        &graph,
        entity_id(&entities, EntityKind::Function, "local_target"),
        "Ruby same-file call",
    );
}

#[test]
#[ignore = "Ruby call extraction emits no call edges for method calls in the current resolver pipeline"]
fn ruby_cross_file_call_resolves() {
    let (entities, symbols, files) = load_fixture_project("ruby/evidence_calls/cross");
    let graph =
        varde_code::resolve::resolve(&entities, &symbols, &files).expect("resolve succeeds");
    assert_call_target(
        &graph,
        entity_id(&entities, EntityKind::Function, "remote_target"),
        "Ruby cross-file call",
    );
}

#[test]
fn ruby_import_resolves() {
    let (entities, symbols, files) = load_fixture_project("ruby/evidence_imports");
    let graph =
        varde_code::resolve::resolve(&entities, &symbols, &files).expect("resolve succeeds");
    assert_resolved_import(&graph, "/a.rb", "/b.rb", "Ruby require_relative");
}

#[test]
fn php_same_file_call_resolves() {
    let (entities, symbols, files) = load_fixture_project("php/evidence_calls/same");
    let graph =
        varde_code::resolve::resolve(&entities, &symbols, &files).expect("resolve succeeds");
    assert_call_target(
        &graph,
        entity_id(&entities, EntityKind::Function, "local_target"),
        "PHP same-file call",
    );
}

#[test]
fn php_cross_file_call_resolves() {
    let (entities, symbols, files) = load_fixture_project("php/evidence_calls/cross");
    let graph =
        varde_code::resolve::resolve(&entities, &symbols, &files).expect("resolve succeeds");
    assert_call_target(
        &graph,
        entity_id(&entities, EntityKind::Function, "remote_target"),
        "PHP cross-file call",
    );
}

#[test]
fn php_import_resolves() {
    let (entities, symbols, files) = load_fixture_project("php/evidence_imports");
    let graph =
        varde_code::resolve::resolve(&entities, &symbols, &files).expect("resolve succeeds");
    assert_resolved_import(&graph, "/a.php", "/b.php", "PHP require_once");
}

#[test]
fn lua_same_file_call_resolves() {
    let (entities, symbols, files) = load_fixture_project("lua/evidence_calls/same");
    let graph =
        varde_code::resolve::resolve(&entities, &symbols, &files).expect("resolve succeeds");
    assert_call_target(
        &graph,
        entity_id(&entities, EntityKind::Function, "local_target"),
        "Lua same-file call",
    );
}

#[test]
fn lua_cross_file_call_resolves() {
    let (entities, symbols, files) = load_fixture_project("lua/evidence_calls/cross");
    let graph =
        varde_code::resolve::resolve(&entities, &symbols, &files).expect("resolve succeeds");
    assert_call_target(
        &graph,
        entity_id(&entities, EntityKind::Function, "remote_target"),
        "Lua cross-file call",
    );
}

#[test]
fn bash_same_file_call_resolves() {
    let (entities, symbols, files) = load_fixture_project("bash/evidence_calls/same");
    let graph =
        varde_code::resolve::resolve(&entities, &symbols, &files).expect("resolve succeeds");
    assert_call_target(
        &graph,
        entity_id(&entities, EntityKind::Function, "local_target"),
        "Bash same-file call",
    );
}

#[test]
fn bash_cross_file_call_resolves() {
    let (entities, symbols, files) = load_fixture_project("bash/evidence_calls/cross");
    let graph =
        varde_code::resolve::resolve(&entities, &symbols, &files).expect("resolve succeeds");
    assert_call_target(
        &graph,
        entity_id(&entities, EntityKind::Function, "remote_target"),
        "Bash cross-file call",
    );
}

#[test]
fn bash_import_resolves() {
    let (entities, symbols, files) = load_fixture_project("bash/evidence_imports");
    let graph =
        varde_code::resolve::resolve(&entities, &symbols, &files).expect("resolve succeeds");
    assert_resolved_import(&graph, "/a.sh", "/b.sh", "Bash source");
}
