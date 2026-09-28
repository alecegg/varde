//! Module-specific environment names preserve legacy compatibility.
use std::process::Command;

#[test]
fn rules_directory_prefers_canonical_name_and_accepts_legacy() {
    let fixture =
        std::env::temp_dir().join(format!("varde-code-env-naming-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&fixture);
    std::fs::create_dir_all(&fixture).unwrap();
    let canonical = fixture.join("canonical");
    let legacy = fixture.join("legacy");
    for (directory, id) in [(&canonical, "canonical-rule"), (&legacy, "legacy-rule")] {
        std::fs::create_dir(directory).unwrap();
        std::fs::write(directory.join("rule.toml"), format!("[[rule]]\nid = \"{id}\"\nkind = \"pattern\"\nseverity = \"warning\"\nmessage = \"fixture\"\npattern = \"foo()\"\n")).unwrap();
    }
    let invoke = |use_canonical: bool| {
        let mut command = Command::new(env!("CARGO_BIN_EXE_varde-code"));
        command
            .args([
                "rules_list",
                "--json",
                &serde_json::json!({"repoRoot": &fixture}).to_string(),
            ])
            .env_remove("VARDE_CODE_USER_RULES_DIR")
            .env("VARDE_USER_RULES_DIR", &legacy)
            .env("VARDE_CODE_TOZ", "0");
        if use_canonical {
            command.env("VARDE_CODE_USER_RULES_DIR", &canonical);
        }
        let output = command.output().unwrap();
        assert!(
            output.status.success(),
            "{}",
            String::from_utf8_lossy(&output.stderr)
        );
        String::from_utf8(output.stdout).unwrap()
    };
    let canonical_output = invoke(true);
    assert!(
        canonical_output.contains("canonical-rule"),
        "{canonical_output}"
    );
    assert!(
        !canonical_output.contains("legacy-rule"),
        "{canonical_output}"
    );
    let legacy_output = invoke(false);
    assert!(legacy_output.contains("legacy-rule"), "{legacy_output}");
    assert!(!legacy_output.contains("canonical-rule"), "{legacy_output}");
    std::fs::remove_dir_all(fixture).unwrap();
}
