use assert_cmd::Command;
use predicates::str::contains;
use serde_json::Value;
use std::path::Path;

fn flow(args: &[&str]) -> Command {
    let mut command = Command::cargo_bin("varde").expect("varde binary");
    command.args(["doc", "flow"]).args(args);
    command
}

fn envelope(output: &[u8]) -> Value {
    serde_json::from_slice(output).expect("json envelope")
}

/// A skill with one route to one reference, plus an optional dangling pointer.
fn write_skill(root: &Path, dangling: bool) -> String {
    let dir = root.join("demo");
    std::fs::create_dir_all(dir.join("references")).unwrap();
    std::fs::write(
        dir.join("SKILL.md"),
        "---\nname: demo\ndescription: demo\n---\n\n| Request | Read |\n|---|---|\n| Build it | `references/build.md` |\n",
    )
    .unwrap();
    let build = if dangling {
        "# Build\n\nSee `references/ghost.md`.\n"
    } else {
        "# Build\n\nDo the work.\n"
    };
    std::fs::write(dir.join("references/build.md"), build).unwrap();
    dir.to_str().unwrap().to_string()
}

#[test]
fn text_report_succeeds_for_a_clean_skill() {
    let tmp = tempfile::tempdir().unwrap();
    let dir = write_skill(tmp.path(), false);
    flow(&[&dir])
        .assert()
        .success()
        .stdout(contains("== demo (SKILL.md ~"))
        .stdout(contains("  Build it  [~"));
}

#[test]
fn mermaid_prints_a_flowchart() {
    let tmp = tempfile::tempdir().unwrap();
    let dir = write_skill(tmp.path(), false);
    flow(&["--mermaid", &dir])
        .assert()
        .success()
        .stdout(contains("%% demo\nflowchart TD\n"));
}

#[test]
fn json_returns_the_analysis_list_in_a_success_envelope() {
    let tmp = tempfile::tempdir().unwrap();
    let dir = write_skill(tmp.path(), false);
    let output = flow(&["--json", &dir])
        .assert()
        .success()
        .get_output()
        .stdout
        .clone();
    let value = envelope(&output);
    assert_eq!(value["ok"], true);
    let skills = value["data"].as_array().unwrap();
    assert_eq!(skills.len(), 1);
    assert_eq!(skills[0]["skill"], "demo");
    assert_eq!(skills[0]["routes"][0]["route"], "Build it");
}

#[test]
fn dispatch_files_list_agent_inputs_with_tokens_and_source() {
    let tmp = tempfile::tempdir().unwrap();
    let skills = tmp.path().join("skills");
    let dir = write_skill(&skills, false);
    let skill_dir = Path::new(&dir);
    std::fs::write(
        skill_dir.join("SKILL.md"),
        "---\nname: demo\ndescription: demo\n---\n\n| Request | Read |\n|---|---|\n| Build it | `references/build.md`, `references/review-gates.md` |\n| Review it | `references/build.md`, `references/review-gates.md` |\n",
    )
    .unwrap();
    std::fs::write(
        skill_dir.join("references/build.md"),
        "Dispatch the reviewer agent.\n",
    )
    .unwrap();
    let review_gates = "Review the gate.\n";
    let required = "Required review.\n";
    let conditional = "Conditional review.\n";
    std::fs::write(skill_dir.join("references/review-gates.md"), review_gates).unwrap();
    std::fs::write(skill_dir.join("references/required.md"), required).unwrap();
    std::fs::write(skill_dir.join("references/conditional.md"), conditional).unwrap();
    let agent = tmp.path().join("agents/varde-reviewer/claude.md");
    std::fs::create_dir_all(agent.parent().unwrap()).unwrap();
    let agent_text = "---\nname: varde-reviewer\ndescription: demo\nskills: varde-review\n---\n";
    std::fs::write(&agent, agent_text).unwrap();
    let preloaded_skill = tmp.path().join("skills/varde-review/SKILL.md");
    std::fs::create_dir_all(preloaded_skill.parent().unwrap()).unwrap();
    let preloaded_skill_text = "---\nname: varde-review\ndescription: demo\n---\n";
    std::fs::write(&preloaded_skill, preloaded_skill_text).unwrap();

    let output = flow(&["--json", &dir])
        .assert()
        .success()
        .get_output()
        .stdout
        .clone();
    let value = envelope(&output);
    let routes = value["data"][0]["routes"].as_array().unwrap();
    assert_eq!(routes.len(), 2);
    let expected_paths = [
        "agents/varde-reviewer/claude.md",
        "skills/demo/references/review-gates.md",
        "skills/varde-review/SKILL.md",
    ];
    let tokens = |text: &str| text.chars().count().div_ceil(4);
    let expected_files = [
        (
            "agents/varde-reviewer/claude.md",
            agent_text,
            "skills/demo/references/build.md",
        ),
        (
            "skills/demo/references/review-gates.md",
            review_gates,
            "skills/demo/SKILL.md",
        ),
        (
            "skills/varde-review/SKILL.md",
            preloaded_skill_text,
            "agents/varde-reviewer/claude.md",
        ),
    ];
    for route in routes {
        let dispatch = &route["dispatches"][0];
        assert_eq!(dispatch["agent"], "review");
        assert_eq!(dispatch["runs"], "review gate");
        let files = dispatch["files"].as_array().unwrap();
        let paths: Vec<_> = files
            .iter()
            .map(|file| file["file"].as_str().unwrap())
            .collect();
        assert_eq!(paths, expected_paths);
        for (path, text, via) in expected_files {
            let file = files.iter().find(|file| file["file"] == path).unwrap();
            assert_eq!(file["tokens"], tokens(text));
            assert_eq!(file["via"], via);
        }
        let typical = tokens(agent_text) + tokens(preloaded_skill_text) + tokens(review_gates);
        assert_eq!(dispatch["min_tokens"], typical);
        assert_eq!(dispatch["max_tokens"], typical);
    }
}

