//! Integration tests for `varde-workflow concept map`.

mod common;

use common::{bin, json_data, temp_bundle};
use std::process::Command;

fn write_concept(bundle: &std::path::Path, slug: &str, frontmatter: &str) {
    let path = bundle.join(format!("{slug}.md"));
    std::fs::create_dir_all(path.parent().unwrap()).unwrap();
    std::fs::write(path, format!("---\n{frontmatter}---\nbody\n")).unwrap();
}

#[test]
fn map_command_writes_deterministic_root_and_type_maps() {
    let bundle = temp_bundle("maps-cli");
    std::fs::write(bundle.join("index.md"), "---\nokf_version: 0.2\n---\n").unwrap();
    write_concept(
        &bundle,
        "decision/old",
        "type: decision\ntitle: Old\ndescription: Old note.\nstatus: deprecated\n",
    );
    write_concept(
        &bundle,
        "decision/new",
        "type: decision\ntitle: New\ndescription: New note.\naliases:\n  - fresh\n",
    );

    let first = Command::new(bin())
        .args(["concept", "map", "--bundle"])
        .arg(&bundle)
        .args(["--json"])
        .output()
        .unwrap();
    assert!(
        first.status.success(),
        "stderr: {}",
        String::from_utf8_lossy(&first.stderr)
    );
    let data = json_data(&first.stdout);
    assert_eq!(data["entries"], 2);
    assert_eq!(data["root"], "index.md");
    assert_eq!(data["type_maps"][0], "decision/index.md");

    let root_first = std::fs::read(bundle.join("index.md")).unwrap();
    let type_first = std::fs::read(bundle.join("decision/index.md")).unwrap();
    let second = Command::new(bin())
        .args(["concept", "map", "--bundle"])
        .arg(&bundle)
        .output()
        .unwrap();
    assert!(second.status.success());
    assert_eq!(root_first, std::fs::read(bundle.join("index.md")).unwrap());
    assert_eq!(
        type_first,
        std::fs::read(bundle.join("decision/index.md")).unwrap()
    );

    let root = String::from_utf8(root_first).unwrap();
    assert!(root.contains("## Active"));
    assert!(root.contains("## Deprecated"));
    assert!(root.contains("Aliases: fresh"));
    assert!(root.contains("Status: deprecated"));
}
