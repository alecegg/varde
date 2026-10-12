mod discovery;
mod events;

pub(crate) use discovery::{inspect_id, inspect_path, list_sessions, verified_header_identity};
pub(crate) use events::{context_occupancy, native_id, normalize_record};

#[cfg(test)]
mod tests {
    use super::super::{MAX_RECORDS, MAX_SOURCE_BYTES, NormalizedRecordBudget, SessionMetadata};
    use super::discovery::{Header, child_header_matches, discover_descendants, read_header};
    use super::events::parse_source;
    use std::fs;
    use std::path::PathBuf;

    fn header(thread_id: &str, parent_thread_id: Option<&str>) -> Header {
        Header {
            session: SessionMetadata {
                harness: "codex".into(),
                thread_id: thread_id.into(),
                session_id: None,
                parent_thread_id: parent_thread_id.map(str::to_owned),
                parent_provenance: None,
                started_at: None,
                cwd: None,
                cli_version: Some("0.155.1".into()),
                history_mode: None,
                git: None,
                source_id: String::new(),
                transcript_id: None,
                project_namespace: None,
                agent_id: None,
                parent_agent_id: None,
                parent_tool_use_id: None,
                current_directory: None,
                fork_session_id: None,
                fork_boundary: None,
            },
            forked_from_id: None,
            history_base: None,
            parent_link_known: parent_thread_id.is_some(),
        }
    }

    #[test]
    fn selected_root_duplicates_in_a_cycle_do_not_override_explicit_selection() {
        let sessions = vec![
            (PathBuf::from("selected"), header("root", Some("leaf"))),
            (PathBuf::from("copy"), header("root", None)),
            (PathBuf::from("leaf"), header("leaf", Some("root"))),
        ];
        let (children, ambiguous) = discover_descendants("root", &sessions);
        assert!(!ambiguous);
        assert_eq!(children.len(), 1);
        assert_eq!(children[0].1.session.thread_id, "leaf");
    }

    #[test]
    fn ambiguous_descendants_are_omitted_regardless_of_order_or_parent() {
        for other_parent in ["root", "unrelated"] {
            let mut sessions = vec![
                (PathBuf::from("first"), header("duplicate", Some("root"))),
                (
                    PathBuf::from("second"),
                    header("duplicate", Some(other_parent)),
                ),
                (
                    PathBuf::from("grandchild"),
                    header("grandchild", Some("duplicate")),
                ),
                (PathBuf::from("unique"), header("unique", Some("root"))),
            ];
            for _ in 0..2 {
                let (children, ambiguous) = discover_descendants("root", &sessions);
                assert!(ambiguous);
                assert_eq!(children.len(), 1);
                assert_eq!(children[0].1.session.thread_id, "unique");
                sessions.reverse();
            }
        }
    }

    #[test]
    fn nested_ambiguity_keeps_only_verified_ancestors() {
        let sessions = vec![
            (PathBuf::from("child"), header("child", Some("root"))),
            (PathBuf::from("first"), header("duplicate", Some("child"))),
            (PathBuf::from("second"), header("duplicate", Some("child"))),
        ];
        let (children, ambiguous) = discover_descendants("root", &sessions);
        assert!(ambiguous);
        assert_eq!(children.len(), 1);
        assert_eq!(children[0].1.session.thread_id, "child");
    }

    #[test]
    fn unrelated_duplicates_do_not_taint_a_unique_family() {
        let sessions = vec![
            (PathBuf::from("child"), header("child", Some("root"))),
            (
                PathBuf::from("grandchild"),
                header("grandchild", Some("child")),
            ),
            (
                PathBuf::from("first"),
                header("duplicate", Some("unrelated")),
            ),
            (
                PathBuf::from("second"),
                header("duplicate", Some("unrelated")),
            ),
        ];
        let (children, ambiguous) = discover_descendants("root", &sessions);
        assert!(!ambiguous);
        assert_eq!(children.len(), 2);
        assert_eq!(children[0].1.session.thread_id, "child");
        assert_eq!(children[1].1.session.thread_id, "grandchild");
    }

    #[test]
    fn linked_child_header_must_keep_its_discovered_identity_and_parent() {
        let discovered = header("child", Some("parent"));
        assert!(child_header_matches(
            &header("child", Some("parent")),
            &discovered,
            "parent"
        ));
        assert!(!child_header_matches(
            &header("replacement", Some("parent")),
            &discovered,
            "parent"
        ));
        assert!(!child_header_matches(
            &header("child", Some("other-parent")),
            &discovered,
            "parent"
        ));
    }

    #[test]
    fn parsing_charges_large_inherited_identity_before_retaining_each_record() {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("rollout.jsonl");
        let thread_id = "t".repeat(65_536);
        let mut lines = vec![serde_json::json!({
            "type":"session_meta",
            "payload":{"id":thread_id,"cli_version":"0.155.1"}
        })];
        lines.push(serde_json::json!({
            "type":"turn_context",
            "payload":{"cwd":"c".repeat(32_768)}
        }));
        for index in 0..40 {
            lines.push(serde_json::json!({
                "type":"response_item",
                "timestamp":"2026-09-27T10:00:00Z",
                "payload":{"type":"message","role":"assistant","content":[{"type":"output_text","text":format!("event-{index}")}]}
            }));
        }
        fs::write(
            &path,
            lines
                .iter()
                .map(serde_json::Value::to_string)
                .collect::<Vec<_>>()
                .join("\n")
                + "\n",
        )
        .unwrap();

        let mut budget = NormalizedRecordBudget::new();
        let parsed = parse_source(&path, MAX_SOURCE_BYTES, MAX_RECORDS, &mut budget).unwrap();
        let serialized_bytes = parsed
            .records
            .iter()
            .map(|record| serde_json::to_vec(record).unwrap().len())
            .sum::<usize>();
        assert!(serialized_bytes <= super::super::NORMALIZED_RECORD_BUDGET_BYTES);
        assert_eq!(serialized_bytes, budget.used_bytes());
        assert!(parsed.records.len() < 41);
        assert!(parsed.truncated);
        assert!(parsed.omitted_records > 0);
        assert!(parsed.records.iter().all(|record| {
            record.cwd.as_ref().is_some_and(|cwd| cwd.len() == 32_768)
                && record.session_thread_id.len() == 65_536
        }));
        assert!(
            parsed
                .records
                .windows(2)
                .all(|records| { records[1].anchor.record_index > records[0].anchor.record_index })
        );
    }

    #[test]
    fn header_discovery_charges_buffered_prefetch_to_its_byte_budget() {
        let unique = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let directory = std::env::temp_dir().join(format!(
            "varde-codex-header-budget-{}-{unique}",
            std::process::id()
        ));
        fs::create_dir(&directory).unwrap();
        let path = directory.join("rollout.jsonl");
        let header = serde_json::json!({
            "type": "session_meta",
            "payload": { "id": "thread", "cli_version": "0.155.1" }
        });
        let mut contents = serde_json::to_vec(&header).unwrap();
        contents.push(b'\n');
        let tail_end = contents.len() + 4 * 1024;
        contents.resize(tail_end, b'x');
        fs::write(&path, contents).unwrap();

        let (result, bytes_read) = read_header(&path, 128, true);
        assert!(result.is_ok());
        assert_eq!(bytes_read, 128);

        fs::remove_dir_all(directory).unwrap();
    }
}
