use varde::sync::harness::HarnessId;
use varde::sync::preserve::{dry_run, preserve_models};

fn check_case(
    harness: HarnessId,
    agent: &str,
    staged: &str,
    installed: Option<&str>,
    expected_text: &str,
    expected_keys: &[&str],
) {
    let (actual_text, actual_keys) = preserve_models(harness, agent, staged, installed);
    assert_eq!(actual_text, expected_text);
    assert_eq!(
        actual_keys.iter().map(String::as_str).collect::<Vec<_>>(),
        expected_keys
    );
}

#[test]
fn fresh_and_unchanged_installs_take_the_shipped_model_idempotently() {
    let staged = "---\ndescription: Planner\nmodel: \"new-model\"\n---\nbody\n";
    let installed = "---\ndescription: Planner\nmodel: \"old-model\"\n---\nbody\n\n<!-- varde-managed-agent -->\n<!-- varde-default: model: \"old-model\" -->\n";
    let expected = "---\ndescription: Planner\nmodel: \"new-model\"\n---\nbody\n<!-- varde-default: model: \"new-model\" -->\n";

    check_case(
        HarnessId::Claude,
        "varde-planner",
        staged,
        None,
        expected,
        &[],
    );
    check_case(
        HarnessId::Claude,
        "varde-planner",
        staged,
        Some(installed),
        expected,
        &[],
    );
    check_case(
        HarnessId::Claude,
        "varde-planner",
        staged,
        Some(expected),
        expected,
        &[],
    );
}

#[test]
fn changed_markdown_model_survives_replacement_and_dry_run_lists_it() {
    let staged = "---\ndescription: Planner\nmodel: \"new-model\"\n---\nbody\n";
    let installed = "---\ndescription: Planner\nmodel: \"user-model\"\n---\nbody\n\n<!-- varde-managed-agent -->\n<!-- varde-default: model: \"old-model\" -->\n";
    let expected = "---\ndescription: Planner\nmodel: \"user-model\"\n---\nbody\n<!-- varde-default: model: \"new-model\" -->\n";

    check_case(
        HarnessId::OpenCode,
        "varde-planner",
        staged,
        Some(installed),
        expected,
        &["model"],
    );
    assert_eq!(
        dry_run(
            HarnessId::OpenCode,
            "varde-planner",
            staged,
            Some(installed)
        ),
        ["model"]
    );
}

#[test]
fn changed_codex_model_and_reasoning_effort_are_preserved_with_defaults() {
    let staged = "model = \"new-model\"\nmodel_reasoning_effort = \"medium\"\ndeveloper_instructions = \"instructions\"\n";
    let installed = "model = \"user-model\"\nmodel_reasoning_effort = \"high\"\ndeveloper_instructions = \"old instructions\"\n\n# varde-managed-agent\n# varde-default: model = \"old-model\"\n# varde-default: model_reasoning_effort = \"low\"\n";
    let expected = "model = \"user-model\"\nmodel_reasoning_effort = \"high\"\ndeveloper_instructions = \"instructions\"\n# varde-default: model = \"new-model\"\n# varde-default: model_reasoning_effort = \"medium\"\n";

    check_case(
        HarnessId::Codex,
        "varde-planner",
        staged,
        Some(installed),
        expected,
        &["model", "model_reasoning_effort"],
    );
}

