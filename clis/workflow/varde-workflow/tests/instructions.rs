//! `instructions`: managed global instruction files and persisted targets.

mod common;

use std::fs;
use std::os::unix::fs::{PermissionsExt, symlink};
use std::path::{Path, PathBuf};
use std::process::Output;

struct Fixture {
    root: PathBuf,
    bin_dir: PathBuf,
    config_dir: PathBuf,
}

impl Fixture {
    fn new(tag: &str) -> Self {
        let root = common::temp_bundle(tag);
        let bin_dir = root.join("bin");
        let config_dir = root.join("isolated-config");
        fs::create_dir_all(&bin_dir).unwrap();
        Self {
            root,
            bin_dir,
            config_dir,
        }
    }

    fn run(&self, args: &[String]) -> Output {
        let mut command = common::isolate_memory(&self.root);
        command
            .args(args)
            .env("PATH", &self.bin_dir)
            .output()
            .unwrap()
    }

    fn stub_toz(&self) {
        let path = self.bin_dir.join("varde-toz");
        fs::write(
            &path,
            "#!/bin/sh\n[ \"$1\" = note ] && [ \"$2\" = --block ] || exit 2\nprintf '%s\\n' 'TOZ_NOTE_BLOCK'\n",
        )
        .unwrap();
        fs::set_permissions(&path, fs::Permissions::from_mode(0o755)).unwrap();
    }

    fn config_file(&self) -> PathBuf {
        self.config_dir.join("config.toml")
    }
}

fn cli_args(parts: &[&str]) -> Vec<String> {
    parts.iter().map(|part| (*part).to_owned()).collect()
}

fn install_args(target: &Path) -> Vec<String> {
    vec![
        "instructions".into(),
        "install".into(),
        "--target".into(),
        target.to_string_lossy().into_owned(),
    ]
}

fn text(output: &Output) -> String {
    String::from_utf8_lossy(&output.stdout).into_owned()
}

fn write_block_count(content: &str) -> usize {
    content.matches("<!-- varde:start -->").count()
}

#[test]
fn install_appends_after_user_text_with_a_blank_line_and_override_sentence() {
    let fixture = Fixture::new("instructions-append");
    let target = fixture.root.join("AGENTS.md");
    fs::write(&target, "# User instructions\nKeep this text.\n").unwrap();
    fixture.stub_toz();

    let output = fixture.run(&install_args(&target));
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let content = fs::read_to_string(&target).unwrap();
    assert!(content.starts_with("# User instructions\nKeep this text.\n\n\n"));
    assert!(content.ends_with("<!-- varde:end -->\n"));
    assert_eq!(write_block_count(&content), 1, "{content}");
    assert!(content.contains("This standing user request to delegate overrides any built-in default to spawn subagents only on request."));
    assert!(
        content.contains("If you were launched with a bounded task, follow that brief instead.")
    );
    assert!(content.contains("Keep responding to the user while commands and agents run; say when you become busy and when you are free again."));
    assert!(content.contains("TOZ_NOTE_BLOCK"));
}

#[test]
fn install_creates_new_target_with_a_final_newline() {
    let fixture = Fixture::new("instructions-new-target");
    let target = fixture.root.join("AGENTS.md");

    let output = fixture.run(&install_args(&target));
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let content = fs::read(&target).unwrap();
    assert!(content.ends_with(b"<!-- varde:end -->\n"));
}

#[test]
fn install_replaces_the_block_in_place_and_preserves_surrounding_bytes() {
    let fixture = Fixture::new("instructions-replace");
    let target = fixture.root.join("AGENTS.md");
    let prefix = b"before\n\n";
    let old_block = b"<!-- varde:start -->\nold body\n<!-- varde:end -->";
    let suffix = b"\n\nafter\n";
    let mut original = prefix.to_vec();
    original.extend_from_slice(old_block);
    original.extend_from_slice(suffix);
    fs::write(&target, &original).unwrap();

    let output = fixture.run(&install_args(&target));
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let updated = fs::read(&target).unwrap();
    assert!(updated.starts_with(prefix));
    assert!(updated.ends_with(suffix));
    let content = String::from_utf8_lossy(&updated);
    assert_eq!(write_block_count(&content), 1, "{content}");
    assert!(!content.contains("old body"));
}

