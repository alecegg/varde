//! The `varde` command surface: eleven task commands, plus hidden aliases for
//! every self-invoked entry point. Each path forwards to one module's `run`
//! with a Varde route as argv0 and any legacy subcommand words preserved, so
//! module help and errors stay authoritative. Routing is a table scan on plain
//! strings so the hot `capture --hook` path does no parsing before it reaches
//! the module.

use clap::Command;
use std::ffi::OsString;
use std::process::ExitCode;
use varde_contracts::Io;

const MAP_ABOUT: &str = "Query the code index (symbols, dependencies, impact)";
const PLAN_ABOUT: &str = "Plans, tasks and reviews";
const MSG_ABOUT: &str = "Send and read one-line inbox messages between agents";
const KNOWLEDGE_ABOUT: &str = "Knowledge bundle concepts and lint";
const RUN_ABOUT: &str = "Capture, query and index command output";
const LEARN_ABOUT: &str = "Diagnose sessions, evaluate skills, record friction";
const DOC_ABOUT: &str = "Check agent-facing Markdown documents";

#[derive(Clone, Copy)]
enum Module {
    Code,
    Workflow,
    Toz,
    Learn,
    Doc,
    Autosave,
    SessionNotes,
}

impl Module {
    fn about(self) -> &'static str {
        match self {
            Module::Code => "Code maps and scans",
            Module::Workflow => "Plans, reviews, and instructions",
            Module::Toz => "Tool-output capture and setup",
            Module::Learn => "Sessions, skills, and friction",
            Module::Doc => "Agent document checks",
            Module::Autosave => {
                "Scheduled commits and secret-scanned pushes for standalone Git stores"
            }
            Module::SessionNotes => "Move legacy handoff files into session-notes",
        }
    }

    fn run(self, argv: Vec<OsString>, io: &Io<'static>) -> ExitCode {
        match self {
            Module::Code => varde_code::run(argv, io),
            Module::Workflow => varde_workflow::run(argv, io),
            Module::Toz => varde_toz::run(argv, io),
            Module::Learn => varde_learn::run(argv, io),
            Module::Doc => varde_doc::run(argv, io),
            Module::Autosave => crate::autosave::run(argv),
            Module::SessionNotes => crate::setup_session_notes::run(argv),
        }
    }

    fn command(self) -> Command {
        match self {
            Module::Code => varde_code::cli_command(),
            Module::Workflow => varde_workflow::cli_command(),
            Module::Toz => varde_toz::cli_command(),
            Module::Learn => varde_learn::cli_command(),
            Module::Doc => varde_doc::cli_command(),
            Module::Autosave => crate::autosave::command(),
            Module::SessionNotes => crate::setup_session_notes::command(),
        }
    }
}

/// `varde <path> <rest..>` runs `<module> <legacy..> <rest..>`. `deny` lists
/// the word right after `path` when it belongs to another path (so no second
/// route to the same command exists unless it is a declared alias). Options in
/// that position are not checked.
struct Route {
    path: &'static [&'static str],
    module: Module,
    legacy: &'static [&'static str],
    deny: &'static [&'static str],
}

const fn route(
    path: &'static [&'static str],
    module: Module,
    legacy: &'static [&'static str],
) -> Route {
    Route {
        path,
        module,
        legacy,
        deny: &[],
    }
}

use Module::{Autosave, Code, Doc, Learn, SessionNotes, Toz, Workflow};

