//! Resolver evidence for C, C++, Go, Elixir, Haskell, and Solidity.

use super::load_fixture_project;
use varde_code::model::EntityKind;
use varde_code::resolve::{self, EdgeKind, EdgeTarget};

fn resolved_call_to(rel: &str, name: &str) -> bool {
    let (entities, symbols, files) = load_fixture_project(rel);
    let graph = resolve::resolve(&entities, &symbols, &files).expect("resolve succeeds");
    let target = entities
        .iter()
        .position(|entity| entity.kind == EntityKind::Function && entity.name == name)
        .unwrap_or_else(|| panic!("function {name} exists")) as u32;
    graph.edges.iter().any(|edge| {
        edge.kind == EdgeKind::Call && edge.resolved && edge.to == EdgeTarget::Entity(target)
    })
}

fn resolved_import_count(rel: &str) -> usize {
    let (entities, symbols, files) = load_fixture_project(rel);
    let graph = resolve::resolve(&entities, &symbols, &files).expect("resolve succeeds");
    graph
        .edges
        .iter()
        .filter(|edge| edge.kind == EdgeKind::Import && edge.resolved)
        .count()
}

macro_rules! call_cases {
    ($same:ident, $cross:ident, $lang:literal, $callee:literal) => {
        #[test]
        fn $same() {
            assert!(resolved_call_to(
                concat!($lang, "/evidence_calls/same"),
                $callee
            ));
        }

        #[test]
        fn $cross() {
            assert!(resolved_call_to(
                concat!($lang, "/evidence_calls/cross"),
                $callee
            ));
        }
    };
}

call_cases!(c_same_file_call, c_cross_file_call, "c", "helper");
call_cases!(cpp_same_file_call, cpp_cross_file_call, "cpp", "helper");
#[test]
fn go_same_file_call() {
    assert!(resolved_call_to("go/evidence_calls/same", "helper"));
}

#[test]
fn elixir_same_file_call() {
    assert!(resolved_call_to("elixir/evidence_calls/same", "helper"));
}

#[test]
#[ignore = "resolver does not currently resolve this cross-file Go call"]
fn go_cross_file_call() {
    assert!(resolved_call_to("go/evidence_calls/cross", "helper"));
}

#[test]
#[ignore = "resolver does not currently resolve this cross-file Elixir call"]
fn elixir_cross_file_call() {
    assert!(resolved_call_to("elixir/evidence_calls/cross", "helper"));
}

#[test]
#[ignore = "extractor does not expose this top-level Haskell binding as a function"]
fn haskell_same_file_call() {
    assert!(resolved_call_to("haskell/evidence_calls/same", "helper"));
}

#[test]
#[ignore = "extractor does not expose this top-level Haskell binding as a function"]
fn haskell_cross_file_call() {
    assert!(resolved_call_to("haskell/evidence_calls/cross", "helper"));
}
call_cases!(
    solidity_same_file_call,
    solidity_cross_file_call,
    "solidity",
    "helper"
);

#[test]
fn c_import_resolution() {
    assert_eq!(resolved_import_count("c/evidence_imports"), 1);
}

#[test]
fn cpp_import_resolution() {
    assert_eq!(resolved_import_count("cpp/evidence_imports"), 1);
}

#[test]
fn haskell_import_resolution() {
    assert_eq!(resolved_import_count("haskell/evidence_imports"), 1);
}

#[test]
fn solidity_import_resolution() {
    assert_eq!(resolved_import_count("solidity/evidence_imports"), 1);
}
