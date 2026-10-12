//! Every legacy command (hidden ones included) is reachable through exactly
//! one canonical `varde` path, and that path reaches the same subcommand.

use std::process::Command;

enum Module {
    Code,
    Workflow,
    Toz,
    Learn,
    Doc,
}

fn canonical(module: &Module, legacy: &[String]) -> Vec<String> {
    let first = legacy[0].as_str();
    let rest = &legacy[1..];
    let mut path: Vec<&str> = match (module, first) {
        (Module::Code, "scan") => vec!["scan"],
        (Module::Code, "test") => vec!["scan", "test"],
        (Module::Code, "rules_list") => vec!["scan", "rules", "list"],
        (Module::Code, "rules_seed") => vec!["scan", "rules", "seed"],
        (Module::Code, "rules_remove") => vec!["scan", "rules", "remove"],
        (Module::Code, "watch") => vec!["setup", "watch"],
        (Module::Code, other) => vec!["map", other],
        (Module::Workflow, "concept" | "lint") => vec!["knowledge", first],
        (Module::Doc, "spec") => vec!["doc", first],
        (Module::Workflow, "msg") => vec!["msg"],
        (Module::Workflow, "paths" | "instructions") => vec!["setup", first],
        (Module::Workflow, other) => vec!["plan", other],
        (Module::Toz, "doctor" | "migrate-metadata") => vec!["setup", first],
        (Module::Toz, "profile") => vec!["setup", "profiles"],
        (Module::Toz, other) => vec!["run", other],
        (Module::Learn, other) => vec!["learn", other],
        (Module::Doc, other) => vec!["doc", other],
    };
    path.extend(rest.iter().map(String::as_str));
    path.into_iter().map(String::from).collect()
}

fn nodes(command: &clap::Command, prefix: &mut Vec<String>, out: &mut Vec<Vec<String>>) {
    for sub in command.get_subcommands() {
        if sub.get_name() == "help" {
            continue;
        }
        prefix.push(sub.get_name().to_string());
        out.push(prefix.clone());
        nodes(sub, prefix, out);
        prefix.pop();
    }
}

#[test]
fn every_legacy_command_reaches_its_canonical_varde_path() {
    let trees = [
        (Module::Code, varde_code::cli_command()),
        (Module::Workflow, varde_workflow::cli_command()),
        (Module::Toz, varde_toz::cli_command()),
        (Module::Learn, varde_learn::cli_command()),
        (Module::Doc, varde_doc::cli_command()),
    ];
    let mut checked = 0;
    for (module, tree) in &trees {
        let mut legacy_paths = Vec::new();
        nodes(tree, &mut Vec::new(), &mut legacy_paths);
        assert!(!legacy_paths.is_empty());
        for legacy in legacy_paths {
            let mapped = canonical(module, &legacy);
            let output = Command::new(env!("CARGO_BIN_EXE_varde"))
                .args(&mapped)
                .arg("--help")
                .output()
                .unwrap();
            let stdout = String::from_utf8_lossy(&output.stdout);
            let name = legacy.last().unwrap();
            assert!(
                output.status.success() && stdout.contains(name.as_str()),
                "legacy {legacy:?} -> varde {mapped:?}: status {:?}\nstdout: {stdout}\nstderr: {}",
                output.status,
                String::from_utf8_lossy(&output.stderr)
            );
            checked += 1;
        }
    }
    assert!(checked > 80, "only {checked} commands enumerated");
}

#[test]
fn scan_setup_route_is_available() {
    let output = Command::new(env!("CARGO_BIN_EXE_varde"))
        .args(["scan", "setup", "--help"])
        .output()
        .unwrap();
    let stdout = String::from_utf8_lossy(&output.stdout);
    assert!(output.status.success(), "{stdout}");
    assert!(stdout.contains("Usage: varde scan setup"), "{stdout}");
}

#[test]
fn commands_outside_their_group_are_rejected() {
    for args in [
        ["plan", "concept", "list"].as_slice(),
        &["plan", "paths"],
        &["plan", "msg"],
        &["plan", "hook", "session-start"],
        &["knowledge", "readiness"],
        &["work", "paths"],
        &["run", "install", "x"],
        &["setup", "install"],
        &["setup", "uninstall"],
        &["setup", "hooks", "code"],
        &["setup", "hooks", "session", "install"],
        &["migrate-session-notes"],
        &["hook", "install"],
    ] {
        let output = Command::new(env!("CARGO_BIN_EXE_varde"))
            .args(args)
            .output()
            .unwrap();
        let stderr = String::from_utf8_lossy(&output.stderr);
        assert!(
            !output.status.success() && stderr.contains("unrecognized subcommand"),
            "varde {args:?}: status {:?}\nstderr: {stderr}",
            output.status
        );
    }
}

#[test]
fn app_owned_hook_installer_paths_are_canonical() {
    for action in ["install", "remove"] {
        let output = Command::new(env!("CARGO_BIN_EXE_varde"))
            .args(["setup", "hooks", action, "--help"])
            .output()
            .unwrap();
        let stdout = String::from_utf8_lossy(&output.stdout);
        assert!(
            output.status.success() && stdout.contains(&format!("varde setup hooks {action}")),
            "setup hooks {action}: {stdout}"
        );
    }
}

#[test]
fn app_owned_session_notes_migration_path_is_canonical() {
    let output = Command::new(env!("CARGO_BIN_EXE_varde"))
        .args(["setup", "migrate-session-notes", "--help"])
        .output()
        .unwrap();
    let stdout = String::from_utf8_lossy(&output.stdout);
    assert!(
        output.status.success() && stdout.contains("Usage: varde setup migrate-session-notes"),
        "{stdout}"
    );
    for option in ["--dry-run", "--json", "--all-projects", "--include-live"] {
        assert!(stdout.contains(option), "missing {option}:\n{stdout}");
    }
}
