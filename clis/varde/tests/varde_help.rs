//! `varde --help` lists the task commands; aliases and hidden entry
//! points parse but stay out of the listing.

use std::process::{Command, Output};

fn varde(args: &[&str]) -> Output {
    Command::new(env!("CARGO_BIN_EXE_varde"))
        .args(args)
        .output()
        .unwrap()
}

#[test]
fn help_lists_every_task_command() {
    let output = varde(&["--help"]);
    assert!(output.status.success());
    let stdout = String::from_utf8(output.stdout).unwrap();
    let listed: Vec<&str> = stdout
        .lines()
        .skip_while(|line| *line != "Commands:")
        .skip(1)
        .take_while(|line| !line.is_empty())
        .filter_map(|line| line.split_whitespace().next())
        .filter(|name| *name != "help")
        .collect();
    assert_eq!(
        listed,
        [
            "search",
            "map",
            "scan",
            "edit",
            "plan",
            "knowledge",
            "run",
            "learn",
            "doc",
            "msg",
            "setup"
        ]
    );
}

#[test]
fn msg_help_lists_send_and_read() {
    let output = varde(&["msg", "--help"]);
    let stdout = String::from_utf8_lossy(&output.stdout);
    assert!(output.status.success(), "{stdout}");
    assert!(stdout.contains("send"), "{stdout}");
    assert!(stdout.contains("read"), "{stdout}");
}

#[test]
fn enriched_help_explains_operational_guidance_and_eval_cost() {
    for (args, phrases) in [
        (
            vec!["learn", "eval", "output", "--help"],
            vec!["runs × evals × 2", "judging calls"],
        ),
        (
            vec!["learn", "friction", "list", "--help"],
            vec!["open (needs action)", "use this search before adding"],
        ),
        (
            vec!["learn", "friction", "add", "--help"],
            vec!["search with `friction list --text` first"],
        ),
        (
            vec!["learn", "friction", "set-status", "--help"],
            vec!["promoted (adopted)"],
        ),
        (
            vec!["learn", "eval", "calibrate", "--help"],
            vec!["calibrate before trusting"],
        ),
        (
            vec!["learn", "adopt", "recurrence", "--help"],
            vec![
                "empty output means none are recorded",
                "meta.skipped_invalid_timestamps",
            ],
        ),
        (
            vec!["setup", "sync", "--help"],
            vec!["--dry-run", "Sandbox denial", "Watcher registration"],
        ),
        (
            vec!["setup", "paths", "--help"],
            vec!["working", "knowledge"],
        ),
        (
            vec!["doc", "spec", "inventory", "--help"],
            vec!["reuse means verified cache", "--refresh"],
        ),
        (
            vec!["knowledge", "lint", "--help"],
            vec![
                "warnings such as orphan Concepts do not fail lint",
                "errors exit nonzero",
            ],
        ),
        (
            vec!["doc", "flow", "--help"],
            vec!["FLOW.md is missing or stale"],
        ),
        (
            vec!["doc", "lint", "--help"],
            vec!["glob over a non-skill directory aborts"],
        ),
        (
            vec!["doc", "frontmatter", "--help"],
            vec!["does not check body layout"],
        ),
    ] {
        let output = varde(&args);
        let stdout = String::from_utf8_lossy(&output.stdout);
        assert!(output.status.success(), "varde {args:?}: {stdout}");
        for phrase in phrases {
            assert!(
                stdout.contains(phrase),
                "varde {args:?} missing {phrase:?}: {stdout}"
            );
        }
    }
}

#[test]
fn knowledge_spec_inventory_is_not_a_route() {
    let output = varde(&["knowledge", "spec", "inventory", "--help"]);
    assert!(!output.status.success());
}

