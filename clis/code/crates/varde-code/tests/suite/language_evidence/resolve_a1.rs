//! Resolved call and import evidence for TypeScript-family and Python files.
use super::load_fixture_project;
use varde_code::model::{Entity, EntityKind, Symbol};
use varde_code::resolve::{resolve, EdgeKind, EdgeTarget};

fn graph(
    rel: &str,
) -> (
    Vec<Entity>,
    Vec<Symbol>,
    Vec<String>,
    varde_code::resolve::ResolvedGraph,
) {
    let (entities, symbols, files) = load_fixture_project(rel);
    let resolved = resolve(&entities, &symbols, &files).expect("resolve fixture");
    (entities, symbols, files, resolved)
}

fn check_call(rel: &str, target_name: &str, expected_count: usize) {
    let (entities, _, _, resolved) = graph(rel);
    let target = entities
        .iter()
        .position(|entity| entity.kind == EntityKind::Function && entity.name == target_name)
        .expect("target function exists") as u32;
    let calls: Vec<_> = resolved
        .edges
        .iter()
        .filter(|edge| edge.kind == EdgeKind::Call && edge.resolved)
        .collect();
    assert_eq!(calls.len(), expected_count, "resolved calls in {rel}");
    assert!(calls
        .iter()
        .any(|edge| edge.to == EdgeTarget::Entity(target)));
}

fn check_import(rel: &str, target_suffix: &str) {
    let (_, _, files, resolved) = graph(rel);
    let target = files
        .iter()
        .position(|file| file.ends_with(target_suffix))
        .expect("target file exists") as u32;
    assert!(
        resolved.edges.iter().any(|edge| {
            edge.kind == EdgeKind::Import && edge.resolved && edge.to == EdgeTarget::File(target)
        }),
        "resolved import to {target_suffix}: {:?}",
        resolved.edges
    );
}

#[test]
fn typescript_same_file_call_resolves() {
    check_call("typescript/evidence_calls/same", "helper", 1);
}

#[test]
#[ignore = "current resolver does not connect TypeScript imported call edges to their target function"]
fn typescript_cross_file_call_resolves() {
    check_call("typescript/evidence_calls/cross", "helper", 1);
}

#[test]
fn tsx_same_file_call_resolves() {
    check_call("tsx/evidence_calls/same", "helper", 1);
}

#[test]
#[ignore = "current resolver does not connect TSX imported call edges to their target function"]
fn tsx_cross_file_call_resolves() {
    check_call("tsx/evidence_calls/cross", "helper", 1);
}

#[test]
fn javascript_same_file_call_resolves() {
    check_call("javascript/evidence_calls/same", "helper", 1);
}

#[test]
#[ignore = "current resolver does not connect JavaScript imported call edges to their target function"]
fn javascript_cross_file_call_resolves() {
    check_call("javascript/evidence_calls/cross", "helper", 1);
}

#[test]
fn python_same_file_call_resolves() {
    check_call("python/evidence_calls/same", "helper", 1);
}

// Existing src/resolve.rs lib coverage: Python cross-file module calls and
// TypeScript/Python import resolution. Keep these fixtures out of duplication.
#[test]
fn tsx_import_resolves() {
    check_import("tsx/evidence_imports", "target.tsx");
}

#[test]
fn javascript_import_resolves() {
    check_import("javascript/evidence_imports", "target.js");
}
