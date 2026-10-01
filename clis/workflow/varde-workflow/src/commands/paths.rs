//! `varde-workflow paths`: show where memory resolves and edit the user-scoped
//! `config.toml` that redirects it. The learn store is global; working and
//! knowledge can also be redirected per project.

use crate::cli::{PathsArgs, PathsCommand, PathsSetArgs, PathsUnsetArgs};
use crate::commands::error::{InternalError, report_error};
use crate::output::print_success;
use anyhow::Result;
use serde_json::json;
use std::path::{Path, PathBuf};
use varde_workflow_core::memory::{self, Config, MemoryKind, MemoryPaths};

pub fn run(args: PathsArgs) -> Result<()> {
    match args.command {
        None => show(args.project.as_deref(), args.json),
        Some(PathsCommand::Set(set)) => set_paths(set),
        Some(PathsCommand::Unset(unset)) => unset_paths(unset),
    }
}

fn show(project: Option<&Path>, json: bool) -> Result<()> {
    let root = match project_root(project) {
        Ok(root) => root,
        Err(error) => return report_error(&InternalError(error.to_string()), json),
    };
    let paths = match MemoryPaths::resolve(&root) {
        Ok(paths) => paths,
        Err(error) => return report_error(&InternalError(error.to_string()), json),
    };
    if json {
        let mut data = resolved_paths_data(&paths, &paths.config);
        report_ignored_legacy(&mut data);
        print_success(data)
    } else {
        println!("root: {}", paths.root.display());
        println!(
            "working: {} ({})",
            paths.working.path.display(),
            paths.working.source
        );
        println!(
            "knowledge: {} ({})",
            paths.knowledge.path.display(),
            paths.knowledge.source
        );
        println!(
            "learn: {} ({})",
            paths.learn.path.display(),
            paths.learn.source
        );
        match &paths.toz {
            Some(toz) => println!("toz: {} ({})", toz.path.display(), toz.source),
            None => println!("toz: (unset)"),
        }
        println!("config: {}", paths.config.display());
        Ok(())
    }
}

fn set_paths(args: PathsSetArgs) -> Result<()> {
    if args.working.is_none()
        && args.knowledge.is_none()
        && args.toz.is_none()
        && args.learn.is_none()
    {
        return report_error(
            &InternalError("pass --working, --knowledge, --toz, and/or --learn".into()),
            args.json,
        );
    }
    if args
        .learn
        .as_deref()
        .is_some_and(|path| path.trim().is_empty())
    {
        return report_error(
            &InternalError("--learn must be a non-empty path".into()),
            args.json,
        );
    }
    if args.learn.is_some()
        && !args.default
        && (args.working.is_some() || args.knowledge.is_some() || args.toz.is_some())
    {
        return report_error(
            &InternalError("combine --learn with other path options only with --default".into()),
            args.json,
        );
    }
    edit(
        args.default || args.learn.is_some(),
        args.project.as_deref(),
        args.json,
        |entry| {
            if let Some(working) = args.working.clone() {
                entry.set(MemoryKind::Working, Some(working));
            }
            if let Some(knowledge) = args.knowledge.clone() {
                entry.set(MemoryKind::Knowledge, Some(knowledge));
            }
            if let Some(toz) = args.toz.clone() {
                entry.toz = Some(toz);
            }
            if let Some(learn) = args.learn.clone() {
                entry.learn = Some(learn);
            }
        },
    )
}

fn unset_paths(args: PathsUnsetArgs) -> Result<()> {
    if !args.working && !args.knowledge && !args.toz && !args.learn {
        return report_error(
            &InternalError("pass --working, --knowledge, --toz, and/or --learn".into()),
            args.json,
        );
    }
    if args.learn && !args.default && (args.working || args.knowledge || args.toz) {
        return report_error(
            &InternalError("combine --learn with other path options only with --default".into()),
            args.json,
        );
    }
    edit(
        args.default || args.learn,
        args.project.as_deref(),
        args.json,
        |entry| {
            if args.working {
                entry.set(MemoryKind::Working, None);
            }
            if args.knowledge {
                entry.set(MemoryKind::Knowledge, None);
            }
            if args.toz {
                entry.toz = None;
            }
            if args.learn {
                entry.learn = None;
            }
        },
    )
}

fn edit(
    default: bool,
    project: Option<&Path>,
    json: bool,
    apply: impl FnOnce(&mut memory::Entry),
) -> Result<()> {
    let mut config = match memory::load_config() {
        Ok(config) => config,
        Err(error) => return report_error(&InternalError(error.to_string()), json),
    };
    let root = if default {
        None
    } else {
        match project_root(project) {
            Ok(root) => Some(root),
            Err(error) => return report_error(&InternalError(error.to_string()), json),
        }
    };
    let entry = match &root {
        None => &mut config.default,
        Some(root) => config.project_entry_mut(root),
    };
    apply(entry);
    config.prune();
    match memory::save_config(&config) {
        Ok(path) => finish(&config, root.as_deref(), path, json),
        Err(error) => report_error(&InternalError(error.to_string()), json),
    }
}

fn finish(config: &Config, root: Option<&Path>, config_path: PathBuf, json: bool) -> Result<()> {
    match root {
        Some(root) => {
            let paths = MemoryPaths::resolve_with(root, config)
                .map_err(|error| anyhow::anyhow!(error.to_string()))?;
            if json {
                let mut data = resolved_paths_data(&paths, &config_path);
                report_ignored_legacy(&mut data);
                print_success(data)
            } else {
                println!("updated {}", config_path.display());
                println!("working: {}", paths.working.path.display());
                println!("knowledge: {}", paths.knowledge.path.display());
                println!("learn: {}", paths.learn.path.display());
                match &paths.toz {
                    Some(toz) => println!("toz: {}", toz.path.display()),
                    None => println!("toz: (unset)"),
                }
                Ok(())
            }
        }
        None => {
            if json {
                let mut data = json!({
                    "default": {
                        "working": config.default.working,
                        "knowledge": config.default.knowledge,
                        "toz": config.default.toz,
                        "learn": config.default.learn,
                    },
                    "config": config_path,
                });
                report_ignored_legacy(&mut data);
                print_success(data)
            } else {
                println!("updated {}", config_path.display());
                Ok(())
            }
        }
    }
}

fn resolved_paths_data(paths: &MemoryPaths, config: &Path) -> serde_json::Value {
    json!({
        "root": paths.root,
        "working": paths.working.path,
        "working_source": paths.working.source,
        "knowledge": paths.knowledge.path,
        "knowledge_source": paths.knowledge.source,
        "learn": paths.learn.path,
        "learn_source": paths.learn.source,
        "toz": paths.toz.as_ref().map(|resolved| &resolved.path),
        "toz_source": paths.toz.as_ref().map(|resolved| resolved.source.to_string()),
        "config": config,
    })
}

fn report_ignored_legacy(data: &mut serde_json::Value) {
    let legacy = memory::legacy_config_path();
    if memory::config_path().exists() && legacy.exists() {
        data["ignored_legacy_config"] = json!(legacy);
    }
}

/// `--project` when given, else `memory::find_root`'s chain from the current
/// directory (main Git repository root, then a configured project, then a
/// `memory-bank/` ancestor), else the current directory itself
/// (so `paths set` works before a project has any memory bank at all).
fn project_root(project: Option<&Path>) -> Result<PathBuf> {
    let root = match project {
        Some(path) => path.to_path_buf(),
        None => {
            let cwd = std::env::current_dir()?;
            memory::find_root(&cwd).unwrap_or(cwd)
        }
    };
    Ok(memory::repository_memory_root(&root))
}