#[test]
fn symlink_targets_are_deduplicated_and_writes_keep_the_link() {
    let fixture = Fixture::new("instructions-symlink");
    let real = fixture.root.join("canonical.md");
    let link = fixture.root.join("AGENTS.md");
    fs::write(&real, "# Shared instructions\n").unwrap();
    symlink(&real, &link).unwrap();
    let args = vec![
        "instructions".into(),
        "install".into(),
        "--target".into(),
        link.to_string_lossy().into_owned(),
        "--target".into(),
        real.to_string_lossy().into_owned(),
    ];

    let output = fixture.run(&args);
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert!(
        fs::symlink_metadata(&link)
            .unwrap()
            .file_type()
            .is_symlink()
    );
    let content = fs::read_to_string(&real).unwrap();
    assert_eq!(write_block_count(&content), 1, "{content}");
    let configured = fs::read_to_string(fixture.config_file()).unwrap();
    assert!(configured.contains(&link.to_string_lossy().to_string()));
    assert!(!configured.contains(&real.to_string_lossy().to_string()));
}

#[test]
fn remove_restores_user_file_bytes_after_an_append() {
    let cases: [(&str, &[u8], bool); 4] = [
        ("instructions-remove-empty", b"", false),
        (
            "instructions-remove-with-newline",
            b"# User instructions\n",
            false,
        ),
        (
            "instructions-remove-without-newline",
            b"# User instructions",
            false,
        ),
        (
            "instructions-remove-editor-newline",
            b"# User instructions\n",
            true,
        ),
    ];
    for (tag, original, add_newline_after_block) in cases {
        let fixture = Fixture::new(tag);
        let target = fixture.root.join("AGENTS.md");
        let mut initial = original.to_vec();
        if add_newline_after_block {
            initial.extend_from_slice(
                b"\n\n<!-- varde:start -->\nold managed text\n<!-- varde:end -->",
            );
        }
        fs::write(&target, initial).unwrap();

        let installed = fixture.run(&install_args(&target));
        assert!(
            installed.status.success(),
            "{}",
            String::from_utf8_lossy(&installed.stderr)
        );
        if add_newline_after_block {
            let mut edited = fs::read(&target).unwrap();
            edited.push(b'\n');
            fs::write(&target, edited).unwrap();
        }

        let removed = fixture.run(&cli_args(&["instructions", "remove"]));
        assert!(
            removed.status.success(),
            "{}",
            String::from_utf8_lossy(&removed.stderr)
        );
        assert_eq!(fs::read(&target).unwrap(), original, "{tag}");
    }
}

#[test]
fn remove_clears_targets_and_keeps_other_config_values() {
    let fixture = Fixture::new("instructions-remove-targets");
    let target = fixture.root.join("AGENTS.md");
    fs::write(
        &target,
        "User text\n\n\n<!-- varde:start -->\nmanaged\n<!-- varde:end -->\n",
    )
    .unwrap();
    fs::create_dir_all(&fixture.config_dir).unwrap();
    fs::write(
        fixture.config_file(),
        format!(
            "[orchestration]\nmax_agents = 2\n\n[instructions]\ntargets = [\"{}\"]\n\n[custom]\nkeep = \"yes\"\n",
            target.display()
        ),
    )
    .unwrap();

    let removed = fixture.run(&cli_args(&["instructions", "remove"]));
    assert!(
        removed.status.success(),
        "{}",
        String::from_utf8_lossy(&removed.stderr)
    );
    assert_eq!(fs::read(&target).unwrap(), b"User text\n");
    let config = fs::read_to_string(fixture.config_file()).unwrap();
    assert!(!config.contains("targets ="), "{config}");
    assert!(config.contains("max_agents = 2"), "{config}");
    assert!(config.contains("keep = \"yes\""), "{config}");
}

#[test]
fn install_without_targets_prints_the_setup_warning_and_targets_is_empty() {
    let fixture = Fixture::new("instructions-no-targets");
    let output = fixture.run(&cli_args(&["instructions", "install"]));
    assert!(output.status.success());
    assert!(text(&output).contains("Varde will not work as designed"));
    assert!(text(&output).contains("varde-workflow instructions install --target <file>"));

    let targets = fixture.run(&cli_args(&["instructions", "targets"]));
    assert!(targets.status.success());
    assert!(targets.stdout.is_empty());
}

#[test]
fn read_only_target_warns_and_prints_the_block_without_failing() {
    let fixture = Fixture::new("instructions-read-only");
    let target = fixture.root.join("readonly.md");
    fs::write(&target, "# Read only\n").unwrap();
    fs::set_permissions(&target, fs::Permissions::from_mode(0o444)).unwrap();

    let output = fixture.run(&install_args(&target));
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert!(String::from_utf8_lossy(&output.stdout).contains("<!-- varde:start -->"));
    assert!(String::from_utf8_lossy(&output.stderr).contains("could not write"));
    assert_eq!(fs::read_to_string(target).unwrap(), "# Read only\n");
}