const ROUTES: &[Route] = &[
    // map: every query mode plus extract, build, batch, slice_state.
    Route {
        path: &["map"],
        module: Code,
        legacy: &[],
        deny: &[
            "scan",
            "test",
            "rules_list",
            "rules_seed",
            "rules_remove",
            "hooks",
            "watch",
        ],
    },
    // scan: the scan itself unless the first word names a scan subcommand.
    Route {
        path: &["scan"],
        module: Code,
        legacy: &["scan"],
        deny: &["test", "setup", "rules"],
    },
    route(&["scan", "test"], Code, &["test"]),
    route(&["scan", "setup"], Code, &["scan"]),
    route(&["scan", "rules", "list"], Code, &["rules_list"]),
    route(&["scan", "rules", "diff"], Code, &["rules_list"]),
    route(&["scan", "rules", "seed"], Code, &["rules_seed"]),
    route(&["scan", "rules", "remove"], Code, &["rules_remove"]),
    // plan: lifecycle commands; knowledge and setup commands live elsewhere.
    Route {
        path: &["plan"],
        module: Workflow,
        legacy: &[],
        deny: &["concept", "lint", "paths", "instructions", "hook", "msg"],
    },
    // msg: the inbox commands live in the workflow module but at the top level.
    route(&["msg"], Workflow, &["msg"]),
    route(&["knowledge", "concept"], Workflow, &["concept"]),
    route(&["knowledge", "lint"], Workflow, &["lint"]),
    // run: toz commands that are not setup.
    Route {
        path: &["run"],
        module: Toz,
        legacy: &[],
        deny: &[
            "install",
            "uninstall",
            "doctor",
            "profile",
            "migrate-metadata",
        ],
    },
    route(&["learn"], Learn, &[]),
    route(&["doc"], Doc, &[]),
    route(&["doc", "spec"], Doc, &["spec"]),
    route(&["setup", "doctor"], Toz, &["doctor"]),
    route(&["setup", "profiles"], Toz, &["profile"]),
    route(&["setup", "migrate-metadata"], Toz, &["migrate-metadata"]),
    route(&["setup", "instructions"], Workflow, &["instructions"]),
    route(&["setup", "paths"], Workflow, &["paths"]),
    route(&["setup", "autosave"], Autosave, &[]),
    route(&["setup", "migrate-session-notes"], SessionNotes, &[]),
    route(&["setup", "watch"], Code, &["watch"]),
    // Hidden aliases: a written or re-executed command only swaps the
    // executable path. They match only as the first argument, so toz global
    // options go after `varde run` (`varde run --fallback-dir D note`), never
    // before an alias.
    route(&["__worker"], Toz, &["__worker"]),
    route(&["capture"], Toz, &["capture"]),
    route(&["note"], Toz, &["note"]),
    route(&["event"], Toz, &["event"]),
    route(&["watch"], Code, &["watch"]),
];

/// The module and legacy argv for `args` (including the program name), or
/// `None` when no route matches.
fn resolve(args: &[OsString]) -> Option<(&'static Route, Vec<OsString>)> {
    let words: Vec<&str> = args.iter().skip(1).map_while(|a| a.to_str()).collect();
    let route = ROUTES
        .iter()
        .filter(|r| words.starts_with(r.path))
        .filter(|r| words.get(r.path.len()).is_none_or(|w| !r.deny.contains(w)))
        .max_by_key(|r| r.path.len())?;
    let argv0_path = if route.legacy.is_empty() {
        route.path
    } else {
        &route.path[..route.path.len() - 1]
    };
    let argv0 = if argv0_path.is_empty() {
        "varde".to_string()
    } else {
        format!("varde {}", argv0_path.join(" "))
    };
    let mut argv = vec![OsString::from(argv0)];
    argv.extend(route.legacy.iter().map(OsString::from));
    let tail = &args[1 + route.path.len()..];
    if route.path == ["scan", "rules", "diff"] {
        if tail
            .first()
            .is_some_and(|arg| arg == "--help" || arg == "-h")
        {
            argv.extend_from_slice(tail);
        } else {
            let rule_id = tail
                .first()
                .and_then(|arg| arg.to_str())
                .unwrap_or_default();
            let input = serde_json::json!({
                "repoRoot": ".",
                "operation": "diff",
                "ruleId": rule_id,
            })
            .to_string();
            argv.push(OsString::from("--json"));
            argv.push(OsString::from(input));
            argv.extend_from_slice(tail.get(1..).unwrap_or_default());
        }
    } else if route.path == ["scan", "setup"] {
        if tail
            .first()
            .is_some_and(|arg| arg == "--help" || arg == "-h")
        {
            argv.extend_from_slice(tail);
        } else if let Some(rewritten) = rewrite_scan_setup_json(tail) {
            argv.extend(rewritten);
        } else {
            argv.extend_from_slice(tail);
        }
    } else if route.path == ["scan", "rules", "seed"] {
        if let Some(rewritten) = rewrite_seed_rule_id(tail) {
            argv.extend(rewritten);
        } else {
            argv.extend_from_slice(tail);
        }
    } else {
        argv.extend_from_slice(tail);
    }
    Some((route, argv))
}