#[test]
fn edit_help_uses_varde_names_and_lists_preview_and_apply() {
    let edit = varde(&["edit", "--help"]);
    let edit_stdout = String::from_utf8_lossy(&edit.stdout);
    assert!(edit.status.success(), "{edit_stdout}");
    assert!(
        edit_stdout.contains("Usage: varde edit <COMMAND>"),
        "{edit_stdout}"
    );
    assert!(edit_stdout.contains("preview"), "{edit_stdout}");
    assert!(edit_stdout.contains("apply"), "{edit_stdout}");
    assert!(!edit_stdout.contains("varde-code"), "{edit_stdout}");

    for args in [
        &["edit", "preview", "--help"][..],
        &["edit", "apply", "--help"][..],
    ] {
        let output = varde(args);
        let stdout = String::from_utf8_lossy(&output.stdout);
        assert!(output.status.success(), "varde {args:?}: {stdout}");
        assert!(
            stdout
                .lines()
                .any(|line| line.starts_with("Usage: varde edit ")),
            "varde {args:?}: {stdout}"
        );
        assert!(!stdout.contains("varde-code"), "varde {args:?}: {stdout}");
    }
}

#[test]
fn version_is_the_workspace_version() {
    let output = varde(&["--version"]);
    assert!(output.status.success());
    assert_eq!(
        String::from_utf8(output.stdout).unwrap().trim(),
        format!("varde {}", env!("CARGO_PKG_VERSION"))
    );
}

#[test]
fn setup_and_hidden_aliases_parse() {
    let aliases: &[(&[&str], &str)] = &[
        (&["setup", "doctor"], "doctor"),
        (&["setup", "profiles", "list"], "list"),
        (&["setup", "migrate-metadata"], "migrate-metadata"),
        (&["setup", "migrate-session-notes"], "migrate-session-notes"),
        (&["setup", "hooks", "install"], "--force"),
        (&["setup", "hooks", "remove"], "--force"),
        (&["setup", "autosave", "install"], "--repo"),
        (&["setup", "autosave", "uninstall"], "--repo"),
        (&["setup", "autosave", "run"], "--repo"),
        (&["setup", "instructions", "targets"], "targets"),
        (&["setup", "paths"], "paths"),
        (&["setup", "watch"], "watch"),
        (&["scan", "test"], "test"),
        (&["scan", "setup"], "scan"),
        (&["scan", "rules", "list"], "rules_list"),
        (&["scan", "rules", "seed"], "rules_seed"),
        (&["scan", "rules", "remove"], "rules_remove"),
        (&["capture"], "capture"),
        (&["note"], "note"),
        (&["event"], "event"),
        (&["watch"], "watch"),
    ];
    for (path, name) in aliases {
        let output = varde(&[path.to_vec(), vec!["--help"]].concat());
        let stdout = String::from_utf8_lossy(&output.stdout);
        assert!(
            output.status.success() && stdout.contains(name),
            "varde {path:?}: {:?}\n{stdout}\n{}",
            output.status,
            String::from_utf8_lossy(&output.stderr)
        );
    }
}

#[test]
fn hidden_entry_points_stay_out_of_help() {
    let stdout = String::from_utf8(varde(&["--help"]).stdout).unwrap();
    for hidden in ["__worker", "capture", "note", "event", "hook", "watch"] {
        assert!(
            !stdout
                .lines()
                .any(|l| l.split_whitespace().next() == Some(hidden)),
            "{hidden} is listed"
        );
    }
}

#[test]
fn unknown_command_fails_and_module_help_stays_authoritative() {
    assert!(!varde(&["nope"]).status.success());
    let stdout = String::from_utf8(varde(&["map", "extract", "--help"]).stdout).unwrap();
    assert!(stdout.contains("varde map extract"), "{stdout}");
}

