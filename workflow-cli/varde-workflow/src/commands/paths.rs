//! `varde-workflow paths`: show where working and knowledge memory resolve
//! for a project, and edit the user-scoped `paths.toml` that redirects
//! them. Skills call the show form to find the memory directories instead
//! of assuming `memory-bank/working` and `memory-bank/knowledge`.

use crate::cli::{PathsArgs, PathsCommand, PathsSetArgs, PathsUnsetArgs};
use crate::commands::error::{InternalError, report_error};
use crate::output::print_success;
use anyhow::Result;
use okf_core::memory::{self, Config, MemoryKind, MemoryPaths};
use serde_json::json;
use std::path::{Path, PathBuf};

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
        print_success(json!({
            "root": paths.root,
            "working": paths.working.path,
            "working_source": paths.working.source,
            "knowledge": paths.knowledge.path,
            "knowledge_source": paths.knowledge.source,
            "config": paths.config,
        }))
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
        println!("config: {}", paths.config.display());
        Ok(())
    }
}

fn set_paths(args: PathsSetArgs) -> Result<()> {
    if args.working.is_none() && args.knowledge.is_none() {
        return report_error(
            &InternalError("pass --working and/or --knowledge".into()),
            args.json,
        );
    }
    edit(args.default, args.project.as_deref(), args.json, |entry| {
        if let Some(working) = args.working.clone() {
            entry.set(MemoryKind::Working, Some(working));
        }
        if let Some(knowledge) = args.knowledge.clone() {
            entry.set(MemoryKind::Knowledge, Some(knowledge));
        }
    })
}

fn unset_paths(args: PathsUnsetArgs) -> Result<()> {
    if !args.working && !args.knowledge {
        return report_error(
            &InternalError("pass --working and/or --knowledge".into()),
            args.json,
        );
    }
    edit(args.default, args.project.as_deref(), args.json, |entry| {
        if args.working {
            entry.set(MemoryKind::Working, None);
        }
        if args.knowledge {
            entry.set(MemoryKind::Knowledge, None);
        }
    })
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
                print_success(json!({
                    "root": paths.root,
                    "working": paths.working.path,
                    "working_source": paths.working.source,
                    "knowledge": paths.knowledge.path,
                    "knowledge_source": paths.knowledge.source,
                    "config": config_path,
                }))
            } else {
                println!("updated {}", config_path.display());
                println!("working: {}", paths.working.path.display());
                println!("knowledge: {}", paths.knowledge.path.display());
                Ok(())
            }
        }
        None => {
            if json {
                print_success(json!({
                    "default": {
                        "working": config.default.working,
                        "knowledge": config.default.knowledge,
                    },
                    "config": config_path,
                }))
            } else {
                println!("updated {}", config_path.display());
                Ok(())
            }
        }
    }
}

/// `--project` when given, else the nearest `memory-bank/` ancestor of the
/// current directory, else the current directory itself (so `paths set`
/// works before a project has any memory bank at all).
fn project_root(project: Option<&Path>) -> Result<PathBuf> {
    let root = match project {
        Some(path) => path.to_path_buf(),
        None => {
            let cwd = std::env::current_dir()?;
            memory::find_root(&cwd).unwrap_or(cwd)
        }
    };
    Ok(memory::canonical_or_lexical(&root))
}
