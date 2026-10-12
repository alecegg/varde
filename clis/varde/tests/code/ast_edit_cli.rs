use std::ffi::OsString;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, Output};

use serde_json::Value;
use tempfile::TempDir;

struct Fixture {
    _root: TempDir,
    repo: PathBuf,
    home: PathBuf,
    xdg: PathBuf,
    config: PathBuf,
    working: PathBuf,
}

impl Fixture {
    fn new() -> Self {
        let root = tempfile::Builder::new()
            .prefix("varde-ast-edit-cli-")
            .tempdir()
            .expect("temporary fixture directory creates under TMPDIR");
        let repo = root.path().join("repo");
        let home = root.path().join("home");
        let xdg = root.path().join("xdg");
        let config = root.path().join("config");
        let working = root.path().join("working");
        for directory in [&repo, &home, &xdg, &config, &working] {
            fs::create_dir_all(directory).unwrap();
        }
        let git = Command::new("git")
            .args(["init", "--quiet"])
            .current_dir(&repo)
            .env("HOME", &home)
            .env("XDG_CONFIG_HOME", &xdg)
            .output()
            .expect("git is installed");
        assert!(
            git.status.success(),
            "git init failed: {}",
            String::from_utf8_lossy(&git.stderr)
        );
        Self {
            _root: root,
            repo,
            home,
            xdg,
            config,
            working,
        }
    }

    fn command(&self, binary: &Path, cwd: &Path, args: &[OsString]) -> Output {
        Command::new(binary)
            .args(args)
            .current_dir(cwd)
            .env("HOME", &self.home)
            .env("XDG_CONFIG_HOME", &self.xdg)
            .env("VARDE_CONFIG_DIR", &self.config)
            .env("VARDE_WORKING_DIR", &self.working)
            .env_remove("VARDE_KNOWLEDGE_DIR")
            .env_remove("VARDE_LEARN_STORE")
            .output()
            .expect("varde binary runs")
    }

    fn varde(&self, cwd: &Path, args: &[&str]) -> Output {
        self.command(Path::new(env!("CARGO_BIN_EXE_varde")), cwd, &os_args(args))
    }
}

fn os_args(args: &[&str]) -> Vec<OsString> {
    args.iter().map(OsString::from).collect()
}

fn json(output: &Output) -> Value {
    serde_json::from_slice(&output.stdout).unwrap_or_else(|error| {
        panic!(
            "expected JSON output ({error}):\nstdout: {}\nstderr: {}",
            String::from_utf8_lossy(&output.stdout),
            String::from_utf8_lossy(&output.stderr)
        )
    })
}

fn write_rules(repo: &Path) -> PathBuf {
    let path = repo.join("rules.json");
    fs::write(
        &path,
        r#"[{"id":"rename","language":"typescript","pattern":"oldCall($ARG)","replacement":"newCall($ARG)"}]"#,
    )
    .unwrap();
    path
}

fn preview_args(rules: &[&str], path: &str) -> Vec<OsString> {
    let mut args = os_args(&["edit", "preview"]);
    args.extend(rules.iter().map(OsString::from));
    args.extend(os_args(&["--path", path, "--json"]));
    args
}

fn inline_preview_args(path: &str) -> Vec<OsString> {
    preview_args(
        &[
            "--language",
            "typescript",
            "--pattern",
            "oldCall()",
            "--replacement",
            "newCall()",
        ],
        path,
    )
}

fn apply_preview(fixture: &Fixture, cwd: &Path, data: &Value) -> Output {
    let mut args = os_args(&["edit", "apply", "--proposal"]);
    args.push(
        data["proposal_path"]
            .as_str()
            .expect("preview returns a proposal path")
            .into(),
    );
    args.push(OsString::from("--json"));
    fixture.command(Path::new(env!("CARGO_BIN_EXE_varde")), cwd, &args)
}

fn smoke_binary() -> PathBuf {
    std::env::var_os("VARDE_SMOKE_BIN")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from(env!("CARGO_BIN_EXE_varde")))
}

