pub mod agents;
pub mod config;
pub mod embedded;
pub mod fsops;
pub mod harness;
pub mod preserve;
pub mod skills;

use std::env;
use std::ffi::OsString;
use std::path::{Component, Path, PathBuf};
use std::process::ExitCode;
#[cfg(unix)]
use std::{fs::File, io::Write, os::fd::AsRawFd};

use crate::migrate::{self, MigrateEnv, Report, ReportEntry, watch::CodeWatchHost};
use clap::builder::{PossibleValuesParser, ValueParser};
use clap::{Arg, ArgAction, Command};
use serde_json::json;
use varde_core::envelope;
use varde_workflow_core::memory::{load_config, save_config};

use self::harness::{Harness, HarnessId};

pub const SYNC_ABOUT: &str =
    "Preview with --dry-run, choose explicit targets, then apply skill and agent setup";
const RECOMMENDED_LAYOUT: &str = "Recommended layout: keep one canonical central copy (for example ~/.agents/skills and ~/.agents/agents, or a private Git repo) and symlink it into each detected harness's skill and agent directories.";

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum LinkMode {
    Symlink,
    Copy,
}

impl LinkMode {
    fn as_str(self) -> &'static str {
        match self {
            Self::Symlink => "symlink",
            Self::Copy => "copy",
        }
    }
}

#[derive(Clone, Debug)]
pub struct SyncContext {
    pub skills_dir: PathBuf,
    pub agents_dir: PathBuf,
    pub selected_skills: Option<Vec<String>>,
    pub link_mode: LinkMode,
    pub harnesses: Vec<Harness>,
    pub dry_run: bool,
    pub home: PathBuf,
}

fn parse_harnesses(value: &str) -> Result<Vec<HarnessId>, String> {
    if value == "none" {
        return Ok(Vec::new());
    }

    let mut ids = Vec::new();
    for item in value.split(',') {
        let id = item.parse::<HarnessId>()?;
        if !ids.contains(&id) {
            ids.push(id);
        }
    }
    Ok(ids)
}

fn parse_skill_selection(value: &str) -> Result<Vec<String>, String> {
    if value == "all" {
        return Ok(Vec::new());
    }
    let mut names = Vec::new();
    for name in value.split(',').map(str::trim) {
        if name.is_empty() {
            return Err(
                "skill names must not be empty; use --skills all to select every skill".into(),
            );
        }
        let name = name.to_string();
        if !names.contains(&name) {
            names.push(name);
        }
    }
    config::validate_skills(&names)?;
    Ok(names)
}

fn parse_preset(value: &str) -> Result<Vec<String>, String> {
    config::preset_skills(value)
}

fn command() -> Command {
    Command::new("varde setup sync")
        .about(SYNC_ABOUT)
        .after_help(format!("{RECOMMENDED_LAYOUT}\nSandbox denial can leave earlier targets installed; retry the denied target. Watcher registration can time out; check setup doctor afterward."))
        .disable_version_flag(true)
        .arg(
            Arg::new("skills-dir")
                .long("skills-dir")
                .value_name("DIR")
                .help("Canonical directory for installed skills"),
        )
        .arg(
            Arg::new("agents-dir")
                .long("agents-dir")
                .value_name("DIR")
                .help("Canonical directory for installed agents"),
        )
        .arg(
            Arg::new("link-mode")
                .long("link-mode")
                .value_name("MODE")
                .value_parser(PossibleValuesParser::new(["symlink", "copy"]))
                .help("Link mode to save and use (default: symlink)"),
        )
        .arg(
            Arg::new("skills")
                .long("skills")
                .value_name("NAMES")
                .value_parser(ValueParser::new(parse_skill_selection))
                .help("Comma-separated skill names to install (use all to reset to every skill)"),
        )
        .arg(
            Arg::new("preset")
                .long("preset")
                .value_name("NAME")
                .value_parser(ValueParser::new(parse_preset))
                .help(config::preset_help()),
        )
        .arg(
            Arg::new("harnesses")
                .long("harnesses")
                .value_name("IDS")
                .value_parser(ValueParser::new(parse_harnesses))
                .help("Comma-separated harness ids or none (default: detected)"),
        )
        .arg(
            Arg::new("dry-run")
                .long("dry-run")
                .action(ArgAction::SetTrue)
                .help("Print the resolved setup without saving settings"),
        )
        .arg(
            Arg::new("instructions-target")
                .long("instructions-target")
                .value_name("FILE")
                .action(ArgAction::Append)
                .help("Install the shared instruction block at this file (repeatable)"),
        )
        .arg(
            Arg::new("json")
                .long("json")
                .action(ArgAction::SetTrue)
                .help("Print the migration report in a machine-output envelope"),
        )
}

