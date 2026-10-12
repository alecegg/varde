use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, Output};

use tempfile::TempDir;
use varde::sync::embedded::{retired_names, skills};

#[cfg(unix)]
use std::os::unix::fs::{MetadataExt, PermissionsExt, symlink};

struct Sandbox {
    root: TempDir,
    home: PathBuf,
    config: PathBuf,
    pi_agent: PathBuf,
    cwd: PathBuf,
}

impl Sandbox {
    fn new() -> Self {
        let root = tempfile::tempdir().unwrap();
        let home = root.path().join("home");
        let config = root.path().join("config");
        let pi_agent = root.path().join("pi-agent");
        let cwd = root.path().join("work");
        for path in [&home, &config, &pi_agent, &cwd] {
            fs::create_dir_all(path).unwrap();
        }
        Self {
            root,
            home,
            config,
            pi_agent,
            cwd,
        }
    }

    fn run(&self, skills_dir: &Path, agents_dir: &Path, options: &[&str]) -> Output {
        let mut command = Command::new(env!("CARGO_BIN_EXE_varde"));
        command
            .args([
                "setup",
                "sync",
                "--skills-dir",
                skills_dir.to_str().unwrap(),
                "--agents-dir",
                agents_dir.to_str().unwrap(),
            ])
            .args(options)
            .current_dir(&self.cwd)
            .env_clear()
            .env("HOME", &self.home)
            .env("VARDE_CONFIG_DIR", &self.config)
            .env("PI_CODING_AGENT_DIR", &self.pi_agent)
            .env("VARDE_AGENTS_OPENCODE_VERSION", "1");
        if let Some(path) = std::env::var_os("PATH") {
            command.env("PATH", path);
        }
        command.output().unwrap()
    }
}

fn stdout(output: &Output) -> String {
    String::from_utf8_lossy(&output.stdout).into_owned()
}

fn stderr(output: &Output) -> String {
    String::from_utf8_lossy(&output.stderr).into_owned()
}

fn managed(path: &Path) {
    fs::create_dir_all(path).unwrap();
    fs::write(path.join(".varde-managed-skill"), "varde-managed-skill\n").unwrap();
}

fn assert_canonical_skills_intact(skills_dir: &Path) {
    assert!(
        fs::symlink_metadata(skills_dir)
            .unwrap()
            .file_type()
            .is_dir(),
        "{} is not a real directory",
        skills_dir.display()
    );
    for skill in skills() {
        let canonical = skills_dir.join(skill.name);
        assert!(
            fs::symlink_metadata(&canonical)
                .unwrap()
                .file_type()
                .is_dir(),
            "{} is not a real directory",
            canonical.display()
        );
        assert_eq!(
            fs::read(canonical.join(".varde-managed-skill")).unwrap(),
            b"varde-managed-skill\n"
        );
        for file in skill.files {
            let path = canonical.join(file.relative_path);
            assert_eq!(fs::read(&path).unwrap(), file.bytes, "{}", path.display());
        }
    }
}

fn assert_missing(path: &Path) {
    assert!(matches!(
        fs::symlink_metadata(path),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound
    ));
}

fn tree(root: &Path) -> Vec<PathBuf> {
    fn visit(root: &Path, current: &Path, paths: &mut Vec<PathBuf>) {
        for entry in fs::read_dir(current).unwrap() {
            let entry = entry.unwrap();
            let path = entry.path();
            paths.push(path.strip_prefix(root).unwrap().to_path_buf());
            if entry.file_type().unwrap().is_dir() {
                visit(root, &path, paths);
            }
        }
    }

    let mut paths = Vec::new();
    visit(root, root, &mut paths);
    paths.sort();
    paths
}