#[test]
fn recorded_and_historical_values_are_treated_as_shipped_defaults() {
    let staged = "---\ndescription: Reviewer\nmodel: \"current-model\"\n---\n";
    let recorded_default = "---\ndescription: Reviewer\nmodel: \"old-model\"\n---\n<!-- varde-default: model: \"old-model\" -->\n";
    check_case(
        HarnessId::Claude,
        "varde-reviewer",
        staged,
        Some(recorded_default),
        "---\ndescription: Reviewer\nmodel: \"current-model\"\n---\n<!-- varde-default: model: \"current-model\" -->\n",
        &[],
    );

    let history_cases = [
        (HarnessId::Claude, "varde-reviewer", "haiku"),
        (HarnessId::Claude, "varde-explorer", "sonnet"),
        (HarnessId::Codex, "varde-explorer", "gpt-5.6-luna"),
        (HarnessId::Codex, "varde-builder", "gpt-5.6-luna"),
        (HarnessId::Codex, "varde-planner", "gpt-5.6-terra"),
        (HarnessId::Codex, "varde-reviewer", "gpt-5.6-sol"),
    ];
    for (harness, agent, historic_model) in history_cases {
        let (staged, installed, expected) = match harness {
            HarnessId::Codex => (
                "model = \"current-model\"\n".to_string(),
                format!("model = \"{historic_model}\"\n"),
                "model = \"current-model\"\n# varde-default: model = \"current-model\"\n"
                    .to_string(),
            ),
            _ => (
                "---\ndescription: Agent\nmodel: \"current-model\"\n---\n".to_string(),
                format!("---\ndescription: Agent\nmodel: \"{historic_model}\"\n---\n"),
                "---\ndescription: Agent\nmodel: \"current-model\"\n---\n<!-- varde-default: model: \"current-model\" -->\n"
                    .to_string(),
            ),
        };
        check_case(harness, agent, &staged, Some(&installed), &expected, &[]);
    }

    let custom_legacy = "---\ndescription: Reviewer\nmodel: \"sonnet\"\n---\n";
    check_case(
        HarnessId::Claude,
        "varde-reviewer",
        staged,
        Some(custom_legacy),
        "---\ndescription: Reviewer\nmodel: \"sonnet\"\n---\n<!-- varde-default: model: \"current-model\" -->\n",
        &["model"],
    );

    check_case(
        HarnessId::Claude,
        "varde-explorer",
        "---\ndescription: Explorer\nmodel: \"haiku\"\n---\n",
        Some("---\ndescription: Explorer\nmodel: \"opus\"\n---\n"),
        "---\ndescription: Explorer\nmodel: \"opus\"\n---\n<!-- varde-default: model: \"haiku\" -->\n",
        &["model"],
    );

    check_case(
        HarnessId::OpenCode,
        "varde-planner",
        "---\ndescription: Planner\nmodel: \"current-model\"\n---\n",
        Some("---\ndescription: Planner\nmodel: \"deepseek/deepseek-v4-flash\"\n---\n"),
        "---\ndescription: Planner\nmodel: \"deepseek/deepseek-v4-flash\"\n---\n<!-- varde-default: model: \"current-model\" -->\n",
        &["model"],
    );

    check_case(
        HarnessId::Codex,
        "varde-planner",
        "model = \"current-model\"\nmodel_reasoning_effort = \"medium\"\n",
        Some("model = \"gpt-5.6-terra\"\nmodel_reasoning_effort = \"high\"\n"),
        "model = \"current-model\"\nmodel_reasoning_effort = \"high\"\n# varde-default: model = \"current-model\"\n# varde-default: model_reasoning_effort = \"medium\"\n",
        &["model_reasoning_effort"],
    );
}

#[test]
fn removed_models_stay_removed_only_when_a_record_proves_they_were_shipped() {
    let staged = "---\ndescription: Planner\nmodel: \"new-model\"\n---\n";
    let removed_with_record =
        "---\ndescription: Planner\n---\n<!-- varde-default: model: \"old-model\" -->\n";
    check_case(
        HarnessId::Claude,
        "varde-planner",
        staged,
        Some(removed_with_record),
        "---\ndescription: Planner\n---\n<!-- varde-default: model: \"new-model\" -->\n",
        &["model"],
    );

    let removed_without_record = "---\ndescription: Planner\n---\n";
    check_case(
        HarnessId::OpenCode,
        "varde-planner",
        staged,
        Some(removed_without_record),
        "---\ndescription: Planner\nmodel: \"new-model\"\n---\n<!-- varde-default: model: \"new-model\" -->\n",
        &[],
    );

    let staged_toml = "model = \"new-model\"\nmodel_reasoning_effort = \"medium\"\n";
    let removed_toml = "# varde-default: model = \"old-model\"\n# varde-default: model_reasoning_effort = \"low\"\n";
    check_case(
        HarnessId::Codex,
        "varde-planner",
        staged_toml,
        Some(removed_toml),
        "# varde-default: model = \"new-model\"\n# varde-default: model_reasoning_effort = \"medium\"\n",
        &["model", "model_reasoning_effort"],
    );
}

