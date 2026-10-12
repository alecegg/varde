use std::fs;

use tempfile::TempDir;
use varde_learn_core::{
    FrictionAddMode, FrictionAddRequest, FrictionListRequest, PageRequest, Store,
    friction_log::{self, Event, ItemAdded},
};

#[test]
fn append_redacts_event_body_and_records_replacement_count() {
    let store = TempDir::new().unwrap();
    let body = ItemAdded {
        title: "credential AKIAIOSFODNN7EXAMPLE leaked".to_owned(),
        source: "test".to_owned(),
        repo_root: None,
        target: None,
    };
    let event = Event::at("2026-10-11T12:00:00.000Z", None, body);
    let mut log = friction_log::open_log(store.path()).unwrap();

    friction_log::append(store.path(), &mut log, &event).unwrap();

    let text = fs::read_to_string(store.path().join(friction_log::LOG_FILE_NAME)).unwrap();
    let value: serde_json::Value = serde_json::from_str(text.trim()).unwrap();
    assert!(!text.contains("AKIAIOSFODNN7EXAMPLE"));
    assert_eq!(
        value["body"]["title"],
        "credential [redacted:aws-key] leaked"
    );
    assert_eq!(value["redacted"], 1);
    assert_eq!(value["id"], event.id);
}

#[test]
fn redacted_item_keeps_occurrence_and_slug_after_cache_rebuild() {
    let temp = TempDir::new().unwrap();
    let store_dir = temp.path().join("store");
    let cwd = temp.path().join("workspace");
    fs::create_dir(&cwd).unwrap();
    let title = "Credential AKIAIOSFODNN7EXAMPLE title";
    let mut store = Store::open(&store_dir).unwrap();
    let item = store
        .add_friction(FrictionAddRequest {
            mode: FrictionAddMode::Create {
                source: "source AKIAIOSFODNN7EXAMPLE".into(),
                title: title.into(),
                target: Some("target AKIAIOSFODNN7EXAMPLE".into()),
                global: true,
            },
            evidence: "first occurrence".into(),
            cwd: cwd.clone(),
        })
        .unwrap();
    assert!(!item.slug.contains("AKIAIOSFODNN7EXAMPLE"));
    drop(store);

    let log = fs::read_to_string(store_dir.join(friction_log::LOG_FILE_NAME)).unwrap();
    assert!(!log.contains("AKIAIOSFODNN7EXAMPLE"));
    fs::remove_file(store_dir.join("learn.db")).unwrap();
    let mut store = Store::open(&store_dir).unwrap();
    let page = store
        .list_items(&FrictionListRequest {
            status: None,
            source: None,
            repo_root: None,
            global: true,
            text: None,
            cwd,
            page: PageRequest::default(),
        })
        .unwrap();
    assert_eq!(page.items.len(), 1);
    assert_eq!(page.items[0].slug, item.slug);
    assert!(!page.items[0].title.contains("AKIAIOSFODNN7EXAMPLE"));
    assert!(!page.items[0].source.contains("AKIAIOSFODNN7EXAMPLE"));
    assert!(
        !page.items[0]
            .target
            .as_deref()
            .unwrap()
            .contains("AKIAIOSFODNN7EXAMPLE")
    );
    let shown = store
        .show_friction(&item.id.to_string(), PageRequest::default())
        .unwrap();
    assert_eq!(shown.occurrences.items.len(), 1);
    assert_eq!(shown.occurrences.items[0].evidence, "first occurrence");
}

#[test]
fn eval_artifacts_redact_trace_and_report_replacement_count() {
    use crate::common::write_output_skill;

    let mock = crate::common::MockOutputClaude::new();
    let skill = TempDir::new().unwrap();
    write_output_skill(
        skill.path(),
        r#"{"skill_name":"fixture","evals":[{"id":"one","prompt":"test","expected_output":"AKIAIOSFODNN7EXAMPLE","assertions":["done"]}]}"#,
    );
    let response = mock.root().join("response.json");
    fs::write(
        &response,
        r#"{"type":"result","subtype":"success","is_error":false,"result":"credential AKIAIOSFODNN7EXAMPLE","duration_ms":1000,"usage":{"input_tokens":10,"output_tokens":10}}"#,
    )
    .unwrap();
    let workspace = TempDir::new().unwrap();
    let judge_args = mock.root().join("judge-args.txt");

    mock.command()
        .env("MOCK_OUTPUT_RESPONSE_FILE", &response)
        .env("MOCK_JUDGE_ARGS_FILE", &judge_args)
        .args([
            "eval",
            "output",
            "--harness",
            "claude",
            skill.path().to_str().unwrap(),
            "--workspace",
            workspace.path().to_str().unwrap(),
            "--no-baseline",
        ])
        .assert()
        .success();

    let benchmark: serde_json::Value = serde_json::from_slice(
        &fs::read(workspace.path().join("iteration-1/benchmark.json")).unwrap(),
    )
    .unwrap();
    assert_eq!(benchmark["redacted"], 2);
    assert_eq!(benchmark["result"]["redacted"], 2);
    let judge_input = fs::read_to_string(judge_args).unwrap();
    assert!(!judge_input.contains("AKIAIOSFODNN7EXAMPLE"));
    assert!(judge_input.contains("[redacted:aws-key]"));

    let run = workspace
        .path()
        .join("iteration-1/eval-one/with_skill/run-1");
    for artifact in ["raw.json", "transcript.txt", "outputs/transcript.txt"] {
        let text = fs::read_to_string(run.join(artifact)).unwrap();
        assert!(!text.contains("AKIAIOSFODNN7EXAMPLE"), "{artifact}");
        assert!(text.contains("[redacted:aws-key]"), "{artifact}");
    }
    let timing: serde_json::Value =
        serde_json::from_slice(&fs::read(run.join("timing.json")).unwrap()).unwrap();
    assert_eq!(timing["redacted"], 2);
}
