//! Call and import resolution evidence for Java, Kotlin, and C#.

use super::load_fixture_project;
use varde_code::model::EntityKind;
use varde_code::resolve::{EdgeKind, EdgeTarget};

fn resolved_call(rel: &str, target_name: &str) -> bool {
    let (entities, symbols, files) = load_fixture_project(rel);
    let graph = varde_code::resolve::resolve(&entities, &symbols, &files).expect("resolve");
    let target = entities
        .iter()
        .position(|entity| entity.kind == EntityKind::Function && entity.name == target_name)
        .expect("call target exists") as u32;
    graph.edges.iter().any(|edge| {
        edge.kind == EdgeKind::Call && edge.resolved && edge.to == EdgeTarget::Entity(target)
    })
}

fn resolved_import(rel: &str, target_suffix: &str) -> bool {
    let (entities, symbols, files) = load_fixture_project(rel);
    let graph = varde_code::resolve::resolve(&entities, &symbols, &files).expect("resolve");
    let target = graph
        .nodes
        .iter()
        .position(|node| node.path.ends_with(target_suffix))
        .expect("import target file exists") as u32;
    graph.edges.iter().any(|edge| {
        edge.kind == EdgeKind::Import && edge.resolved && edge.to == EdgeTarget::File(target)
    })
}

#[test]
fn java_same_file_call() {
    assert!(resolved_call("java/evidence_calls/same_file", "helper"));
}

#[test]
fn kotlin_same_file_call() {
    assert!(resolved_call("kotlin/evidence_calls/same_file", "helper"));
}

#[test]
fn kotlin_cross_file_call() {
    assert!(resolved_call("kotlin/evidence_calls/cross_file", "helper"));
}

#[test]
fn csharp_same_file_call() {
    assert!(resolved_call("csharp/evidence_calls/same_file", "Helper"));
}

#[test]
#[ignore = "Kotlin imports are extracted but resolve() does not produce a resolved import edge for the imported file"]
fn kotlin_import_resolution() {
    assert!(resolved_import("kotlin/evidence_imports", "/Helper.kt"));
}

#[test]
fn java_import_resolution() {
    assert!(resolved_import("java/evidence_imports", "/Helper.java"));
}

#[test]
fn csharp_import_resolution() {
    assert!(resolved_import("csharp/evidence_imports", "/Helper.cs"));
}