fn usage_error(message: impl AsRef<str>) -> ExitCode {
    eprintln!("{}\n{RECOMMENDED_LAYOUT}", message.as_ref());
    ExitCode::from(2)
}

fn absolute_path(path: &Path, cwd: &Path) -> PathBuf {
    let path = if path.is_absolute() {
        path.to_path_buf()
    } else {
        cwd.join(path)
    };
    let mut normalized = PathBuf::new();
    for component in path.components() {
        match component {
            Component::Prefix(prefix) => normalized.push(prefix.as_os_str()),
            Component::RootDir => normalized.push(component.as_os_str()),
            Component::CurDir => {}
            Component::ParentDir => {
                normalized.pop();
            }
            Component::Normal(part) => normalized.push(part),
        }
    }
    normalized
}

fn flag_path(value: &str, home: &Path, cwd: &Path) -> PathBuf {
    let path = value
        .strip_prefix("~/")
        .map(|relative| home.join(relative))
        .unwrap_or_else(|| PathBuf::from(value));
    absolute_path(&path, cwd)
}

fn home_directory() -> Result<PathBuf, String> {
    let home = env::var_os("HOME")
        .filter(|value| !value.is_empty())
        .or_else(|| env::var_os("USERPROFILE").filter(|value| !value.is_empty()))
        .ok_or_else(|| "could not determine the home directory".to_string())?;
    let cwd =
        env::current_dir().map_err(|error| format!("could not read current directory: {error}"))?;
    Ok(absolute_path(Path::new(&home), &cwd))
}

fn target_from_saved(path: &Path, cwd: &Path) -> PathBuf {
    absolute_path(path, cwd)
}

fn validate_target(flag: &str, path: &Path) -> Result<(), String> {
    if path.exists() && !path.is_dir() {
        return Err(format!(
            "{flag} target {} exists and is not a directory",
            path.display()
        ));
    }
    Ok(())
}

fn display_harnesses(harnesses: &[Harness]) -> String {
    let ids = harnesses
        .iter()
        .map(|harness| harness.id.as_str())
        .collect::<Vec<_>>();
    if ids.is_empty() {
        "none".to_string()
    } else {
        ids.join(", ")
    }
}

fn print_context(context: &SyncContext) {
    if context.dry_run {
        println!("would use skills target: {}", context.skills_dir.display());
        println!("would use agents target: {}", context.agents_dir.display());
        println!("would use link mode: {}", context.link_mode.as_str());
        println!(
            "would process harnesses: {}",
            display_harnesses(&context.harnesses)
        );
    } else {
        println!("skills target: {}", context.skills_dir.display());
        println!("agents target: {}", context.agents_dir.display());
        println!("link mode: {}", context.link_mode.as_str());
        println!("harnesses: {}", display_harnesses(&context.harnesses));
    }
}

#[cfg(unix)]
const STDOUT_FD: i32 = 1;

#[cfg(unix)]
struct StdoutSilencer(i32);

#[cfg(unix)]
unsafe extern "C" {
    fn dup(fd: i32) -> i32;
    fn dup2(source_fd: i32, target_fd: i32) -> i32;
    fn close(fd: i32) -> i32;
}

#[cfg(unix)]
impl StdoutSilencer {
    fn new() -> std::io::Result<Self> {
        std::io::stdout().flush()?;
        let null = File::open("/dev/null")?;
        // SAFETY: stdout is a valid process file descriptor and the duplicate is
        // retained until Drop restores it.
        let saved = unsafe { dup(STDOUT_FD) };
        if saved < 0 {
            return Err(std::io::Error::last_os_error());
        }
        // SAFETY: null owns a valid open descriptor for the duration of dup2.
        if unsafe { dup2(null.as_raw_fd(), STDOUT_FD) } < 0 {
            let error = std::io::Error::last_os_error();
            // SAFETY: saved is the valid descriptor returned by dup above.
            unsafe { close(saved) };
            return Err(error);
        }
        Ok(Self(saved))
    }
}

#[cfg(unix)]
impl Drop for StdoutSilencer {
    fn drop(&mut self) {
        let _ = std::io::stdout().flush();
        // SAFETY: saved is retained from dup until this Drop implementation.
        unsafe {
            dup2(self.0, STDOUT_FD);
            close(self.0);
        }
    }
}