fn smoke_round_trip(fixture: &Fixture, binary: &Path) {
    let source = "const value = oldCall(1);\n";
    fs::write(fixture.repo.join("main.ts"), source).unwrap();
    write_rules(&fixture.repo);

    let preview = fixture.command(
        binary,
        &fixture.repo,
        &preview_args(&["--rules", "rules.json"], "main.ts"),
    );
    assert!(
        preview.status.success(),
        "preview failed:\n{}\n{}",
        String::from_utf8_lossy(&preview.stdout),
        String::from_utf8_lossy(&preview.stderr)
    );
    let envelope = json(&preview);
    assert_eq!(envelope["ok"], true);
    let proposal_id = envelope["data"]["proposal_id"]
        .as_str()
        .expect("preview returns the proposal identity");
    let proposal_path = PathBuf::from(
        envelope["data"]["proposal_path"]
            .as_str()
            .expect("preview returns a proposal path"),
    );
    assert!(
        proposal_path.starts_with(fixture.working.canonicalize().unwrap().join("ast-edit")),
        "proposal path {} is outside the isolated working store {}",
        proposal_path.display(),
        fixture.working.join("ast-edit").display()
    );

    let apply = fixture.command(
        binary,
        &fixture.repo,
        &[
            OsString::from("edit"),
            OsString::from("apply"),
            OsString::from("--proposal"),
            proposal_path.into_os_string(),
            OsString::from("--json"),
        ],
    );
    assert!(
        apply.status.success(),
        "apply failed:\n{}\n{}",
        String::from_utf8_lossy(&apply.stdout),
        String::from_utf8_lossy(&apply.stderr)
    );
    let apply_data = json(&apply);
    assert_eq!(apply_data["ok"], true);
    assert_eq!(apply_data["data"]["proposal_id"], proposal_id);
    assert_eq!(
        fs::read_to_string(fixture.repo.join("main.ts")).unwrap(),
        "const value = newCall(1);\n"
    );
}

#[test]
fn cli_command_has_no_ast_edit_subcommand() {
    assert!(
        !varde_code::cli_command()
            .get_subcommands()
            .any(|command| command.get_name() == "ast-edit")
    );
}

#[test]
fn rules_file_input_previews_a_proposal() {
    let fixture = Fixture::new();
    fs::write(fixture.repo.join("main.ts"), "oldCall(1);\n").unwrap();
    write_rules(&fixture.repo);

    let output = fixture.varde(
        &fixture.repo,
        &[
            "edit",
            "preview",
            "--rules",
            "rules.json",
            "--path",
            "main.ts",
            "--json",
        ],
    );

    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let envelope = json(&output);
    assert_eq!(envelope["ok"], true);
    assert_eq!(envelope["data"]["applicable"], true);
    let data = &envelope["data"];
    assert!(data["proposal_id"].is_string());
    assert!(data["proposal_path"].is_string());
    assert!(data["diff_path"].is_string());
    assert_eq!(data["files"][0]["path"], "main.ts");
    assert_eq!(data["files"][0]["replacement_count"], 1);
    assert!(data.get("proposal").is_none());
    assert!(data.get("diff").is_none());
    assert!(
        !String::from_utf8_lossy(&output.stdout).contains("oldCall(1)"),
        "preview JSON embeds the source instead of returning its stored proposal reference"
    );
}

#[test]
fn one_rule_arguments_preview_a_relative_path_from_the_invoking_subdirectory() {
    let fixture = Fixture::new();
    let subdir = fixture.repo.join("subdir");
    fs::create_dir_all(&subdir).unwrap();
    let source = "oldCall(1);\n";
    fs::write(subdir.join("main.ts"), source).unwrap();

    let output = fixture.varde(
        &subdir,
        &[
            "edit",
            "preview",
            "--language",
            "typescript",
            "--pattern",
            "oldCall($ARG)",
            "--replacement",
            "newCall($ARG)",
            "--path",
            "main.ts",
            "--json",
        ],
    );

    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let data = json(&output)["data"].clone();
    let proposal_path = data["proposal_path"].as_str().unwrap();
    let proposal: Value = serde_json::from_slice(&fs::read(proposal_path).unwrap()).unwrap();
    assert_eq!(
        proposal["repository_root"],
        fixture.repo.canonicalize().unwrap().to_str().unwrap()
    );
    assert_eq!(proposal["files"][0]["path"], "subdir/main.ts");
    assert_eq!(fs::read_to_string(subdir.join("main.ts")).unwrap(), source);
}

#[test]
fn directory_and_repository_root_scopes_preview_then_apply() {
    let fixture = Fixture::new();
    let src = fixture.repo.join("src");
    fs::create_dir_all(&src).unwrap();
    fs::write(src.join("nested.ts"), "oldCall();\n").unwrap();

    let directory_preview = fixture.command(
        Path::new(env!("CARGO_BIN_EXE_varde")),
        &fixture.repo,
        &inline_preview_args("src"),
    );
    assert!(directory_preview.status.success());
    let directory_data = json(&directory_preview)["data"].clone();
    let directory_proposal: Value = serde_json::from_slice(
        &fs::read(directory_data["proposal_path"].as_str().unwrap()).unwrap(),
    )
    .unwrap();
    assert_eq!(directory_proposal["scope"], serde_json::json!(["src"]));
    assert_eq!(directory_proposal["files"][0]["path"], "src/nested.ts");

    let applied_directory = apply_preview(&fixture, &fixture.repo, &directory_data);
    assert!(applied_directory.status.success());
    assert_eq!(
        fs::read_to_string(src.join("nested.ts")).unwrap(),
        "newCall();\n"
    );

    let root_source = fixture.repo.join("main.ts");
    fs::write(&root_source, "oldCall();\n").unwrap();
    let root_preview = fixture.command(
        Path::new(env!("CARGO_BIN_EXE_varde")),
        &fixture.repo,
        &inline_preview_args("."),
    );
    assert!(root_preview.status.success());
    let root_data = json(&root_preview)["data"].clone();
    let root_proposal: Value =
        serde_json::from_slice(&fs::read(root_data["proposal_path"].as_str().unwrap()).unwrap())
            .unwrap();
    assert_eq!(root_proposal["scope"], serde_json::json!(["."]));
    assert_eq!(root_proposal["files"][0]["path"], "main.ts");

    let applied_root = apply_preview(&fixture, &fixture.repo, &root_data);
    assert!(applied_root.status.success());
    assert_eq!(fs::read_to_string(root_source).unwrap(), "newCall();\n");
}