#[test]
fn missing_targets_exit_1_in_every_output_mode() {
    let tmp = tempfile::tempdir().unwrap();
    let dir = write_skill(tmp.path(), true);
    flow(&[&dir]).assert().code(1).stdout(contains(
        "missing: references/build.md:3 -> references/ghost.md",
    ));
    flow(&["--mermaid", &dir]).assert().code(1);
    let output = flow(&["--json", &dir])
        .assert()
        .code(1)
        .get_output()
        .stdout
        .clone();
    let value = envelope(&output);
    assert_eq!(value["ok"], false);
    assert_eq!(value["data"]["error"]["code"], "doc_flow_missing");
    let skills = value["data"]["error"]["details"].as_array().unwrap();
    assert_eq!(
        skills[0]["findings"]["missing"][0]["target"],
        "references/ghost.md"
    );
}

#[test]
fn a_directory_without_skill_md_exits_2() {
    let tmp = tempfile::tempdir().unwrap();
    let dir = tmp.path().to_str().unwrap();
    flow(&[dir])
        .assert()
        .code(2)
        .stderr(contains("not a skill directory"));
    let stderr = flow(&["--json", dir])
        .assert()
        .code(2)
        .get_output()
        .stderr
        .clone();
    let value = envelope(&stderr);
    assert_eq!(value["data"]["error"]["code"], "doc_flow_input");
}

#[test]
fn json_usage_errors_print_a_tool_error_envelope() {
    let stderr = flow(&["--json", "--mermaid", "x"])
        .assert()
        .code(2)
        .get_output()
        .stderr
        .clone();
    let value = envelope(&stderr);
    assert_eq!(value["data"]["error"]["code"], "doc_flow_usage");
}

#[test]
fn check_reports_missing_and_stale_flow_files_then_write_fixes_them() {
    let tmp = tempfile::tempdir().unwrap();
    let dir = write_skill(tmp.path(), false);
    let flow_md = format!("{dir}/FLOW.md");
    flow(&["--check", &dir]).assert().code(1).stdout(format!(
        "stale: {flow_md} (run varde doc flow --write {dir})\n"
    ));
    flow(&["--write", &dir]).assert().success().stdout("");
    let written = std::fs::read_to_string(&flow_md).unwrap();
    assert!(written.starts_with("# demo flow\n"));
    assert!(written.contains("with `varde doc flow --write`."));
    flow(&["--check", &dir]).assert().success().stdout("");
    std::fs::write(&flow_md, "old\n").unwrap();
    flow(&["--check", &dir]).assert().code(1);
}
