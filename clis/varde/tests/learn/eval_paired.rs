use crate::common::{MockHarness, write_output_skill};
use serde_json::{Value, json};
use std::{fs, path::Path};
use tempfile::tempdir;

fn read(path: &Path) -> Value {
    serde_json::from_slice(&fs::read(path).unwrap()).unwrap()
}

fn trace(dir: &Path) -> std::path::PathBuf {
    let path = dir.join("trace.json");
    fs::write(
        &path,
        json!({
            "type": "result",
            "subtype": "success",
            "is_error": false,
            "result": "{\"results\":[{\"assertion\":\"works\",\"verdict\":\"PASS\",\"evidence\":\"yes\"}]}"
        })
        .to_string(),
    )
    .unwrap();
    path
}

#[test]
fn summarizes_paired_rates_and_labels_three_runs_as_comparison() {
    let mock = MockHarness::new();
    let skill = tempdir().unwrap();
    let workspace = tempdir().unwrap();
    write_output_skill(
        skill.path(),
        r#"{"evals":[{"id":"one","prompt":"request","assert":[{"kind":"event_order","events":["results","PASS"]}]}]}"#,
    );
    mock.command(
        &trace(mock.root()),
        0,
        [
            "eval",
            "output",
            skill.path().to_str().unwrap(),
            "--workspace",
            workspace.path().to_str().unwrap(),
            "--runs",
            "3",
        ],
    )
    .assert()
    .success();

    let benchmark = read(&workspace.path().join("iteration-1/benchmark.json"));
    let result = &benchmark["result"];
    assert_eq!(result["status"], "fail");
    assert_eq!(result["evidence"], "comparison");
    assert_eq!(result["included_runs"]["current"], 3);
    assert_eq!(result["included_runs"]["candidate"], 3);
    assert_eq!(result["cases"][0]["current"]["pass_rate"], 0.0);
    assert_eq!(result["cases"][0]["candidate"]["pass_rate"], 0.0);
    assert_eq!(result["cases"][0]["current"]["variance"], 0.0);
}

#[test]
fn labels_short_samples_as_screens_and_excludes_inconclusive_runs() {
    let mock = MockHarness::new();
    let skill = tempdir().unwrap();
    let workspace = tempdir().unwrap();
    write_output_skill(
        skill.path(),
        r#"{"evals":[{"id":"one","prompt":"request","assertions":[] }]}"#,
    );
    mock.command(
        &trace(mock.root()),
        0,
        [
            "eval",
            "output",
            skill.path().to_str().unwrap(),
            "--workspace",
            workspace.path().to_str().unwrap(),
            "--runs",
            "2",
        ],
    )
    .assert()
    .success();

    let benchmark = read(&workspace.path().join("iteration-1/benchmark.json"));
    let result = &benchmark["result"];
    assert_eq!(result["status"], "inconclusive");
    assert_eq!(result["evidence"], "screen");
    assert_eq!(result["included_runs"]["current"], 0);
    assert_eq!(result["inconclusive_runs"]["current"], 2);
    assert!(result["cases"][0]["current"]["pass_rate"].is_null());
}