#[test]
fn installs_canonical_files_and_links_selected_harnesses_idempotently() {
    let sandbox = Sandbox::new();
    let skills_dir = sandbox.root.path().join("central/skills");
    let agents_dir = sandbox.root.path().join("central/agents");

    let output = sandbox.run(&skills_dir, &agents_dir, &["--harnesses", "claude"]);

    assert!(output.status.success(), "{}", stderr(&output));
    for skill in skills() {
        let canonical = skills_dir.join(skill.name);
        assert!(
            fs::symlink_metadata(&canonical)
                .unwrap()
                .file_type()
                .is_dir(),
            "{} is not a real directory",
            canonical.display()
        );
        assert_eq!(
            fs::read(canonical.join(".varde-managed-skill")).unwrap(),
            b"varde-managed-skill\n"
        );
        for file in skill.files {
            let path = canonical.join(file.relative_path);
            assert_eq!(fs::read(&path).unwrap(), file.bytes, "{}", path.display());
            #[cfg(unix)]
            assert_eq!(
                fs::metadata(&path).unwrap().permissions().mode() & 0o111 != 0,
                file.executable,
                "executable mode for {}",
                path.display()
            );
        }

        #[cfg(unix)]
        {
            let entry = sandbox.home.join(".claude/skills").join(skill.name);
            let metadata = fs::symlink_metadata(&entry).unwrap();
            assert!(metadata.file_type().is_symlink(), "{}", entry.display());
            assert_eq!(fs::read_link(&entry).unwrap(), canonical);
        }
    }

    #[cfg(unix)]
    {
        let entry = sandbox.home.join(".claude/skills/varde-change");
        let inode = fs::symlink_metadata(&entry).unwrap().ino();
        let again = sandbox.run(&skills_dir, &agents_dir, &["--harnesses", "claude"]);
        assert!(again.status.success(), "{}", stderr(&again));
        assert!(stdout(&again).contains("already linked"));
        assert_eq!(fs::symlink_metadata(entry).unwrap().ino(), inode);
    }
}

#[test]
fn selected_skills_are_persisted_additively_and_always_include_manage() {
    let sandbox = Sandbox::new();
    let skills_dir = sandbox.root.path().join("central/skills");
    let agents_dir = sandbox.root.path().join("central/agents");
    let retained = skills_dir.join("varde-review");
    managed(&retained);
    fs::write(retained.join("user.txt"), "keep").unwrap();

    let first = sandbox.run(
        &skills_dir,
        &agents_dir,
        &["--harnesses", "claude", "--skills", "varde-code"],
    );
    assert!(first.status.success(), "{}", stderr(&first));

    for name in ["varde-code", "varde-manage"] {
        assert!(skills_dir.join(name).is_dir(), "missing {name}");
        assert!(sandbox.home.join(".claude/skills").join(name).exists());
    }
    assert!(!skills_dir.join("varde-change").exists());
    assert!(!sandbox.home.join(".claude/skills/varde-change").exists());
    assert_eq!(
        fs::read_to_string(retained.join("user.txt")).unwrap(),
        "keep"
    );

    let second = sandbox.run(&skills_dir, &agents_dir, &["--harnesses", "claude"]);
    assert!(second.status.success(), "{}", stderr(&second));
    for name in ["varde-code", "varde-manage"] {
        assert!(skills_dir.join(name).is_dir(), "missing persisted {name}");
        assert!(sandbox.home.join(".claude/skills").join(name).exists());
    }
    assert!(!skills_dir.join("varde-change").exists());
}

#[test]
fn unknown_skill_names_report_the_valid_names() {
    let sandbox = Sandbox::new();
    let skills_dir = sandbox.root.path().join("central/skills");
    let agents_dir = sandbox.root.path().join("central/agents");

    let output = sandbox.run(&skills_dir, &agents_dir, &["--skills", "unknown"]);

    assert_eq!(output.status.code(), Some(2));
    let message = stderr(&output);
    assert!(message.contains("varde-code"), "{message}");
    assert!(message.contains("varde-manage"), "{message}");
}

