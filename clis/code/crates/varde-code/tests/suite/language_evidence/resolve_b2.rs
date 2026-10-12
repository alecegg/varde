//! Evidence cases for resolve b2.

use varde_code::model::EntityKind;
use varde_code::resolve::{self, EdgeKind, EdgeTarget};

use super::load_fixture_project;

fn assert_resolved_call(rel: &str, target: &str) {
    let (entities, symbols, files) = load_fixture_project(rel);
    let graph = resolve::resolve(&entities, &symbols, &files).expect("resolve succeeds");
    let call = graph
        .edges
        .iter()
        .find(|edge| edge.kind == EdgeKind::Call)
        .unwrap_or_else(|| panic!("call edge exists: {:?}", graph.edges));
    let target_id = entities
        .iter()
        .position(|entity| entity.kind == EntityKind::Function && entity.name == target)
        .unwrap_or_else(|| panic!("{target} definition exists")) as u32;
    assert!(call.resolved, "call resolves: {call:?}");
    assert_eq!(call.to, EdgeTarget::Entity(target_id));
}

#[test]
fn scala_same_file_call_resolves() {
    assert_resolved_call("scala/evidence_calls/same_file", "helper");
}

#[test]
fn scala_cross_file_call_resolves() {
    assert_resolved_call("scala/evidence_calls/cross_file", "helper");
}

#[test]
fn dart_same_file_call_resolves() {
    assert_resolved_call("dart/evidence_calls/same_file", "greet");
}

#[test]
fn dart_cross_file_call_resolves() {
    assert_resolved_call("dart/evidence_calls/cross_file", "greet");
}

#[test]
fn swift_same_file_call_resolves() {
    assert_resolved_call("swift/evidence_calls/same_file", "helper");
}

#[test]
fn swift_import_resolves_to_local_file() {
    let (entities, symbols, files) = load_fixture_project("swift/evidence_imports");
    let graph = resolve::resolve(&entities, &symbols, &files).expect("resolve succeeds");
    let importer = files
        .iter()
        .position(|file| file.ends_with("/App.swift"))
        .expect("App.swift exists") as u32;
    let imported = files
        .iter()
        .position(|file| file.ends_with("/Helpers.swift"))
        .expect("Helpers.swift exists") as u32;
    assert!(
        graph.edges.iter().any(|edge| {
            edge.kind == EdgeKind::Import
                && edge.from == importer
                && edge.to == EdgeTarget::File(imported)
                && edge.resolved
        }),
        "Swift import resolves to local file: {:?}",
        graph.edges
    );
}
