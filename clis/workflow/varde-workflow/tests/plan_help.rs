fn long_help(command_name: &str) -> String {
    let mut command = varde_workflow::cli_command();
    command
        .find_subcommand_mut(command_name)
        .unwrap_or_else(|| panic!("missing {command_name} command"))
        .render_long_help()
        .to_string()
}

#[test]
fn plan_help_explains_workflow_outputs_and_gates() {
    let status = long_help("status");
    assert!(status.contains("progress block"), "{status}");
    assert!(status.contains("non-cancelled"), "{status}");
    assert!(status.contains("blockers"), "{status}");
    assert!(status.contains("next actions"), "{status}");

    let readiness = long_help("readiness");
    assert!(readiness.contains("blockers"), "{readiness}");
    assert!(readiness.contains("next actions"), "{readiness}");

    let validate = long_help("validate");
    assert!(validate.contains("validation_failed"), "{validate}");
    for status in ["backlog", "active", "blocked", "completed", "cancelled"] {
        assert!(validate.contains(status), "{validate}");
    }
    for status in ["todo", "in_progress", "blocked", "done"] {
        assert!(validate.contains(status), "{validate}");
    }

    let owner = long_help("owner");
    assert!(owner.contains("Example:"), "{owner}");

    let conclude = long_help("conclude");
    assert!(conclude.contains("reviewed head equals the merged repository HEAD"), "{conclude}");
    assert!(conclude.contains("approved"), "{conclude}");

    let now = long_help("now");
    assert!(now.contains("current progress line"), "{now}");
    assert!(now.contains("msg` carries free text"), "{now}");
    assert!(now.contains("watch` reports plan state"), "{now}");

    let watch = long_help("watch");
    assert!(watch.contains("Reports plan state"), "{watch}");
    assert!(watch.contains("msg` carries free text"), "{watch}");
    assert!(watch.contains("watch` reports plan state"), "{watch}");
}