/// Mark JSON routed through `varde scan setup` for the existing scan dispatcher.
fn rewrite_scan_setup_json(args: &[OsString]) -> Option<Vec<OsString>> {
    let mut json = None;
    let mut user_scope = false;
    let mut remaining = Vec::new();
    let mut index = 0;
    while index < args.len() {
        match args[index].to_str()? {
            "--json" => {
                if json.is_some() {
                    return None;
                }
                json = Some(args.get(index + 1)?.to_str()?.to_owned());
                index += 2;
            }
            "--user" => {
                if user_scope {
                    return None;
                }
                user_scope = true;
                index += 1;
            }
            _ => {
                remaining.push(args[index].clone());
                index += 1;
            }
        }
    }
    let mut input: serde_json::Value = serde_json::from_str(&json?).ok()?;
    input.as_object_mut()?.insert(
        "operation".to_owned(),
        serde_json::Value::String("setup".to_owned()),
    );
    if user_scope {
        input.as_object_mut()?.insert(
            "scope".to_owned(),
            serde_json::Value::String("user".to_owned()),
        );
    }
    let mut rewritten = vec![OsString::from("--json"), OsString::from(input.to_string())];
    rewritten.extend(remaining);
    Some(rewritten)
}

/// Move the router-only `--rule-id` option into the code module's JSON input.
fn rewrite_seed_rule_id(args: &[OsString]) -> Option<Vec<OsString>> {
    let mut rule_id = None;
    let mut json = None;
    let mut remaining = Vec::new();
    let mut index = 0;
    while index < args.len() {
        match args[index].to_str()? {
            "--rule-id" => {
                if rule_id.is_some() {
                    return None;
                }
                rule_id = Some(args.get(index + 1)?.to_str()?.to_owned());
                index += 2;
            }
            "--json" => {
                if json.is_some() {
                    return None;
                }
                json = Some(args.get(index + 1)?.to_str()?.to_owned());
                index += 2;
            }
            _ => {
                remaining.push(args[index].clone());
                index += 1;
            }
        }
    }
    let rule_id = rule_id?;
    let mut input: serde_json::Value = serde_json::from_str(&json?).ok()?;
    input
        .as_object_mut()?
        .insert("ruleId".to_owned(), serde_json::Value::String(rule_id));
    let mut rewritten = vec![OsString::from("--json"), OsString::from(input.to_string())];
    rewritten.extend(remaining);
    Some(rewritten)
}

/// The longest route whose path matches `args` and whose `deny` list holds
/// the next word, with that word, unless that word is a router child (the
/// surface parser then reports it). `resolve` skips such a route.
fn denied_word(args: &[OsString]) -> Option<(&'static Route, &str)> {
    let words: Vec<&str> = args.iter().skip(1).map_while(|a| a.to_str()).collect();
    ROUTES
        .iter()
        .filter(|r| words.starts_with(r.path))
        .filter_map(|r| {
            let word = *words.get(r.path.len())?;
            (r.deny.contains(&word) && !child_names(r.path).contains(&word)).then_some((r, word))
        })
        .max_by_key(|(r, _)| r.path.len())
}

/// The help line for the node at `path`: the module command a route runs, or
/// a group heading when no route ends there.
fn about_for(path: &[&str]) -> String {
    if path == ["scan", "setup"] {
        return "Apply a scan preset and show effective rules".to_owned();
    }
    match ROUTES.iter().find(|r| r.path == path) {
        Some(route) if !route.legacy.is_empty() => {
            let mut command = route.module.command();
            for name in route.legacy {
                let Some(subcommand) = command
                    .get_subcommands()
                    .find(|subcommand| subcommand.get_name() == *name)
                else {
                    return route.module.about().to_string();
                };
                command = subcommand.clone();
            }
            command
                .get_about()
                .map(ToString::to_string)
                .unwrap_or_else(|| route.module.about().to_string())
        }
        Some(route) => route.module.about().to_string(),
        None => format!("Subcommands of `varde {}`", path.join(" ")),
    }
}

fn group_about(name: &str) -> Option<&'static str> {
    match name {
        "map" => Some(MAP_ABOUT),
        "plan" => Some(PLAN_ABOUT),
        "knowledge" => Some(KNOWLEDGE_ABOUT),
        "run" => Some(RUN_ABOUT),
        "learn" => Some(LEARN_ABOUT),
        "doc" => Some(DOC_ABOUT),
        _ => None,
    }
}

/// The direct child names that `ROUTES` declares below `prefix`.
fn child_names(prefix: &[&str]) -> Vec<&'static str> {
    let mut names: Vec<&'static str> = Vec::new();
    for r in ROUTES
        .iter()
        .filter(|r| r.path.len() > prefix.len() && r.path.starts_with(prefix))
    {
        if !names.contains(&r.path[prefix.len()]) {
            names.push(r.path[prefix.len()]);
        }
    }
    names
}