#[test]
fn router_only_paths_list_subcommands_and_help_matches_flag() {
    let cases: &[(&[&str], &str)] = &[
        (&["setup"], "hooks"),
        (&["setup"], "autosave"),
        (&["setup"], "migrate-session-notes"),
        (&["setup", "hooks"], "install"),
        (&["setup", "hooks"], "remove"),
        (&["setup", "autosave"], "install"),
        (&["setup", "autosave"], "uninstall"),
        (&["setup", "autosave"], "run"),
        (&["scan"], "setup"),
        (&["scan", "rules"], "seed"),
    ];
    for (path, listed) in cases {
        let flag = varde(&[path.to_vec(), vec!["--help"]].concat());
        let word = varde(&[vec!["help"], path.to_vec()].concat());
        let stdout = String::from_utf8(flag.stdout).unwrap();
        assert!(flag.status.success(), "varde {path:?} --help failed");
        assert!(stdout.contains(listed), "varde {path:?}: {stdout}");
        if *path == ["setup", "autosave"] {
            assert!(!stdout.contains("Subcommands:"), "{stdout}");
        }
        assert_eq!(stdout.as_bytes(), word.stdout.as_slice(), "help {path:?}");
    }
}

#[test]
fn scan_help_lists_router_subcommands() {
    let scan = varde(&["scan", "--help"]);
    let scan_stdout = String::from_utf8(scan.stdout).unwrap();
    assert!(scan.status.success(), "{scan_stdout}");
    let subcommands = scan_stdout
        .split_once("Subcommands:\n")
        .expect("scan help should list router subcommands")
        .1
        .lines()
        .take_while(|line| !line.trim().is_empty())
        .filter_map(|line| line.split_whitespace().next())
        .collect::<Vec<_>>();
    assert_eq!(subcommands, ["test", "setup", "rules"]);
    assert_child_descriptions_use_command_about(&scan_stdout, "Subcommands:\n");
    assert!(scan_stdout.lines().any(|line| {
        line.trim_start().starts_with("rules") && line.contains("Subcommands of `varde scan rules`")
    }));

    let help_scan = varde(&["help", "scan"]);
    let help_scan_stdout = String::from_utf8(help_scan.stdout).unwrap();
    assert!(help_scan.status.success(), "{help_scan_stdout}");
    let help_scan_subcommands = help_scan_stdout
        .split_once("Subcommands:\n")
        .expect("help scan should list router subcommands")
        .1
        .lines()
        .take_while(|line| !line.trim().is_empty())
        .filter_map(|line| line.split_whitespace().next())
        .collect::<Vec<_>>();
    assert_eq!(help_scan_subcommands, ["test", "setup", "rules"]);

    let rules = varde(&["scan", "rules", "--help"]);
    let rules_stdout = String::from_utf8(rules.stdout).unwrap();
    assert!(rules.status.success(), "{rules_stdout}");
    let commands = rules_stdout
        .split_once("Commands:\n")
        .expect("scan rules help should list its commands")
        .1
        .lines()
        .take_while(|line| !line.trim().is_empty())
        .filter_map(|line| line.split_whitespace().next())
        .filter(|name| *name != "help")
        .collect::<Vec<_>>();
    assert_eq!(commands, ["list", "diff", "seed", "remove"]);

    let map = varde(&["map", "--help"]);
    let map_stdout = String::from_utf8(map.stdout).unwrap();
    assert!(map.status.success(), "{map_stdout}");
    assert!(!map_stdout.contains("Subcommands:\n"));
}

fn assert_child_descriptions_use_command_about(stdout: &str, heading: &str) {
    let children = stdout
        .split_once(heading)
        .unwrap_or_else(|| panic!("missing {heading:?} in help:\n{stdout}"))
        .1
        .lines()
        .take_while(|line| !line.trim().is_empty());
    let module_labels = [
        "Code maps and scans",
        "Plans, reviews, and instructions",
        "Tool-output capture and setup",
        "Sessions, skills, and friction",
    ];

    for line in children {
        let Some((name, description)) = line.trim().split_once(char::is_whitespace) else {
            continue;
        };
        if name == "help" {
            continue;
        }
        assert!(
            !description.trim().is_empty(),
            "child {name:?} has no description: {line:?}"
        );
        for label in module_labels {
            assert!(
                !description.contains(label),
                "child {name:?} repeats module label {label:?}: {line:?}"
            );
        }
    }
}