#[test]
fn escaping_path_is_rejected_with_a_clear_error_and_writes_nothing() {
    let fixture = Fixture::new();
    let outside = fixture.repo.parent().unwrap().join("outside");
    fs::write(&outside, "oldCall(1);\n").unwrap();

    let output = fixture.varde(
        &fixture.repo,
        &[
            "edit",
            "preview",
            "--language",
            "typescript",
            "--pattern",
            "oldCall($ARG)",
            "--replacement",
            "newCall($ARG)",
            "--path",
            "../outside",
            "--json",
        ],
    );

    assert!(!output.status.success());
    let envelope = json(&output);
    assert_eq!(envelope["ok"], false);
    let diagnostics = &envelope["data"]["error"]["details"]["diagnostics"];
    assert!(
        diagnostics.as_array().unwrap().iter().any(|diagnostic| {
            diagnostic["code"] == "unsafe_path"
                && diagnostic["message"]
                    .as_str()
                    .is_some_and(|message| message.contains("escapes repository root"))
        }),
        "{envelope}"
    );
    assert_eq!(fs::read_to_string(outside).unwrap(), "oldCall(1);\n");
    assert!(!fixture.working.join("ast-edit").exists());
}

#[test]
fn out_directory_preserves_existing_mode_and_writes_private_artifacts() {
    #[cfg(unix)]
    use std::os::unix::fs::PermissionsExt;

    let fixture = Fixture::new();
    let output_dir = fixture._root.path().join("explicit-output");
    fs::create_dir(&output_dir).unwrap();
    #[cfg(unix)]
    fs::set_permissions(&output_dir, fs::Permissions::from_mode(0o755)).unwrap();
    fs::write(fixture.config.join("config.toml"), "[").unwrap();
    fs::write(fixture.repo.join("main.ts"), "oldCall(1);\n").unwrap();

    let mut args = os_args(&[
        "edit",
        "preview",
        "--language",
        "typescript",
        "--pattern",
        "oldCall($ARG)",
        "--replacement",
        "newCall($ARG)",
        "--path",
        "main.ts",
        "--out",
    ]);
    args.push(output_dir.clone().into_os_string());
    args.push(OsString::from("--json"));
    let output = fixture.command(Path::new(env!("CARGO_BIN_EXE_varde")), &fixture.repo, &args);

    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert_eq!(json(&output)["ok"], true);
    assert!(output_dir.is_dir());
    let artifacts = fs::read_dir(&output_dir)
        .unwrap()
        .map(|entry| entry.unwrap().path())
        .collect::<Vec<_>>();
    assert_eq!(artifacts.len(), 2);
    #[cfg(unix)]
    {
        assert_eq!(
            fs::metadata(&output_dir).unwrap().permissions().mode() & 0o777,
            0o755,
        );
        for artifact in artifacts {
            assert_eq!(
                fs::metadata(&artifact).unwrap().permissions().mode() & 0o777,
                0o600,
                "{}",
                artifact.display(),
            );
        }
    }
    assert!(!fixture.working.join("ast-edit").exists());
}

#[test]
fn combined_rule_sources_are_usage_errors_named_for_varde_edit() {
    let fixture = Fixture::new();
    write_rules(&fixture.repo);
    let output = fixture.varde(
        &fixture.repo,
        &[
            "edit",
            "preview",
            "--rules",
            "rules.json",
            "--language",
            "typescript",
            "--pattern",
            "oldCall($ARG)",
            "--replacement",
            "newCall($ARG)",
            "--path",
            "main.ts",
        ],
    );

    assert_eq!(output.status.code(), Some(2));
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(stderr.contains("Usage: varde edit preview"), "{stderr}");
    assert!(!stderr.contains("varde-code"), "{stderr}");
}

#[test]
fn preview_then_apply_edits_a_disposable_git_repository() {
    smoke_round_trip(&Fixture::new(), Path::new(env!("CARGO_BIN_EXE_varde")));
}

#[test]
fn installed_binary_smoke() {
    smoke_round_trip(&Fixture::new(), &smoke_binary());
}
