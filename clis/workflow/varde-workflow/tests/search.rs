//! Integration tests for `varde-workflow concept search`.

mod common;

use common::{bin, temp_bundle};
use std::process::Command;

fn concept(fields: &str) -> String {
    format!("---\ntype: decision\n{fields}---\n# Body\n")
}

fn search(args: &[&str]) -> std::process::Output {
    Command::new(bin())
        .args(["concept", "search"])
        .args(args)
        .output()
        .unwrap()
}

mod search {
    use super::*;

    fn fixture(bundle: &std::path::Path) {
        std::fs::write(
            bundle.join("decision-a.md"),
            concept("status: deprecated\nrecall_priority: high\n"),
        )
        .unwrap();
        std::fs::write(
            bundle.join("pattern-b.md"),
            "---\ntype: pattern\n---\n# b\n",
        )
        .unwrap();
        std::fs::write(
            bundle.join("decision-c.md"),
            concept("recall_priority: low\n"),
        )
        .unwrap();
    }

    #[test]
    fn field_filter_returns_only_matching_slugs() {
        let bundle = temp_bundle("search-type");
        fixture(&bundle);

        let out = search(&[
            "--field",
            "type=decision",
            "--bundle",
            bundle.to_str().unwrap(),
        ]);
        assert!(
            out.status.success(),
            "stderr: {}",
            String::from_utf8_lossy(&out.stderr)
        );
        let text = String::from_utf8_lossy(&out.stdout);
        assert!(text.contains("decision-a"), "stdout: {text}");
        assert!(text.contains("decision-c"), "stdout: {text}");
        assert!(!text.contains("pattern-b"), "stdout: {text}");
    }

    #[test]
    fn multiple_field_filters_are_and() {
        let bundle = temp_bundle("search-and");
        fixture(&bundle);

        let out = search(&[
            "--field",
            "status=deprecated",
            "--field",
            "recall_priority=high",
            "--bundle",
            bundle.to_str().unwrap(),
        ]);
        assert!(out.status.success());
        let text = String::from_utf8_lossy(&out.stdout);
        assert!(text.contains("decision-a"), "stdout: {text}");
        assert!(!text.contains("decision-c"), "stdout: {text}");
        assert!(!text.contains("pattern-b"), "stdout: {text}");
    }

    #[test]
    fn custom_extension_field_is_filterable() {
        let bundle = temp_bundle("search-custom");
        fixture(&bundle);

        let out = search(&[
            "--field",
            "recall_priority=low",
            "--bundle",
            bundle.to_str().unwrap(),
        ]);
        assert!(out.status.success());
        let text = String::from_utf8_lossy(&out.stdout);
        assert!(text.contains("decision-c"), "stdout: {text}");
        assert!(!text.contains("decision-a"), "stdout: {text}");
    }

    #[test]
    fn json_output_is_parseable_array_of_registry_entries() {
        let bundle = temp_bundle("search-json");
        fixture(&bundle);

        let out = search(&[
            "--field",
            "type=decision",
            "--json",
            "--bundle",
            bundle.to_str().unwrap(),
        ]);
        assert!(out.status.success());
        let parsed = common::json_data(&out.stdout);
        assert!(parsed.is_array(), "output must be a JSON array: {parsed}");
        assert_eq!(parsed.as_array().unwrap().len(), 2);
        for entry in parsed.as_array().unwrap() {
            assert_eq!(entry["type"], "decision");
            assert!(entry["frontmatter"].is_object());
            assert!(entry["slug"].is_string());
        }
    }

    #[test]
    fn no_match_prints_message_and_exits_zero() {
        let bundle = temp_bundle("search-nomatch");
        fixture(&bundle);

        let out = search(&[
            "--field",
            "status=stable",
            "--bundle",
            bundle.to_str().unwrap(),
        ]);
        assert!(out.status.success());
        let text = String::from_utf8_lossy(&out.stdout);
        assert!(text.contains("no concepts match"), "stdout: {text}");
    }

    #[test]
    fn malformed_field_flag_is_rejected_on_stderr() {
        let out = search(&["--field", "status"]);
        assert!(!out.status.success());
        assert!(
            String::from_utf8_lossy(&out.stderr).contains("expected `key=value`"),
            "stderr: {}",
            String::from_utf8_lossy(&out.stderr)
        );
    }

    #[test]
    fn aliases_are_searchable_as_frontmatter_terms() {
        let bundle = temp_bundle("search-aliases");
        std::fs::write(
            bundle.join("decision.md"),
            "---\ntype: decision\ndescription: A useful decision.\naliases:\n  - shortcut\n---\n# Body\n",
        )
        .unwrap();

        let out = search(&["--text", "shortcut", "--bundle", bundle.to_str().unwrap()]);
        assert!(out.status.success());
        assert!(String::from_utf8_lossy(&out.stdout).contains("decision"));
    }

    #[test]
    fn text_and_field_filters_compose() {
        let bundle = temp_bundle("search-text-fields");
        std::fs::write(
            bundle.join("stable.md"),
            "---\ntype: decision\nstatus: stable\n---\n# Rust\nStable choice.\n",
        )
        .unwrap();
        std::fs::write(
            bundle.join("draft.md"),
            "---\ntype: decision\nstatus: draft\n---\n# Rust\nDraft choice.\n",
        )
        .unwrap();

        let out = search(&[
            "--text",
            "rust",
            "--field",
            "status=stable",
            "--bundle",
            bundle.to_str().unwrap(),
        ]);
        assert!(out.status.success());
        let text = String::from_utf8_lossy(&out.stdout);
        assert!(text.contains("stable"), "stdout: {text}");
        assert!(!text.contains("draft"), "stdout: {text}");
    }
}