#[test]
fn setup_child_descriptions_use_the_routed_command_about() {
    let output = varde(&["setup", "--help"]);
    let stdout = String::from_utf8_lossy(&output.stdout);
    assert!(output.status.success(), "{stdout}");
    assert_child_descriptions_use_command_about(&stdout, "Commands:\n");
}

#[test]
fn setup_sync_is_listed_and_documents_targets_and_recommended_layout() {
    let setup = varde(&["setup", "--help"]);
    let setup_stdout = String::from_utf8(setup.stdout).unwrap();
    assert!(setup.status.success());
    assert!(setup_stdout.contains("sync"), "{setup_stdout}");

    let sync = varde(&["setup", "sync", "--help"]);
    let sync_stdout = String::from_utf8_lossy(&sync.stdout).into_owned();
    assert!(sync.status.success());
    for item in [
        "--skills-dir",
        "--agents-dir",
        "--link-mode",
        "canonical central copy",
    ] {
        assert!(sync_stdout.contains(item), "missing {item}: {sync_stdout}");
    }

    let help_word = varde(&["help", "setup", "sync"]);
    assert!(help_word.status.success());
    assert_eq!(sync.stdout, help_word.stdout);
}

#[test]
fn routed_usage_and_group_about_use_varde_names() {
    let forbidden = [
        "varde-code",
        "varde-workflow",
        "varde-toz",
        "varde-learn",
        "toz ",
    ];
    for args in [
        vec!["learn", "friction", "list", "--help"],
        vec!["setup", "hooks", "install", "--help"],
        vec!["setup", "doctor", "--help"],
    ] {
        let output = varde(&args);
        let stdout = String::from_utf8_lossy(&output.stdout);
        assert!(output.status.success(), "varde {args:?}: {stdout}");
        let usage = stdout.lines().find(|line| line.starts_with("Usage:"));
        assert!(
            usage.is_some_and(|line| line.starts_with("Usage: varde ")),
            "varde {args:?} has no varde usage path: {stdout}"
        );
        for name in forbidden {
            assert!(
                !stdout.contains(name),
                "varde {args:?} contains {name:?}: {stdout}"
            );
        }
    }

    for (args, about, forbidden_about) in [
        (
            ["map", "--help"],
            "Query the code index (symbols, dependencies, impact)",
            "varde-code: native code-intelligence CLI",
        ),
        (
            ["plan", "--help"],
            "Plans, tasks and reviews",
            "Concept/Knowledge Bundle CRUD with OCC writes",
        ),
        (
            ["learn", "--help"],
            "Diagnose sessions, evaluate skills, record friction",
            "Trigger-accuracy and output-quality evaluation tool",
        ),
        (
            ["run", "--help"],
            "Capture, query and index command output",
            "Tool-output capture and setup",
        ),
    ] {
        let output = varde(&args);
        let stdout = String::from_utf8_lossy(&output.stdout);
        assert!(output.status.success(), "varde {args:?}: {stdout}");
        assert!(
            stdout
                .lines()
                .find(|line| line.starts_with("Usage:"))
                .is_some_and(|line| line.starts_with(&format!("Usage: varde {} ", args[0]))),
            "varde {args:?} has no routed usage identity: {stdout}"
        );
        assert!(stdout.contains(about), "varde {args:?}: {stdout}");
        assert!(
            !stdout.contains(forbidden_about),
            "varde {args:?} retains its module-specific about text: {stdout}"
        );
    }

    let setup = varde(&["setup", "--help"]);
    let setup_stdout = String::from_utf8_lossy(&setup.stdout);
    assert!(setup.status.success(), "{setup_stdout}");
    for name in ["varde-code", "varde-workflow", "varde-toz", "varde-learn"] {
        assert!(
            !setup_stdout.contains(name),
            "setup group help contains {name:?}: {setup_stdout}"
        );
    }
}