fn install_targets(
    context: &SyncContext,
    json_output: bool,
) -> Result<std::collections::BTreeSet<&'static str>, String> {
    let relations = skills::skill_relations()?;
    let resolved = skills::resolve_selection(context, &relations)?;
    let features = resolved.features.clone();
    #[cfg(unix)]
    if json_output {
        let _silencer = StdoutSilencer::new()
            .map_err(|error| format!("could not prepare JSON output: {error}"))?;
        skills::run(context, resolved)?;
        agents::run(context)?;
        return Ok(features);
    }

    let _ = json_output;
    skills::run(context, resolved)?;
    agents::run(context)?;
    Ok(features)
}

pub fn run(args: Vec<OsString>) -> ExitCode {
    let mut args = args;
    if let Some(program) = args.first_mut() {
        *program = OsString::from("varde setup sync");
    } else {
        args.push(OsString::from("varde setup sync"));
    }
    let matches = match command().try_get_matches_from(args) {
        Ok(matches) => matches,
        Err(error) => {
            let code = error.exit_code().clamp(0, 255) as u8;
            let _ = error.print();
            return ExitCode::from(code);
        }
    };

    let mut stored_config = match load_config() {
        Ok(config) => config,
        Err(error) => {
            eprintln!("could not read varde config: {error}");
            return ExitCode::FAILURE;
        }
    };
    let aliases = config::deprecated_session_notes_aliases(&stored_config);
    if !aliases.is_empty() {
        eprintln!(
            "varde setup sync: deprecated aliases in use: {}",
            aliases.join("; ")
        );
    }
    let saved = match config::read(&stored_config) {
        Ok(saved) => saved,
        Err(error) => return usage_error(error),
    };
    let home = match home_directory() {
        Ok(home) => home,
        Err(error) => return usage_error(error),
    };
    let cwd = match env::current_dir() {
        Ok(cwd) => cwd,
        Err(error) => {
            eprintln!("could not read current directory: {error}");
            return ExitCode::FAILURE;
        }
    };

    let skills_dir = matches
        .get_one::<String>("skills-dir")
        .map(|value| flag_path(value, &home, &cwd))
        .or_else(|| {
            saved
                .skills_dir
                .as_deref()
                .map(|path| target_from_saved(path, &cwd))
        });
    let agents_dir = matches
        .get_one::<String>("agents-dir")
        .map(|value| flag_path(value, &home, &cwd))
        .or_else(|| {
            saved
                .agents_dir
                .as_deref()
                .map(|path| target_from_saved(path, &cwd))
        });
    let missing = [
        skills_dir.is_none().then_some("--skills-dir"),
        agents_dir.is_none().then_some("--agents-dir"),
    ]
    .into_iter()
    .flatten()
    .collect::<Vec<_>>();
    if !missing.is_empty() {
        return usage_error(format!(
            "missing required target{}: {}",
            if missing.len() == 1 { "" } else { "s" },
            missing.join(" and ")
        ));
    }
    let skills_dir = skills_dir.expect("checked above");
    let agents_dir = agents_dir.expect("checked above");
    if let Err(error) = validate_target("--skills-dir", &skills_dir) {
        return usage_error(error);
    }
    if let Err(error) = validate_target("--agents-dir", &agents_dir) {
        return usage_error(error);
    }

    let link_mode_name = matches
        .get_one::<String>("link-mode")
        .map(String::as_str)
        .or(saved.link_mode.as_deref())
        .unwrap_or("symlink");
    let link_mode = match link_mode_name {
        "symlink" => LinkMode::Symlink,
        "copy" => LinkMode::Copy,
        other => return usage_error(format!("invalid saved [sync].link_mode: {other}")),
    };
    let skills_flag = matches.get_one::<Vec<String>>("skills").cloned();
    let preset_flag = matches.get_one::<Vec<String>>("preset").cloned();
    let selected_skills = match (skills_flag, preset_flag) {
        (Some(skills), Some(preset)) => {
            // `--skills all` and the `full` preset both select empty, which
            // installs every skill and clears the saved selection.
            if skills.is_empty() || preset.is_empty() {
                Some(Vec::new())
            } else {
                let mut names = skills;
                for name in preset {
                    if !names.contains(&name) {
                        names.push(name);
                    }
                }
                Some(names)
            }
        }
        (Some(skills), None) => Some(skills),
        (None, Some(preset)) => Some(preset),
        (None, None) => saved.skills.clone(),
    };

    let pi_agent_dir = env::var_os("PI_CODING_AGENT_DIR")
        .filter(|value| !value.is_empty())
        .map(PathBuf::from);
    let harnesses = if let Some(ids) = matches.get_one::<Vec<HarnessId>>("harnesses") {
        harness::select(ids, &home, pi_agent_dir.as_deref())
    } else {
        harness::detect(&home, pi_agent_dir.as_deref())
    };
    let dry_run = matches.get_flag("dry-run");
    let json_output = matches.get_flag("json");
    let instruction_targets = matches
        .get_many::<String>("instructions-target")
        .into_iter()
        .flatten()
        .map(|target| flag_path(target, &home, &cwd))
        .collect::<Vec<_>>();
    let update_settings = matches.get_one::<String>("skills-dir").is_some()
        || matches.get_one::<String>("agents-dir").is_some()
        || matches.get_one::<String>("link-mode").is_some()
        || matches.get_one::<Vec<String>>("skills").is_some()
        || matches.get_one::<Vec<String>>("preset").is_some();

    if update_settings && !dry_run {
        config::write(
            &mut stored_config,
            &skills_dir,
            &agents_dir,
            link_mode.as_str(),
            selected_skills.as_deref(),
        );
        if let Err(error) = save_config(&stored_config) {
            eprintln!("could not save varde config: {error}");
            return ExitCode::FAILURE;
        }
    }

    let context = SyncContext {
        skills_dir,
        agents_dir,
        selected_skills,
        link_mode,
        harnesses,
        dry_run,
        home,
    };
    if !json_output {
        print_context(&context);
    }

    let migrate_env = MigrateEnv::current(dry_run);
    let mut report = Report::default();
    let mut watch_host = CodeWatchHost;
    let watch_state = migrate::watch::stop_for_move(&migrate_env, &mut watch_host, &mut report);

    // Pin before config_move so dry-run resolves the same marker-aware path
    // that a real run pins before the migration marker is written.
    migrate::harness::pin_toz_store(&migrate_env, &mut report);

    let mut hard_error = match migrate::config_move::run(
        &migrate_env,
        watch_state.code_store_movable,
        &mut report,
    ) {
        Ok(()) => None,
        Err(error) => {
            report.unrewritable.push(ReportEntry::new(
                &migrate_env.config_dir,
                format!("config migration failed: {error}"),
            ));
            Some(format!("config migration failed: {error}"))
        }
    };

    if hard_error.is_none() {
        let features = match install_targets(&context, json_output) {
            Ok(features) => Some(features),
            Err(error) => {
                hard_error = Some(error);
                None
            }
        };
        if let Some(features) = features {
            if !dry_run
                && let Err(error) =
                    config::seed_hooks(&varde_workflow_core::memory::config_path(), &features)
            {
                eprintln!("could not seed hook config: {error}");
                return ExitCode::FAILURE;
            }
            for harness in &context.harnesses {
                migrate::harness::rewrite_harness_with_features(
                    &migrate_env,
                    harness.id.as_str(),
                    &mut report,
                    Some(&features),
                );
            }
            let sections = [
                ("change", "orchestration"),
                ("toz", "toz"),
                ("learn", "learn"),
            ]
            .into_iter()
            .filter(|(feature, _)| features.contains(feature))
            .map(|(_, section)| section.to_owned())
            .collect::<Vec<_>>();
            migrate::harness::install_instructions(
                &migrate_env,
                &instruction_targets,
                &sections,
                &mut report,
            );
        }
    }

    migrate::watch::restart_after_move(
        &migrate_env,
        &mut watch_host,
        &watch_state.registered_repos,
        &mut report,
    );

    if hard_error.is_none() {
        for (path, command) in
            harness::remaining_legacy_hook_commands(&migrate_env, pi_agent_dir.as_deref())
        {
            report.skipped.push(
                ReportEntry::new(
                    path,
                    "legacy hook command remains and still references an installed binary",
                )
                .with_command(command),
            );
        }
        if let Err(error) = migrate::legacy_bins::run(&migrate_env, &mut report) {
            let message = format!("could not remove legacy Varde binaries: {error}");
            report.unrewritable.push(ReportEntry::new(
                migrate_env.cargo_install_root.join("bin"),
                &message,
            ));
            hard_error = Some(message);
        }
    }

    if dry_run {
        for entry in &mut report.would {
            if !entry.reason.starts_with("prediction:") {
                entry.reason = format!("prediction: {}", entry.reason);
            }
        }
    }

    let meta = json!({"dry_run": dry_run});
    let output = match &hard_error {
        Some(error) => envelope::negative_result("sync_failed", error, report.data(), meta),
        None => envelope::success(report.data(), meta),
    };
    if json_output {
        println!("{output}");
    } else {
        println!("{report}");
    }
    if let Some(error) = hard_error {
        eprintln!("{error}");
        ExitCode::FAILURE
    } else {
        ExitCode::SUCCESS
    }
}