#[test]
fn a_selection_installs_its_requires_closure() {
    let sandbox = Sandbox::new();
    let skills_dir = sandbox.root.path().join("central/skills");
    let agents_dir = sandbox.root.path().join("central/agents");

    let change = sandbox.run(
        &skills_dir,
        &agents_dir,
        &["--harnesses", "none", "--skills", "varde-change"],
    );
    assert!(change.status.success(), "{}", stderr(&change));
    for name in ["varde-change", "varde-review", "varde-manage"] {
        assert!(skills_dir.join(name).is_dir(), "missing {name}");
    }
    assert!(!skills_dir.join("varde-code").exists());

    let scan = sandbox.run(
        &skills_dir,
        &agents_dir,
        &["--harnesses", "none", "--skills", "varde-scan"],
    );
    assert!(scan.status.success(), "{}", stderr(&scan));
    for name in ["varde-scan", "varde-code"] {
        assert!(skills_dir.join(name).is_dir(), "missing {name}");
    }
}

#[test]
fn the_recommends_hint_repeats_the_saved_selection() {
    let sandbox = Sandbox::new();
    let skills_dir = sandbox.root.path().join("central/skills");
    let agents_dir = sandbox.root.path().join("central/agents");

    let output = sandbox.run(
        &skills_dir,
        &agents_dir,
        &["--harnesses", "none", "--skills", "varde-learn"],
    );

    assert!(output.status.success(), "{}", stderr(&output));
    let report = stdout(&output);
    assert!(
        report.contains("add it with --skills varde-learn,varde-change"),
        "{report}"
    );
}

#[cfg(unix)]
#[test]
fn skips_harness_skills_directories_that_resolve_to_the_canonical_folder() {
    for link_mode in ["symlink", "copy"] {
        for harness_directory_is_symlink in [false, true] {
            let sandbox = Sandbox::new();
            let harness_dir = sandbox.home.join(".claude/skills");
            let skills_dir = if harness_directory_is_symlink {
                sandbox.root.path().join("central/skills")
            } else {
                harness_dir.clone()
            };
            let agents_dir = sandbox.root.path().join("central/agents");

            if harness_directory_is_symlink {
                fs::create_dir_all(harness_dir.parent().unwrap()).unwrap();
                symlink(&skills_dir, &harness_dir).unwrap();
            }

            let options = ["--harnesses", "claude", "--link-mode", link_mode];
            let output = sandbox.run(&skills_dir, &agents_dir, &options);
            assert!(output.status.success(), "{}", stderr(&output));
            assert!(
                stdout(&output).contains(&format!(
                    "Skipped {}: it is the canonical skills folder",
                    harness_dir.display()
                )),
                "{}",
                stdout(&output)
            );
            assert_canonical_skills_intact(&skills_dir);

            if harness_directory_is_symlink {
                assert!(
                    fs::symlink_metadata(&harness_dir)
                        .unwrap()
                        .file_type()
                        .is_symlink()
                );
                assert_eq!(fs::read_link(&harness_dir).unwrap(), skills_dir);
            }

            let again = sandbox.run(&skills_dir, &agents_dir, &options);
            assert!(again.status.success(), "{}", stderr(&again));
            assert!(stdout(&again).contains("Skipped"), "{}", stdout(&again));
            assert_canonical_skills_intact(&skills_dir);
        }
    }
}