#[test]
fn max_agents_is_persisted_and_rendered() {
    let fixture = Fixture::new("instructions-max-agents");
    let target = fixture.root.join("AGENTS.md");
    let mut args = install_args(&target);
    args.extend(["--max-agents".into(), "2".into()]);

    let output = fixture.run(&args);
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let config = fs::read_to_string(fixture.config_file()).unwrap();
    assert!(config.contains("max_agents = 2"), "{config}");
    assert!(config.contains("[instructions]"), "{config}");
    assert!(
        fs::read_to_string(target)
            .unwrap()
            .contains("Run at most 2 subagents")
    );
}

#[test]
fn invalid_max_agents_exits_nonzero_without_writing_config_or_target() {
    let fixture = Fixture::new("instructions-invalid-max-agents");
    let target = fixture.root.join("AGENTS.md");
    let mut args = install_args(&target);
    args.extend(["--max-agents".into(), "0".into()]);

    let output = fixture.run(&args);
    assert!(!output.status.success());
    assert!(!target.exists());
    assert!(!fixture.config_file().exists());
}

#[test]
fn invalid_configured_max_agents_warns_and_uses_four() {
    let fixture = Fixture::new("instructions-invalid-configured-max-agents");
    let target = fixture.root.join("AGENTS.md");
    fs::create_dir_all(&fixture.config_dir).unwrap();
    fs::write(fixture.config_file(), "[orchestration]\nmax_agents = 0\n").unwrap();

    let output = fixture.run(&install_args(&target));
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert!(
        String::from_utf8_lossy(&output.stderr).contains("0 is not a positive integer"),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert!(
        fs::read_to_string(target)
            .unwrap()
            .contains("Run at most 4 subagents")
    );
}

#[test]
fn toz_note_is_included_only_when_the_command_is_available() {
    let with_toz = Fixture::new("instructions-toz-present");
    let target = with_toz.root.join("AGENTS.md");
    with_toz.stub_toz();
    let output = with_toz.run(&install_args(&target));
    assert!(output.status.success());
    assert!(
        fs::read_to_string(target)
            .unwrap()
            .contains("TOZ_NOTE_BLOCK")
    );

    let without_toz = Fixture::new("instructions-toz-absent");
    let target = without_toz.root.join("AGENTS.md");
    let output = without_toz.run(&install_args(&target));
    assert!(output.status.success());
    assert!(
        !fs::read_to_string(target)
            .unwrap()
            .contains("TOZ_NOTE_BLOCK")
    );
    assert!(
        !String::from_utf8_lossy(&output.stderr).contains("note --block` failed"),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
}

#[test]
fn targets_prints_persisted_absolute_paths() {
    let fixture = Fixture::new("instructions-targets");
    let target = fixture.root.join("AGENTS.md");
    let empty = fixture.run(&cli_args(&["instructions", "targets"]));
    assert!(empty.status.success());
    assert!(empty.stdout.is_empty());

    let installed = fixture.run(&install_args(&target));
    assert!(installed.status.success());
    let output = fixture.run(&cli_args(&["instructions", "targets"]));
    assert!(output.status.success());
    assert_eq!(text(&output), format!("{}\n", target.display()));
}

#[test]
fn legacy_toz_blocks_emit_the_migration_warning() {
    let fixture = Fixture::new("instructions-legacy-toz");
    let target = fixture.root.join("AGENTS.md");
    fs::write(
        &target,
        "# Existing\n\n<!-- varde-toz:start -->\nlegacy\n<!-- varde-toz:end -->\n",
    )
    .unwrap();

    let output = fixture.run(&install_args(&target));
    assert!(output.status.success());
    assert!(String::from_utf8_lossy(&output.stderr).contains("varde-toz install codex"));
}

#[test]
fn missing_parent_write_error_warns_and_prints_the_block() {
    let fixture = Fixture::new("instructions-missing-parent");
    let target = fixture.root.join("missing-parent").join("AGENTS.md");

    let output = fixture.run(&install_args(&target));
    assert!(output.status.success());
    assert!(String::from_utf8_lossy(&output.stderr).contains("could not write"));
    assert!(String::from_utf8_lossy(&output.stdout).contains("<!-- varde:start -->"));
    assert!(!target.exists());
}

#[test]
fn install_dry_run_prints_only_target_and_block_without_writing() {
    let fixture = Fixture::new("instructions-dry-run");
    let target = fixture.root.join("AGENTS.md");
    fs::write(&target, "Private target content\n").unwrap();
    let mut args = install_args(&target);
    args.push("--dry-run".into());

    let output = fixture.run(&args);
    assert!(output.status.success());
    assert!(text(&output).contains("would write the Varde instruction block"));
    assert!(text(&output).contains(&target.display().to_string()));
    assert!(text(&output).contains("<!-- varde:start -->"));
    assert!(!text(&output).contains("Private target content"));
    assert_eq!(
        fs::read_to_string(target).unwrap(),
        "Private target content\n"
    );
    assert!(!fixture.config_file().exists());
}