#[test]
fn pi_keeps_custom_models_without_recording_a_new_default() {
    let staged = "---\ndescription: Planner\ntools: read\n---\nbody\n";
    let installed = "---\ndescription: Planner\nmodel: \"anthropic/claude-sonnet-4-5\"\ntools: read\n---\nbody\n";
    let expected = "---\ndescription: Planner\nmodel: \"anthropic/claude-sonnet-4-5\"\ntools: read\n---\nbody\n";
    check_case(
        HarnessId::Pi,
        "varde-planner",
        staged,
        Some(installed),
        expected,
        &["model"],
    );
    let installed_with_default = "---\ndescription: Planner\nmodel: \"anthropic/claude-sonnet-4-5\"\ntools: read\n---\n<!-- varde-default: model: \"deepseek/deepseek-v4-flash\" -->\n";
    check_case(
        HarnessId::Pi,
        "varde-planner",
        staged,
        Some(installed_with_default),
        expected,
        &["model"],
    );
    check_case(
        HarnessId::Pi,
        "varde-planner",
        staged,
        Some(expected),
        expected,
        &["model"],
    );

    let no_description = "---\ntools: read\n---\nbody\n";
    check_case(
        HarnessId::Pi,
        "varde-planner",
        no_description,
        Some("---\ntools: read\nmodel: \"mine\"\n---\nbody\n"),
        "---\ntools: read\nmodel: \"mine\"\n---\nbody\n",
        &["model"],
    );
}

#[test]
fn pi_drops_prior_pins_with_or_without_recorded_defaults() {
    let staged = "---\ndescription: Planner\ntools: read\n---\n";
    for agent in [
        "varde-builder",
        "varde-explorer",
        "varde-planner",
        "varde-reviewer",
    ] {
        let old_pin =
            "---\ndescription: Agent\nmodel: \"deepseek/deepseek-v4-flash\"\ntools: read\n---\n";
        let old_pin_with_record = "---\ndescription: Agent\nmodel: \"deepseek/deepseek-v4-flash\"\ntools: read\n---\n<!-- varde-default: model: \"deepseek/deepseek-v4-flash\" -->\n";
        check_case(HarnessId::Pi, agent, staged, Some(old_pin), staged, &[]);
        check_case(
            HarnessId::Pi,
            agent,
            staged,
            Some(old_pin_with_record),
            staged,
            &[],
        );
    }
}

#[test]
fn model_keys_outside_the_header_are_ignored() {
    let staged = "---\ndescription: Planner\nmodel: \"new-model\"\n---\nmodel: body-model\n";
    let installed =
        "---\ndescription: Planner\nmodel: \"new-model\"\n---\nmodel: user-body-model\n";
    check_case(
        HarnessId::Claude,
        "varde-planner",
        staged,
        Some(installed),
        "---\ndescription: Planner\nmodel: \"new-model\"\n---\nmodel: body-model\n<!-- varde-default: model: \"new-model\" -->\n",
        &[],
    );

    check_case(
        HarnessId::Codex,
        "varde-planner",
        "model = \"new-model\"\n[agents]\nmodel = \"body-model\"\n",
        Some("model = \"old-model\"\n[agents]\nmodel = \"user-body-model\"\n"),
        "model = \"old-model\"\n[agents]\nmodel = \"body-model\"\n# varde-default: model = \"new-model\"\n",
        &["model"],
    );
}