#[cfg(unix)]
#[test]
fn keeps_canonical_links_in_symlink_mode_and_replaces_them_in_copy_mode() {
    for link_mode in ["symlink", "copy"] {
        let sandbox = Sandbox::new();
        let skills_dir = sandbox.root.path().join("central/skills");
        let agents_dir = sandbox.root.path().join("central/agents");
        let harness_dir = sandbox.home.join(".claude/skills");
        let skill_name = skills()[0].name;
        let canonical = skills_dir.join(skill_name);
        let destination = harness_dir.join(skill_name);
        fs::create_dir_all(&harness_dir).unwrap();
        symlink(&canonical, &destination).unwrap();

        let options = ["--harnesses", "claude", "--link-mode", link_mode];
        let output = sandbox.run(&skills_dir, &agents_dir, &options);
        assert!(output.status.success(), "{}", stderr(&output));
        if link_mode == "symlink" {
            assert!(
                stdout(&output).contains("already linked"),
                "{}",
                stdout(&output)
            );
            assert_eq!(fs::read_link(&destination).unwrap(), canonical);
        } else {
            let metadata = fs::symlink_metadata(&destination).unwrap();
            assert!(metadata.file_type().is_dir());
            assert!(!metadata.file_type().is_symlink());
            assert_eq!(
                fs::read(destination.join(".varde-managed-skill")).unwrap(),
                b"varde-managed-skill\n"
            );
        }
        assert_canonical_skills_intact(&skills_dir);
    }
}

#[cfg(unix)]
#[test]
fn switches_harness_entries_from_symlinks_to_copies_and_back() {
    let sandbox = Sandbox::new();
    let skills_dir = sandbox.root.path().join("central/skills");
    let agents_dir = sandbox.root.path().join("central/agents");
    let harness_dir = sandbox.home.join(".claude/skills");

    let symlink_options = ["--harnesses", "claude", "--link-mode", "symlink"];
    let linked = sandbox.run(&skills_dir, &agents_dir, &symlink_options);
    assert!(linked.status.success(), "{}", stderr(&linked));
    for skill in skills() {
        let canonical = skills_dir.join(skill.name);
        let entry = harness_dir.join(skill.name);
        assert!(
            fs::symlink_metadata(&entry)
                .unwrap()
                .file_type()
                .is_symlink()
        );
        assert_eq!(fs::read_link(entry).unwrap(), canonical);
    }

    let copy_options = ["--harnesses", "claude", "--link-mode", "copy"];
    let copied = sandbox.run(&skills_dir, &agents_dir, &copy_options);
    assert!(copied.status.success(), "{}", stderr(&copied));
    for skill in skills() {
        let entry = harness_dir.join(skill.name);
        let metadata = fs::symlink_metadata(&entry).unwrap();
        assert!(metadata.file_type().is_dir(), "{}", entry.display());
        assert!(!metadata.file_type().is_symlink(), "{}", entry.display());
        assert_eq!(
            fs::read(entry.join(".varde-managed-skill")).unwrap(),
            b"varde-managed-skill\n"
        );
        for file in skill.files {
            assert_eq!(
                fs::read(entry.join(file.relative_path)).unwrap(),
                file.bytes,
                "{}",
                entry.join(file.relative_path).display()
            );
        }
    }
    assert_canonical_skills_intact(&skills_dir);

    let linked_again = sandbox.run(&skills_dir, &agents_dir, &symlink_options);
    assert!(linked_again.status.success(), "{}", stderr(&linked_again));
    for skill in skills() {
        let canonical = skills_dir.join(skill.name);
        let entry = harness_dir.join(skill.name);
        assert!(
            fs::symlink_metadata(&entry)
                .unwrap()
                .file_type()
                .is_symlink()
        );
        assert_eq!(fs::read_link(entry).unwrap(), canonical);
    }
    assert_canonical_skills_intact(&skills_dir);
}

