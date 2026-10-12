//! The app crate's in-process contract implementations, exercised against
//! temporary stores and repos (no spawned Varde binaries).

use std::path::Path;
use std::sync::Once;
use varde_contracts::CaptureInput;

/// Point every store at a temp directory once for the whole test binary.
fn isolate() -> &'static Path {
    static INIT: Once = Once::new();
    static HOME: std::sync::OnceLock<std::path::PathBuf> = std::sync::OnceLock::new();
    INIT.call_once(|| {
        let home = std::env::temp_dir().join(format!("varde-inprocess-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&home);
        std::fs::create_dir_all(&home).unwrap();
        // SAFETY: process environment setup runs once for this test binary.
        unsafe {
            std::env::set_var("HOME", &home);
            std::env::set_var("TOZ_CONFIG_DIR", home.join("toz-config"));
            std::env::remove_var("VARDE_CODE_TOZ");
        }
        HOME.set(home).unwrap();
    });
    HOME.get().unwrap()
}

#[test]
fn io_wires_every_capability_and_installs_the_code_capture() {
    isolate();
    let io = varde::io();
    assert!(io.repo_map.is_some() && io.impact.is_some() && io.capture.is_some());
    assert!(varde_code::toz::available());
}

#[test]
fn text_capture_returns_the_toz_preview_with_a_handle() {
    isolate();
    let capture = varde::io().capture.unwrap();
    let preview = capture
        .capture(
            CaptureInput::Text("line one\nline two\n"),
            "inprocess text",
            "inprocess",
        )
        .expect("text is captured");
    assert!(preview.starts_with("varde: captured "), "{preview}");
    assert!(preview.contains("→ handle "), "{preview}");
    assert!(preview.contains("label: \"inprocess\""), "{preview}");
}

#[test]
fn items_capture_returns_the_json_response_with_handle_and_toc() {
    isolate();
    let capture = varde::io().capture.unwrap();
    let items: Vec<String> = (0..3)
        .map(|i| format!("{{\"file\":\"a.rs\",\"id\":{i}}}"))
        .collect();
    let response = capture
        .capture(
            CaptureInput::Items(&items),
            "inprocess items",
            "find_pattern",
        )
        .expect("items are captured");
    let value: serde_json::Value = serde_json::from_str(&response).expect("--json shape");
    assert!(value["handle"].is_string(), "{value}");
    assert!(value.get("preview").is_some(), "{value}");
}

#[test]
fn repo_map_without_an_index_fails_with_the_envelope_error_code() {
    let home = isolate();
    let repo = home.join("unindexed-repo");
    std::fs::create_dir_all(repo.join("src")).unwrap();
    std::fs::write(repo.join("src/lib.rs"), "pub fn a() {}\n").unwrap();
    let error = varde::io()
        .repo_map
        .unwrap()
        .repo_map_text(&repo)
        .expect_err("no index yet");
    assert_eq!(error.code.as_deref(), Some("index_missing"));
}

#[test]
fn impact_query_is_unknown_without_an_index() {
    let home = isolate();
    let repo = home.join("unindexed-impact");
    std::fs::create_dir_all(&repo).unwrap();
    let io = varde::io();
    assert_eq!(
        io.impact
            .unwrap()
            .dependents(&repo, Path::new("src/lib.rs")),
        None
    );
}