/// Adds the subcommands that `ROUTES` declares below `prefix`, recursively.
fn nest(mut cmd: Command, prefix: &[&'static str]) -> Command {
    let names = child_names(prefix);
    if !names.is_empty() {
        cmd = cmd.arg_required_else_help(true);
    }
    for name in names {
        let path = [prefix, &[name]].concat();
        let child = Command::new(name).about(about_for(&path));
        cmd = cmd.subcommand(nest(child, &path));
    }
    cmd
}

fn help_requested(args: &[OsString], route: &Route) -> bool {
    (args.len() == route.path.len() + 2
        || (route.path == ["doc", "spec"]
            && args.len() == route.path.len() + 3
            && args
                .get(args.len() - 2)
                .is_some_and(|arg| arg == "inventory"))
        || (route.path == ["doc"]
            && args.len() == route.path.len() + 3
            && args.get(args.len() - 2).is_some_and(|arg| arg == "flow")))
        && args
            .last()
            .is_some_and(|arg| arg == "-h" || arg == "--help")
}

fn module_help_command(route: &Route) -> Command {
    let mut command = route.module.command();
    for name in route.deny {
        if command
            .get_subcommands()
            .any(|subcommand| subcommand.get_name() == *name)
        {
            command = command.mut_subcommand(*name, |subcommand| subcommand.hide(true));
        }
    }
    command
}

/// Render module help without `Parser::parse_from`'s immediate process exit,
/// then append child routes that only exist in the Varde router.
fn routed_help(route: &Route, argv: Vec<OsString>) -> ExitCode {
    if route.path == ["scan", "rules", "diff"] {
        let help = Command::new("varde scan rules diff")
            .about("Show a seeded rule pack against its current built-in version")
            .arg(clap::Arg::new("rule-id").required(true).value_name("ID"))
            .try_get_matches_from(["varde scan rules diff", "--help"])
            .expect_err("diff help requested")
            .to_string();
        print!("{help}");
        return ExitCode::SUCCESS;
    }
    if route.path == ["scan", "setup"] {
        let help = scan_setup_command()
            .try_get_matches_from(["varde scan setup", "--help"])
            .expect_err("scan setup help requested")
            .to_string();
        print!("{help}");
        return ExitCode::SUCCESS;
    }
    let mut command = module_help_command(route);
    if route.path == ["setup", "doctor"] {
        command = command.mut_subcommand("doctor", |doctor| {
            let about = doctor
                .get_about()
                .map(ToString::to_string)
                .unwrap_or_default();
            doctor.long_about(format!(
                "{about}\n\nevent states are installed, missing, edited, unsupported, or blocked."
            ))
        });
    }
    if route.path == ["setup", "paths"] {
        command = command.mut_subcommand("paths", |paths| {
            let about = paths
                .get_about()
                .map(ToString::to_string)
                .unwrap_or_default();
            paths.long_about(format!(
                "{about}\n\n--json includes the resolved `working` and `knowledge` paths."
            ))
        });
    }
    if route.path == ["knowledge", "lint"] {
        command = command.mut_subcommand("lint", |lint| {
            let about = lint
                .get_about()
                .map(ToString::to_string)
                .unwrap_or_default();
            lint.long_about(format!(
                "{about}\n\nwarnings such as orphan Concepts do not fail lint, while errors exit nonzero."
            ))
        });
    }
    if route.path == ["doc", "spec"] {
        command = command.mut_subcommand("spec", |spec| {
            spec.mut_subcommand("inventory", |inventory| {
                let about = inventory
                    .get_about()
                    .map(ToString::to_string)
                    .unwrap_or_default();
                inventory.long_about(format!("{about}\n\nreuse means verified cache, inspect needs classification, and stale means source or provenance changed."))
            })
        });
    }
    if route.path == ["doc"] {
        command = command.mut_subcommand("flow", |flow| {
            flow.mut_arg("check", |arg| {
                arg.help("Exit 1 when a skill's FLOW.md is missing or stale; checks generated flow docs.")
            })
        });
    }
    if route.path == ["scan", "rules", "seed"] {
        command = command.mut_subcommand("rules_seed", |subcommand| {
            subcommand.arg(
                clap::Arg::new("rule-id")
                    .long("rule-id")
                    .value_name("ID")
                    .help("Seed only the built-in pack containing this rule id"),
            )
        });
    }
    if route.legacy.is_empty()
        && let Some(about) = group_about(route.path[0])
    {
        command = command.about(about).long_about(None);
    }
    let help = match command.try_get_matches_from(argv) {
        Err(error) if error.kind() == clap::error::ErrorKind::DisplayHelp => error.to_string(),
        Err(error) => error.exit(),
        Ok(_) => return ExitCode::SUCCESS,
    };
    let children = child_names(route.path);
    if children.is_empty() {
        print!("{help}");
        return ExitCode::SUCCESS;
    }
    let width = children.iter().map(|name| name.len()).max().unwrap_or(0);
    print!("{help}\nSubcommands:\n");
    for name in children {
        let path = [route.path, &[name]].concat();
        println!("  {name:width$}  {}", about_for(&path));
    }
    ExitCode::SUCCESS
}

fn scan_setup_command() -> Command {
    Command::new("varde scan setup")
        .about("Apply a scan preset and show effective rules")
        .after_help("Presets affect nine warning-default maintainability rules. Minimal disables them; strict raises them to errors. The dependency-boundary rule remains an error by default and is inactive until both prefixes are configured.\n\nBalanced keeps existing overrides unchanged. Minimal and strict write overrides. Scope defaults to repo; use user for user configuration. Existing overrides are replaced only with --force.")
        .arg(
            clap::Arg::new("json")
                .long("json")
                .required(true)
                .value_name("JSON")
                .help("JSON object: { repoRoot, preset (minimal|balanced|strict), scope? (repo|user), force? }"),
        )
        .arg(
            clap::Arg::new("force")
                .long("force")
                .action(clap::ArgAction::SetTrue)
                .help("Overwrite an existing overrides file; required to replace it"),
        )
        .arg(
            clap::Arg::new("user")
                .long("user")
                .action(clap::ArgAction::SetTrue)
                .help("Write overrides to the user configuration"),
        )
}

/// Help, version and usage errors for words that reach no module.
fn surface() -> Command {
    let sub =
        |name: &'static str, about: &'static str| nest(Command::new(name).about(about), &[name]);
    let setup = sub("setup", "Install, configure and diagnose Varde")
        .subcommand(Command::new("sync").about(crate::sync::SYNC_ABOUT))
        .subcommand(
            Command::new("hooks")
                .about("Install and remove the unified harness hooks")
                .arg_required_else_help(true)
                .subcommand(crate::hooks_install::command("install"))
                .subcommand(crate::hooks_install::command("remove")),
        )
        .mut_subcommand("autosave", |_| crate::autosave::command());
    Command::new("varde")
        .version(env!("CARGO_PKG_VERSION"))
        .about("Code maps, scans, workflow state, tool-output capture and learning")
        .arg_required_else_help(true)
        .subcommand(
            Command::new("search")
                .about("Search code, docs, knowledge, plans, captured output and friction"),
        )
        .subcommand(sub("map", MAP_ABOUT))
        .subcommand(sub(
            "scan",
            "Scan the code against rule packs; manage rules",
        ))
        .subcommand(sub("edit", "Preview and apply AST edits"))
        .subcommand(sub("plan", PLAN_ABOUT))
        .subcommand(sub("knowledge", KNOWLEDGE_ABOUT))
        .subcommand(sub("run", RUN_ABOUT))
        .subcommand(sub("learn", LEARN_ABOUT))
        .subcommand(sub("doc", DOC_ABOUT))
        .subcommand(sub("msg", MSG_ABOUT))
        .subcommand(setup)
}

pub fn main(mut args: Vec<OsString>, io: &Io<'static>) -> ExitCode {
    // The hook dispatchers are app-owned and skip every parse; PostToolUse is hot.
    if args.get(1).is_some_and(|a| a == "hook")
        && args.get(2).is_some_and(|a| {
            a == "session-start" || a == "post-tool-use" || a == "user-prompt-submit"
        })
    {
        return crate::hook::run(args.split_off(2), io);
    }
    // `varde help <path>` prints what `varde <path> --help` prints.
    if args.get(1).is_some_and(|a| a == "help") {
        args.remove(1);
        args.push(OsString::from("--help"));
    }
    if args.get(1).is_some_and(|a| a == "search") {
        return crate::search::run(args.split_off(1));
    }
    if args.get(1).is_some_and(|a| a == "edit") {
        return crate::edit::run(args.split_off(1), io);
    }
    if args.get(1).is_some_and(|a| a == "setup") && args.get(2).is_some_and(|a| a == "sync") {
        return crate::sync::run(args.split_off(2));
    }
    if args.get(1).is_some_and(|a| a == "setup")
        && args.get(2).is_some_and(|a| a == "hooks")
        && args.get(3).is_some_and(|a| a == "install" || a == "remove")
    {
        return crate::hooks_install::run(args.split_off(3));
    }
    if let Some((route, word)) = denied_word(&args) {
        module_help_command(route)
            .bin_name(format!("varde {}", route.path.join(" ")))
            .error(
                clap::error::ErrorKind::InvalidSubcommand,
                format!("unrecognized subcommand '{word}'"),
            )
            .exit();
    }
    if let Some((route, argv)) = resolve(&args) {
        if help_requested(&args, route) {
            return routed_help(route, argv);
        }
        if route.path == ["setup", "doctor"] {
            let section = crate::hooks_install::doctor_section();
            return varde_toz::run_with_doctor_section(argv, io, section);
        }
        return route.module.run(argv, io);
    }
    if let Err(error) = surface().try_get_matches_from(&args) {
        error.exit();
    }
    eprintln!("varde: incomplete command; run `varde <command> --help`");
    ExitCode::from(2)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn scan_setup_help_explains_presets_scope_and_override_replacement() {
        let help = scan_setup_command()
            .try_get_matches_from(["varde scan setup", "--help"])
            .unwrap_err()
            .to_string();

        for phrase in [
            "nine warning-default maintainability rules",
            "Minimal disables them",
            "strict raises them to errors",
            "Balanced keeps existing overrides unchanged",
            "Scope defaults to repo",
            "Existing overrides are replaced only with --force",
        ] {
            assert!(help.contains(phrase), "missing {phrase:?} in help:\n{help}");
        }
    }

    #[test]
    fn map_help_hides_subcommands_rejected_by_the_router() {
        let route = ROUTES.iter().find(|route| route.path == ["map"]).unwrap();
        let error = module_help_command(route)
            .try_get_matches_from(["varde map", "--help"])
            .unwrap_err();
        let help = error.to_string();
        let commands = help.split("Commands:").nth(1).unwrap_or(&help);

        for name in route.deny {
            assert!(
                !commands
                    .lines()
                    .any(|line| { line.split_whitespace().next() == Some(name) }),
                "router-rejected subcommand {name} is listed:\n{help}"
            );
        }
        assert!(resolve(&["varde", "scan"].map(OsString::from)).is_some());
        assert!(resolve(&["varde", "scan", "rules", "list"].map(OsString::from)).is_some());
        assert!(resolve(&["varde", "setup", "watch"].map(OsString::from)).is_some());

        let scan_route = ROUTES.iter().find(|route| route.path == ["scan"]).unwrap();
        let scan_help = module_help_command(scan_route)
            .try_get_matches_from(["varde scan", "scan", "--help"])
            .unwrap_err();
        assert_eq!(scan_help.kind(), clap::error::ErrorKind::DisplayHelp);
    }

    #[test]
    fn rules_diff_routes_the_positional_id_through_rules_list() {
        let args = ["varde", "scan", "rules", "diff", "no-console"].map(OsString::from);
        let (_, argv) = resolve(&args).expect("rules diff route");
        assert_eq!(argv[1], "rules_list");
        assert_eq!(argv[2], "--json");
        let input: serde_json::Value = serde_json::from_str(argv[3].to_str().unwrap()).unwrap();
        assert_eq!(input["repoRoot"], ".");
        assert_eq!(input["operation"], "diff");
        assert_eq!(input["ruleId"], "no-console");
    }

    #[test]
    fn rules_seed_moves_rule_id_into_json_and_preserves_other_flags() {
        let args = [
            "varde",
            "scan",
            "rules",
            "seed",
            "--json",
            "{\"repoRoot\":\"/tmp/repo\"}",
            "--force",
            "--rule-id",
            "no-console",
        ]
        .map(OsString::from);
        let (_, argv) = resolve(&args).expect("rules seed route");
        assert_eq!(argv[1], "rules_seed");
        assert_eq!(argv[2], "--json");
        let input: serde_json::Value = serde_json::from_str(argv[3].to_str().unwrap()).unwrap();
        assert_eq!(input["repoRoot"], "/tmp/repo");
        assert_eq!(input["ruleId"], "no-console");
        assert_eq!(argv[4], "--force");
    }
}