#[test]
fn copy_mode_refreshes_managed_harness_copies_on_every_sync() {
    let sandbox = Sandbox::new();
    let skills_dir = sandbox.root.path().join("central/skills");
    let agents_dir = sandbox.root.path().join("central/agents");
    let options = ["--harnesses", "claude", "--link-mode", "copy"];

    let first = sandbox.run(&skills_dir, &agents_dir, &options);
    assert!(first.status.success(), "{}", stderr(&first));

    let canonical = skills_dir.join("varde-change");
    let copy = sandbox.home.join(".claude/skills/varde-change");
    assert!(fs::symlink_metadata(&copy).unwrap().file_type().is_dir());
    assert_eq!(
        fs::read(copy.join(".varde-managed-skill")).unwrap(),
        b"varde-managed-skill\n"
    );
    fs::write(copy.join("SKILL.md"), "edited harness copy").unwrap();
    fs::write(copy.join("stale.txt"), "remove on refresh").unwrap();

    let second = sandbox.run(&skills_dir, &agents_dir, &options);
    assert!(second.status.success(), "{}", stderr(&second));
    assert_eq!(
        fs::read(copy.join("SKILL.md")).unwrap(),
        fs::read(canonical.join("SKILL.md")).unwrap()
    );
    assert!(!copy.join("stale.txt").exists());
}

#[cfg(unix)]
#[test]
fn preserves_unowned_destinations_and_removes_only_managed_retired_skills() {
    let sandbox = Sandbox::new();
    let skills_dir = sandbox.root.path().join("central/skills");
    let agents_dir = sandbox.root.path().join("central/agents");
    let unowned = skills_dir.join("varde-change");
    fs::create_dir_all(&unowned).unwrap();
    fs::write(unowned.join("user.txt"), "keep").unwrap();

    let foreign_target = sandbox.root.path().join("user-skill");
    fs::create_dir_all(&foreign_target).unwrap();
    fs::write(foreign_target.join("SKILL.md"), "user-owned").unwrap();
    let foreign_canonical = skills_dir.join("varde-code");
    symlink(&foreign_target, &foreign_canonical).unwrap();
    let foreign_harness = sandbox.home.join(".claude/skills/varde-change");
    fs::create_dir_all(foreign_harness.parent().unwrap()).unwrap();
    symlink(&foreign_target, &foreign_harness).unwrap();

    let retired = retired_names();
    assert!(retired.len() >= 3, "need three retired skill fixtures");
    let retired_managed = skills_dir.join(retired[0]);
    let retired_unowned = skills_dir.join(retired[1]);
    managed(&retired_managed);
    fs::create_dir_all(&retired_unowned).unwrap();
    fs::write(retired_unowned.join("user.txt"), "keep").unwrap();

    let harness_dir = sandbox.home.join(".claude/skills");
    let retired_link = harness_dir.join(retired[0]);
    let retired_copy = harness_dir.join(retired[1]);
    let retired_foreign = harness_dir.join(retired[2]);
    fs::create_dir_all(&harness_dir).unwrap();
    symlink(&retired_managed, &retired_link).unwrap();
    managed(&retired_copy);
    fs::create_dir_all(&retired_foreign).unwrap();
    fs::write(retired_foreign.join("user.txt"), "keep").unwrap();

    let before_dry_run = tree(sandbox.root.path());
    let dry_run = sandbox.run(
        &skills_dir,
        &agents_dir,
        &["--harnesses", "claude", "--dry-run"],
    );
    assert!(dry_run.status.success(), "{}", stderr(&dry_run));
    let dry_run_report = stdout(&dry_run);
    assert!(
        dry_run_report.contains(&format!(
            "would remove retired harness skill {}",
            retired_link.display()
        )),
        "{dry_run_report}"
    );
    assert!(
        dry_run_report.contains(&format!(
            "would remove retired harness skill {}",
            retired_copy.display()
        )),
        "{dry_run_report}"
    );
    assert_eq!(tree(sandbox.root.path()), before_dry_run);
    assert_eq!(fs::read_link(&retired_link).unwrap(), retired_managed);
    assert!(retired_copy.join(".varde-managed-skill").exists());
    assert_eq!(fs::read(retired_foreign.join("user.txt")).unwrap(), b"keep");

    let output = sandbox.run(&skills_dir, &agents_dir, &["--harnesses", "claude"]);

    assert!(output.status.success(), "{}", stderr(&output));
    let report = stdout(&output);
    assert!(
        report.contains(&format!("Preserved unowned {}", unowned.display())),
        "{report}"
    );
    assert!(
        report.contains(&format!(
            "Preserved unowned {}",
            foreign_canonical.display()
        )),
        "{report}"
    );
    assert!(
        report.contains(&format!("Preserved unowned {}", foreign_harness.display())),
        "{report}"
    );
    assert_eq!(fs::read(unowned.join("user.txt")).unwrap(), b"keep");
    assert_eq!(fs::read_link(&foreign_canonical).unwrap(), foreign_target);
    assert_eq!(fs::read_link(&foreign_harness).unwrap(), foreign_target);
    assert_missing(&retired_managed);
    assert_eq!(fs::read(retired_unowned.join("user.txt")).unwrap(), b"keep");
    assert_missing(&retired_link);
    assert_missing(&retired_copy);
    assert!(
        report.contains(&format!("Preserved unowned {}", retired_foreign.display())),
        "{report}"
    );
    assert_eq!(fs::read(retired_foreign.join("user.txt")).unwrap(), b"keep");
}

