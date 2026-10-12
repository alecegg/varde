//! Enforces the workspace dependency layering with `cargo metadata`.
//!
//! Normal, build, and dev dependencies are all checked, so a test-only edge
//! cannot reintroduce a cross-module coupling.

use std::collections::BTreeMap;
use std::process::Command;

const APP: &str = "varde";
const CORE: &str = "varde-core";
const CONTRACTS: &str = "varde-contracts";

/// Module crates, each with the crates of its own family.
const FAMILIES: &[&[&str]] = &[
    &["varde-code"],
    &["varde-workflow", "varde-workflow-core"],
    &["varde-toz", "varde-toz-core"],
    &["varde-learn", "varde-learn-core"],
    &["varde-doc"],
];

/// Workspace package name -> names of its dependencies.
type Graph = BTreeMap<String, Vec<String>>;

fn allowed(package: &str, dep: &str) -> bool {
    match package {
        CORE => false,
        CONTRACTS => dep == CORE,
        APP => true,
        _ => FAMILIES
            .iter()
            .find(|family| family.contains(&package))
            .is_some_and(|family| dep == CORE || dep == CONTRACTS || family.contains(&dep)),
    }
}

fn violations(graph: &Graph) -> Vec<String> {
    let mut found = Vec::new();
    for (package, deps) in graph {
        let known = package == APP
            || package == CORE
            || package == CONTRACTS
            || FAMILIES
                .iter()
                .any(|family| family.contains(&package.as_str()));
        if !known {
            found.push(format!("{package}: not a known workspace crate"));
            continue;
        }
        for dep in deps.iter().filter(|dep| graph.contains_key(*dep)) {
            if !allowed(package, dep) {
                found.push(format!("{package} must not depend on {dep}"));
            }
        }
    }
    found
}

fn workspace_graph() -> Graph {
    let output = Command::new(env!("CARGO"))
        .args(["metadata", "--format-version", "1", "--no-deps", "--locked"])
        .current_dir(env!("CARGO_MANIFEST_DIR"))
        .output()
        .expect("run cargo metadata");
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let metadata: serde_json::Value =
        serde_json::from_slice(&output.stdout).expect("metadata json");
    metadata["packages"]
        .as_array()
        .expect("packages")
        .iter()
        .map(|package| {
            let name = package["name"].as_str().expect("name").to_owned();
            let deps = package["dependencies"]
                .as_array()
                .expect("dependencies")
                .iter()
                .map(|dep| dep["name"].as_str().expect("dep name").to_owned())
                .collect();
            (name, deps)
        })
        .collect()
}

fn graph(edges: &[(&str, &[&str])]) -> Graph {
    edges
        .iter()
        .map(|(name, deps)| {
            (
                (*name).to_owned(),
                deps.iter().map(|d| (*d).to_owned()).collect(),
            )
        })
        .collect()
}

#[test]
fn seeded_violations_are_flagged() {
    let bad = graph(&[
        (CORE, &[CONTRACTS]),
        (CONTRACTS, &[CORE, "varde-code"]),
        ("varde-code", &[CORE, "varde-toz"]),
        ("varde-toz", &["varde-toz-core", "serde"]),
        ("varde-toz-core", &["varde-workflow-core"]),
        ("varde-workflow-core", &[]),
        ("varde-workflow", &[]),
        ("varde-learn", &[]),
        ("varde-learn-core", &[]),
        (APP, &["varde-code", CORE]),
    ]);
    assert_eq!(
        violations(&bad),
        [
            "varde-code must not depend on varde-toz",
            "varde-contracts must not depend on varde-code",
            "varde-core must not depend on varde-contracts",
            "varde-toz-core must not depend on varde-workflow-core",
        ]
    );
}

#[test]
fn unknown_workspace_crate_is_flagged() {
    let unknown = graph(&[(CORE, &[]), ("varde-extra", &[CORE])]);
    assert_eq!(
        violations(&unknown),
        ["varde-extra: not a known workspace crate"]
    );
}

#[test]
fn workspace_follows_layering_rules() {
    let graph = workspace_graph();
    assert!(
        graph.len() >= 10,
        "expected the full workspace, found {:?}",
        graph.keys()
    );
    let found = violations(&graph);
    assert!(
        found.is_empty(),
        "dependency rule violations:\n{}",
        found.join("\n")
    );
}