#[cfg(unix)]
#[test]
fn pi_links_skills_under_agents_when_canonical_target_is_elsewhere() {
    let sandbox = Sandbox::new();
    let skills_dir = sandbox.root.path().join("central/skills");
    let agents_dir = sandbox.root.path().join("central/agents");

    let output = sandbox.run(&skills_dir, &agents_dir, &["--harnesses", "pi"]);

    assert!(output.status.success(), "{}", stderr(&output));
    for skill in skills() {
        let entry = sandbox.home.join(".agents/skills").join(skill.name);
        assert!(
            fs::symlink_metadata(&entry)
                .unwrap()
                .file_type()
                .is_symlink()
        );
        assert_eq!(fs::read_link(entry).unwrap(), skills_dir.join(skill.name));
    }
}

#[test]
fn dry_run_reports_skill_actions_without_writing_anything() {
    let sandbox = Sandbox::new();
    let skills_dir = sandbox.root.path().join("central/skills");
    let agents_dir = sandbox.root.path().join("central/agents");
    let before = tree(sandbox.root.path());

    let output = sandbox.run(
        &skills_dir,
        &agents_dir,
        &["--harnesses", "claude", "--dry-run"],
    );

    assert!(output.status.success(), "{}", stderr(&output));
    let report = stdout(&output);
    assert!(report.contains("would install"), "{report}");
    assert!(report.contains("would link"), "{report}");
    assert_eq!(tree(sandbox.root.path()), before);
}

#[cfg(unix)]
#[test]
fn a_failed_stage_keeps_the_previous_managed_copy_intact() {
    if unsafe { libc::geteuid() } == 0 {
        eprintln!("skipping read-only directory check when running as root");
        return;
    }

    let sandbox = Sandbox::new();
    let skills_dir = sandbox.root.path().join("central/skills");
    let agents_dir = sandbox.root.path().join("central/agents");
    let options = ["--harnesses", "none"];
    let first = sandbox.run(&skills_dir, &agents_dir, &options);
    assert!(first.status.success(), "{}", stderr(&first));

    let previous = skills_dir.join("varde-change/SKILL.md");
    let previous_bytes = fs::read(&previous).unwrap();
    let permissions = fs::metadata(&skills_dir).unwrap().permissions();
    let original_mode = permissions.mode();
    let mut read_only = permissions;
    read_only.set_mode(original_mode & !0o222);
    fs::set_permissions(&skills_dir, read_only).unwrap();

    let failed = sandbox.run(&skills_dir, &agents_dir, &options);

    let mut restored = fs::metadata(&skills_dir).unwrap().permissions();
    restored.set_mode(original_mode);
    fs::set_permissions(&skills_dir, restored).unwrap();
    assert!(!failed.status.success(), "{}", stdout(&failed));
    assert_eq!(fs::read(previous).unwrap(), previous_bytes);
}
