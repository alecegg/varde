//! Move the default code and toz stores into the varde config tree.

use super::{MigrateEnv, Report, ReportEntry};
use serde_json::Value;
use std::fs::{self, OpenOptions};
use std::io::{self, Write};
use std::path::{Component, Path, PathBuf};
use std::process::Command;
use std::time::{SystemTime, UNIX_EPOCH};

const MARKER: &str = ".varde-migration-complete";
const PATHS_COMMAND: &str = "varde setup paths --json";

struct StoreOutcome {
    marker_ready: bool,
    source_names: Vec<PathBuf>,
}

/// Move the default stores. `code_store_movable` is supplied by the watcher
/// migration step; a false value skips code and still processes toz.
pub fn run(env: &MigrateEnv, code_store_movable: bool, report: &mut Report) -> io::Result<()> {
    let code_source = env.home.join(".config/varde-code");
    if code_store_movable {
        migrate_store(
            env,
            &code_source,
            std::slice::from_ref(&code_source),
            &env.config_dir.join("code"),
            "code",
            report,
        )?;
    } else {
        report.skipped.push(ReportEntry::new(
            code_source,
            "code store skipped because the watcher gate is unsafe",
        ));
    }

    let base = env
        .xdg_config_home
        .as_deref()
        .filter(|path| !path.as_os_str().is_empty())
        .map(Path::to_path_buf)
        .unwrap_or_else(|| env.home.join(".config"));
    let tool_output_zone = base.join("tool-output-zone");
    let varde_toz = base.join("varde-toz");
    let tool_exists = path_exists(&tool_output_zone);
    let varde_exists = path_exists(&varde_toz);
    let same_root = roots_are_same(&tool_output_zone, &varde_toz);
    let distinct_roots = tool_exists && varde_exists && !same_root;
    let selected = if tool_exists && !same_root {
        &tool_output_zone
    } else {
        &varde_toz
    };
    if distinct_roots {
        let unselected = if selected == &tool_output_zone {
            &varde_toz
        } else {
            &tool_output_zone
        };
        report.skipped.push(ReportEntry::new(
            unselected,
            "distinct toz store root was left in place; a later sync can migrate it after the selected store",
        ));
    }

    let toz_target = env.config_dir.join("toz");
    if env
        .toz_config_override
        .as_deref()
        .is_some_and(|override_path| same_path(override_path, selected))
    {
        report.skipped.push(ReportEntry::new(
            selected,
            "explicit toz config override is never moved",
        ));
        return Ok(());
    }

    let outcome = migrate_store(
        env,
        selected,
        &[tool_output_zone.clone(), varde_toz.clone()],
        &toz_target,
        "toz",
        report,
    )?;
    if outcome.marker_ready {
        rewrite_saved_toz_paths(env, &outcome.source_names, &toz_target, report);
    }
    Ok(())
}

fn migrate_store(
    env: &MigrateEnv,
    requested_source: &Path,
    legacy_alias_candidates: &[PathBuf],
    target: &Path,
    module: &str,
    report: &mut Report,
) -> io::Result<StoreOutcome> {
    let marker = target.join(MARKER);
    let marker_present = path_exists(&marker);
    let partial = partial_path(target);
    if path_exists(&partial) {
        if env.dry_run {
            would(
                report,
                &partial,
                "clean abandoned partial migration data before retry",
            );
        } else {
            discard_partial(&partial)?;
        }
    }
    let source_exists = path_exists(requested_source);
    let canonical_source = if source_exists {
        match fs::canonicalize(requested_source) {
            Ok(path) => Some(path),
            Err(error) => {
                report.unrewritable.push(ReportEntry::new(
                    requested_source,
                    format!("could not resolve the legacy root: {error}"),
                ));
                return Ok(StoreOutcome {
                    marker_ready: marker_present,
                    source_names: vec![requested_source.to_path_buf()],
                });
            }
        }
    } else {
        None
    };

    let mut source_names = vec![requested_source.to_path_buf()];
    if let Some(source) = &canonical_source {
        if !source_names.contains(source) {
            source_names.push(source.clone());
        }
        for alias in legacy_alias_candidates {
            if fs::canonicalize(alias).ok().as_ref() == Some(source)
                && !source_names.contains(alias)
            {
                source_names.push(alias.clone());
            }
        }
        if !fs::metadata(source)?.is_dir() {
            report.unrewritable.push(ReportEntry::new(
                requested_source,
                "legacy root exists but is not a directory",
            ));
            return Ok(StoreOutcome {
                marker_ready: marker_present,
                source_names,
            });
        }
        if same_path(source, target) {
            if !marker_present {
                if env.dry_run {
                    would(report, &marker, "write the empty migration marker");
                } else {
                    write_marker(target)?;
                    report.moved.push(ReportEntry::new(
                        marker,
                        format!("marked the existing {module} store as migrated"),
                    ));
                }
            }
            return Ok(StoreOutcome {
                marker_ready: true,
                source_names,
            });
        }
    }

    if !source_exists {
        if !marker_present {
            if env.dry_run {
                would(
                    report,
                    &marker,
                    "write the empty migration marker after an absent source",
                );
            } else {
                write_marker(target)?;
                report.moved.push(ReportEntry::new(
                    marker,
                    format!("marked the absent {module} store as migrated"),
                ));
            }
        }
        return Ok(StoreOutcome {
            marker_ready: true,
            source_names,
        });
    }

    let source = canonical_source.expect("existing source was canonicalized");
    let target_exists = path_exists(target);
    if target_exists && !fs::metadata(target)?.is_dir() {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            format!("migration target {} is not a directory", target.display()),
        ));
    }

    let cache_wins = module == "code";
    let conflicts = if target_exists {
        find_conflicts(&source, target, Path::new(""), cache_wins)?
    } else {
        Vec::new()
    };
    if !marker_present && !conflicts.is_empty() {
        for relative in conflicts {
            let source_path = source.join(&relative);
            report.unrewritable.push(ReportEntry::new(
                &source_path,
                format!(
                    "collision with {}; the complete legacy root was left untouched",
                    target.join(relative).display()
                ),
            ));
        }
        return Ok(StoreOutcome {
            marker_ready: false,
            source_names,
        });
    }

    let aliases = symlink_aliases(legacy_alias_candidates, &source);
    if env.dry_run {
        if target_exists {
            preview_merge(&source, target, Path::new(""), cache_wins, report)?;
        } else {
            would(report, target, &format!("rename the legacy {module} root"));
        }
        for alias in aliases {
            would(
                report,
                &alias,
                "remove the legacy symlink after its target moves",
            );
        }
        if !marker_present {
            would(report, &marker, "write the empty migration marker");
        }
        return Ok(StoreOutcome {
            marker_ready: true,
            source_names,
        });
    }

    if !target_exists {
        create_parent(target)?;
        match fs::rename(&source, target) {
            Ok(()) => report.moved.push(ReportEntry::new(
                target,
                format!("moved the legacy {module} root"),
            )),
            Err(error) if is_cross_device(&error) => {
                stage_and_rename(&source, target)?;
                report.moved.push(ReportEntry::new(
                    target,
                    format!("moved the legacy {module} root through a complete staged copy"),
                ));
            }
            Err(error) => return Err(error),
        }
    } else if crosses_device(&source, target)? {
        merge_through_stage(&source, target, module, cache_wins, report)?;
    } else {
        let mut consumed = Vec::new();
        let conflicts = merge_directory(
            &source,
            target,
            Path::new(""),
            module,
            cache_wins,
            false,
            report,
            &mut consumed,
        )?;
        if conflicts {
            prune_empty_directories(&source)?;
        }
    }

    let remains = path_exists(&source);
    if !remains {
        for alias in aliases {
            if path_exists(&alias) {
                fs::remove_file(&alias)?;
                report.moved.push(ReportEntry::new(
                    alias,
                    "removed a legacy symlink that pointed to the moved store",
                ));
            }
        }
    }

    if !marker_present {
        write_marker(target)?;
        report.moved.push(ReportEntry::new(
            marker,
            format!("wrote the empty {module} migration marker"),
        ));
    }
    Ok(StoreOutcome {
        marker_ready: true,
        source_names,
    })
}

fn find_conflicts(
    source: &Path,
    target: &Path,
    relative: &Path,
    cache_wins: bool,
) -> io::Result<Vec<PathBuf>> {
    let mut conflicts = Vec::new();
    for entry in fs::read_dir(source)? {
        let entry = entry?;
        let source_path = entry.path();
        let target_path = target.join(entry.file_name());
        let child_relative = relative.join(entry.file_name());
        if !path_exists(&target_path) {
            continue;
        }
        let source_dir = is_real_directory(&source_path)?;
        let target_dir = is_real_directory(&target_path)?;
        if source_dir && target_dir {
            conflicts.extend(find_conflicts(
                &source_path,
                &target_path,
                &child_relative,
                cache_wins,
            )?);
        } else if cache_wins && is_code_cache(&child_relative) {
            continue;
        } else if !identical_leaf(&source_path, &target_path)? {
            conflicts.push(child_relative);
        }
    }
    Ok(conflicts)
}

fn preview_merge(
    source: &Path,
    target: &Path,
    relative: &Path,
    cache_wins: bool,
    report: &mut Report,
) -> io::Result<()> {
    for entry in fs::read_dir(source)? {
        let entry = entry?;
        let source_path = entry.path();
        let target_path = target.join(entry.file_name());
        let child_relative = relative.join(entry.file_name());
        if !path_exists(&target_path) {
            would(
                report,
                &target_path,
                "move an absent legacy entry into the target",
            );
        } else if is_real_directory(&source_path)? && is_real_directory(&target_path)? {
            preview_merge(
                &source_path,
                &target_path,
                &child_relative,
                cache_wins,
                report,
            )?;
        } else if cache_wins && is_code_cache(&child_relative) {
            would(
                report,
                &source_path,
                "discard the legacy cache because the target wins",
            );
        } else if identical_leaf(&source_path, &target_path)? {
            would(
                report,
                &source_path,
                "keep the identical target entry and remove its duplicate",
            );
        } else {
            report.unrewritable.push(ReportEntry::new(
                source_path,
                format!(
                    "different target entry at {}; the legacy copy would be left for recovery",
                    target_path.display()
                ),
            ));
        }
    }
    Ok(())
}

fn merge_through_stage(
    source: &Path,
    target: &Path,
    module: &str,
    cache_wins: bool,
    report: &mut Report,
) -> io::Result<()> {
    let partial = partial_path(target);
    discard_partial(&partial)?;
    if let Err(error) = copy_directory(source, &partial) {
        let _ = remove_path(&partial);
        return Err(error);
    }

    let mut consumed = Vec::new();
    let merge = merge_directory(
        &partial,
        target,
        Path::new(""),
        module,
        cache_wins,
        true,
        report,
        &mut consumed,
    );
    if let Err(error) = merge {
        let _ = remove_path(&partial);
        return Err(error);
    }
    for relative in consumed {
        let original = source.join(relative);
        if path_exists(&original) {
            remove_path(&original)?;
        }
    }
    prune_empty_directories(source)?;
    if path_exists(&partial) {
        remove_path(&partial)?;
    }
    Ok(())
}

#[allow(clippy::too_many_arguments)]
fn merge_directory(
    source: &Path,
    target: &Path,
    relative: &Path,
    module: &str,
    cache_wins: bool,
    staged: bool,
    report: &mut Report,
    consumed: &mut Vec<PathBuf>,
) -> io::Result<bool> {
    let mut conflicts = false;
    for entry in fs::read_dir(source)? {
        let entry = entry?;
        let source_path = entry.path();
        let target_path = target.join(entry.file_name());
        let child_relative = relative.join(entry.file_name());
        if !path_exists(&target_path) {
            let leaves = if staged {
                collect_leaf_paths(&source_path, &child_relative)?
            } else {
                Vec::new()
            };
            if staged {
                move_staged_entry(&source_path, &target_path)?;
            } else {
                fs::rename(&source_path, &target_path)?;
            }
            report.moved.push(ReportEntry::new(
                &target_path,
                format!("moved a legacy {module} entry"),
            ));
            consumed.extend(leaves);
        } else if is_real_directory(&source_path)? && is_real_directory(&target_path)? {
            conflicts |= merge_directory(
                &source_path,
                &target_path,
                &child_relative,
                module,
                cache_wins,
                staged,
                report,
                consumed,
            )?;
        } else if cache_wins && is_code_cache(&child_relative) {
            remove_path(&source_path)?;
            if staged {
                consumed.push(child_relative);
            }
            report.skipped.push(ReportEntry::new(
                &source_path,
                "discarded the legacy code cache because the target copy wins",
            ));
        } else if identical_leaf(&source_path, &target_path)? {
            remove_path(&source_path)?;
            if staged {
                consumed.push(child_relative);
            }
            report.skipped.push(ReportEntry::new(
                &source_path,
                "kept the identical target entry once",
            ));
        } else {
            conflicts = true;
            report.unrewritable.push(ReportEntry::new(
                &source_path,
                format!(
                    "different target entry at {}; left the legacy copy for recovery",
                    target_path.display()
                ),
            ));
        }
    }
    if directory_is_empty(source)? {
        fs::remove_dir(source)?;
    }
    Ok(conflicts)
}

fn move_staged_entry(source: &Path, target: &Path) -> io::Result<()> {
    match fs::rename(source, target) {
        Ok(()) => Ok(()),
        Err(error) if is_cross_device(&error) => {
            copy_path(source, target)?;
            remove_path(source)
        }
        Err(error) => Err(error),
    }
}

fn collect_leaf_paths(path: &Path, relative: &Path) -> io::Result<Vec<PathBuf>> {
    if is_real_directory(path)? {
        let mut leaves = Vec::new();
        for entry in fs::read_dir(path)? {
            let entry = entry?;
            leaves.extend(collect_leaf_paths(
                &entry.path(),
                &relative.join(entry.file_name()),
            )?);
        }
        Ok(leaves)
    } else {
        Ok(vec![relative.to_path_buf()])
    }
}

fn copy_directory(source: &Path, target: &Path) -> io::Result<()> {
    fs::create_dir(target)?;
    for entry in fs::read_dir(source)? {
        let entry = entry?;
        copy_path(&entry.path(), &target.join(entry.file_name()))?;
    }
    fs::set_permissions(target, fs::metadata(source)?.permissions())
}

fn copy_path(source: &Path, target: &Path) -> io::Result<()> {
    let metadata = fs::symlink_metadata(source)?;
    if metadata.file_type().is_symlink() {
        let link = fs::read_link(source)?;
        create_symlink(
            &link,
            target,
            fs::metadata(source)
                .map(|meta| meta.is_dir())
                .unwrap_or(false),
        )
    } else if metadata.is_dir() {
        copy_directory(source, target)
    } else {
        fs::copy(source, target).map(|_| ())
    }
}

#[cfg(unix)]
fn create_symlink(source: &Path, target: &Path, _directory: bool) -> io::Result<()> {
    std::os::unix::fs::symlink(source, target)
}

#[cfg(windows)]
fn create_symlink(source: &Path, target: &Path, directory: bool) -> io::Result<()> {
    if directory {
        std::os::windows::fs::symlink_dir(source, target)
    } else {
        std::os::windows::fs::symlink_file(source, target)
    }
}

#[cfg(not(any(unix, windows)))]
fn create_symlink(_source: &Path, _target: &Path, _directory: bool) -> io::Result<()> {
    Err(io::Error::new(
        io::ErrorKind::Unsupported,
        "symbolic links are not supported on this platform",
    ))
}

fn identical_leaf(source: &Path, target: &Path) -> io::Result<bool> {
    let source_meta = fs::symlink_metadata(source)?;
    let target_meta = fs::symlink_metadata(target)?;
    if source_meta.file_type().is_symlink() || target_meta.file_type().is_symlink() {
        return if source_meta.file_type().is_symlink() && target_meta.file_type().is_symlink() {
            Ok(fs::read_link(source)? == fs::read_link(target)?)
        } else {
            Ok(false)
        };
    }
    if source_meta.is_file() && target_meta.is_file() {
        return Ok(fs::read(source)? == fs::read(target)?);
    }
    Ok(source_meta.is_dir() && target_meta.is_dir())
}

fn is_code_cache(path: &Path) -> bool {
    let mut components = path.components();
    matches!(
        (components.next(), components.next(), components.next(), components.next()),
        (
            Some(Component::Normal(repos)),
            Some(Component::Normal(_)),
            Some(Component::Normal(index_db)),
            None
        ) if repos == "repos" && index_db == "index.db"
    )
}

fn is_real_directory(path: &Path) -> io::Result<bool> {
    Ok(fs::symlink_metadata(path)?.file_type().is_dir())
}

fn directory_is_empty(path: &Path) -> io::Result<bool> {
    Ok(fs::read_dir(path)?.next().is_none())
}

fn prune_empty_directories(root: &Path) -> io::Result<()> {
    if !is_real_directory(root)? {
        return Ok(());
    }
    for entry in fs::read_dir(root)? {
        let path = entry?.path();
        if is_real_directory(&path)? {
            prune_empty_directories(&path)?;
        }
    }
    if directory_is_empty(root)? {
        fs::remove_dir(root)?;
    }
    Ok(())
}

fn stage_and_rename(source: &Path, target: &Path) -> io::Result<()> {
    let partial = partial_path(target);
    discard_partial(&partial)?;
    if let Err(error) = copy_directory(source, &partial) {
        let _ = remove_path(&partial);
        return Err(error);
    }
    if let Err(error) = fs::rename(&partial, target) {
        let _ = remove_path(&partial);
        return Err(error);
    }
    remove_path(source)
}

fn partial_path(target: &Path) -> PathBuf {
    let name = target
        .file_name()
        .map(|name| name.to_string_lossy().into_owned())
        .unwrap_or_else(|| "store".to_string());
    target.with_file_name(format!("{name}.partial"))
}

fn discard_partial(path: &Path) -> io::Result<()> {
    if path_exists(path) {
        remove_path(path)?;
    }
    Ok(())
}

fn remove_path(path: &Path) -> io::Result<()> {
    if !path_exists(path) {
        return Ok(());
    }
    let metadata = fs::symlink_metadata(path)?;
    if metadata.file_type().is_dir() {
        fs::remove_dir_all(path)
    } else {
        fs::remove_file(path)
    }
}

fn create_parent(path: &Path) -> io::Result<()> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    Ok(())
}

fn write_marker(target: &Path) -> io::Result<()> {
    fs::create_dir_all(target)?;
    let marker = target.join(MARKER);
    if path_exists(&marker) {
        return Ok(());
    }
    let suffix = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos();
    let temp = target.join(format!("{MARKER}.tmp.{}.{}", std::process::id(), suffix));
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&temp)?;
    if let Err(error) = file.flush().and_then(|()| file.sync_all()) {
        drop(file);
        let _ = fs::remove_file(&temp);
        return Err(error);
    }
    drop(file);
    if let Err(error) = fs::rename(&temp, &marker) {
        let _ = fs::remove_file(&temp);
        return Err(error);
    }
    Ok(())
}

fn crosses_device(source: &Path, target: &Path) -> io::Result<bool> {
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        let source_device = fs::metadata(source)?.dev();
        let mut ancestor = target.to_path_buf();
        while !path_exists(&ancestor) {
            if !ancestor.pop() {
                return Ok(false);
            }
        }
        Ok(fs::metadata(ancestor)?.dev() != source_device)
    }
    #[cfg(not(unix))]
    {
        let _ = (source, target);
        // Staging first keeps the whole legacy tree intact until the merge
        // completes on platforms without a portable device-id query.
        Ok(true)
    }
}

#[cfg(unix)]
fn is_cross_device(error: &io::Error) -> bool {
    error.raw_os_error() == Some(18) // EXDEV
}

#[cfg(windows)]
fn is_cross_device(error: &io::Error) -> bool {
    error.raw_os_error() == Some(17) // ERROR_NOT_SAME_DEVICE
}

#[cfg(not(any(unix, windows)))]
fn is_cross_device(_error: &io::Error) -> bool {
    false
}

fn roots_are_same(first: &Path, second: &Path) -> bool {
    path_exists(first) && path_exists(second) && same_path(first, second)
}

fn same_path(first: &Path, second: &Path) -> bool {
    normalized_path(first) == normalized_path(second)
}

fn normalized_path(path: &Path) -> PathBuf {
    if let Ok(canonical) = fs::canonicalize(path) {
        return canonical;
    }
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

fn path_exists(path: &Path) -> bool {
    fs::symlink_metadata(path).is_ok()
}

fn symlink_aliases(candidates: &[PathBuf], source: &Path) -> Vec<PathBuf> {
    candidates
        .iter()
        .filter(|candidate| {
            fs::symlink_metadata(candidate)
                .map(|meta| meta.file_type().is_symlink())
                .unwrap_or(false)
                && fs::canonicalize(candidate)
                    .map(|path| path == source)
                    .unwrap_or(false)
        })
        .cloned()
        .collect()
}

fn would(report: &mut Report, path: &Path, action: &str) {
    report.would.push(ReportEntry::new(
        path,
        format!("prediction: would {action}"),
    ));
}

fn rewrite_saved_toz_paths(
    env: &MigrateEnv,
    source_names: &[PathBuf],
    target: &Path,
    report: &mut Report,
) {
    let (config_path, current_root) = match workflow_config_path(env) {
        Ok(paths) => paths,
        Err(error) => {
            report.unrewritable.push(
                ReportEntry::new(
                    env.config_dir.join("config.toml"),
                    format!("could not read the config path from the workflow paths API: {error}"),
                )
                .with_command(PATHS_COMMAND),
            );
            return;
        }
    };
    let text = match fs::read_to_string(&config_path) {
        Ok(text) => text,
        Err(error) if error.kind() == io::ErrorKind::NotFound => return,
        Err(error) => {
            report.unrewritable.push(
                ReportEntry::new(
                    &config_path,
                    format!("could not read saved toz paths: {error}"),
                )
                .with_command(PATHS_COMMAND),
            );
            return;
        }
    };
    let mut document: toml::Value = match toml::from_str(&text) {
        Ok(value) => value,
        Err(error) => {
            report.unrewritable.push(
                ReportEntry::new(
                    &config_path,
                    format!("could not parse saved toz paths: {error}"),
                )
                .with_command(PATHS_COMMAND),
            );
            return;
        }
    };

    let mut changed = false;
    let project_roots = document
        .get("project")
        .and_then(toml::Value::as_table)
        .map(|table| table.keys().map(PathBuf::from).collect::<Vec<_>>())
        .unwrap_or_default();
    let mut default_contexts = project_roots;
    if let Some(root) = current_root {
        default_contexts.push(root);
    }
    if let Some(default) = document
        .get_mut("default")
        .and_then(toml::Value::as_table_mut)
        && setting_matches_contexts(
            default.get("toz"),
            &default_contexts,
            &env.home,
            source_names,
        )
    {
        default.insert(
            "toz".into(),
            toml::Value::String(target.to_string_lossy().into_owned()),
        );
        changed = true;
    }
    if let Some(projects) = document
        .get_mut("project")
        .and_then(toml::Value::as_table_mut)
    {
        for (project, entry) in projects {
            let context = Path::new(project);
            if let Some(table) = entry.as_table_mut()
                && setting_matches(table.get("toz"), Some(context), &env.home, source_names)
            {
                table.insert(
                    "toz".into(),
                    toml::Value::String(target.to_string_lossy().into_owned()),
                );
                changed = true;
            }
        }
    }
    if !changed {
        return;
    }
    if env.dry_run {
        would(
            report,
            &config_path,
            "rewrite saved toz settings to the migrated store",
        );
        return;
    }
    let updated = match toml::to_string_pretty(&document) {
        Ok(fresh) => varde_workflow_core::memory::merge_toml_text(&text, &fresh),
        Err(error) => {
            report.unrewritable.push(
                ReportEntry::new(
                    &config_path,
                    format!("could not serialize saved toz paths: {error}"),
                )
                .with_command(PATHS_COMMAND),
            );
            return;
        }
    };
    if let Err(error) = write_atomic(&config_path, updated.as_bytes()) {
        report.unrewritable.push(
            ReportEntry::new(
                &config_path,
                format!("could not write migrated toz paths: {error}"),
            )
            .with_command(PATHS_COMMAND),
        );
        return;
    }
    report.moved.push(
        ReportEntry::new(
            &config_path,
            "rewrote saved toz paths to the migrated store",
        )
        .with_command(PATHS_COMMAND),
    );
}

fn workflow_config_path(env: &MigrateEnv) -> io::Result<(PathBuf, Option<PathBuf>)> {
    let mut command = Command::new(&env.exe);
    command
        .args(["setup", "paths", "--json"])
        .env_clear()
        .env("HOME", &env.home)
        .env("PATH", &env.path)
        .env("VARDE_CONFIG_DIR", &env.config_dir);
    if let Some(xdg_config_home) = &env.xdg_config_home {
        command.env("XDG_CONFIG_HOME", xdg_config_home);
    }
    let output = command.output()?;
    if !output.status.success() {
        return Err(io::Error::other(format!(
            "{PATHS_COMMAND} exited with {}: {}",
            output.status,
            String::from_utf8_lossy(&output.stderr).trim()
        )));
    }
    let envelope: Value = serde_json::from_slice(&output.stdout).map_err(|error| {
        io::Error::new(
            io::ErrorKind::InvalidData,
            format!("invalid paths response: {error}"),
        )
    })?;
    if envelope["ok"] != true {
        return Err(io::Error::other(format!(
            "{PATHS_COMMAND} returned an error: {}",
            envelope["data"]["error"]["message"]
        )));
    }
    let data = &envelope["data"];
    let config = data["config"].as_str().ok_or_else(|| {
        io::Error::new(
            io::ErrorKind::InvalidData,
            "paths response did not contain config",
        )
    })?;
    let current_root = data["root"].as_str().map(PathBuf::from);
    Ok((PathBuf::from(config), current_root))
}

fn setting_matches_contexts(
    value: Option<&toml::Value>,
    contexts: &[PathBuf],
    home: &Path,
    source_names: &[PathBuf],
) -> bool {
    let Some(value) = value.and_then(toml::Value::as_str) else {
        return false;
    };
    contexts.is_empty() && setting_path_matches(value, None, home, source_names)
        || contexts
            .iter()
            .any(|context| setting_path_matches(value, Some(context), home, source_names))
}

fn setting_matches(
    value: Option<&toml::Value>,
    project: Option<&Path>,
    home: &Path,
    source_names: &[PathBuf],
) -> bool {
    let Some(value) = value.and_then(toml::Value::as_str) else {
        return false;
    };
    setting_path_matches(value, project, home, source_names)
}

fn setting_path_matches(
    value: &str,
    project: Option<&Path>,
    home: &Path,
    source_names: &[PathBuf],
) -> bool {
    let Some(path) = expand_setting(value, project, home) else {
        return false;
    };
    source_names.iter().any(|source| same_path(&path, source))
}

fn expand_setting(value: &str, project: Option<&Path>, home: &Path) -> Option<PathBuf> {
    let mut expanded = value.to_string();
    if expanded == "~" {
        expanded = home.to_string_lossy().into_owned();
    } else if let Some(rest) = expanded.strip_prefix("~/") {
        expanded = home.join(rest).to_string_lossy().into_owned();
    }
    if expanded.contains("{project}") {
        let project = project?;
        let name = project.file_name()?.to_string_lossy();
        expanded = expanded.replace("{project}", &name);
    }
    let path = PathBuf::from(expanded);
    let path = if path.is_absolute() {
        path
    } else {
        project?.join(path)
    };
    Some(normalized_path(&path))
}

fn write_atomic(path: &Path, contents: &[u8]) -> io::Result<()> {
    let parent = path.parent().unwrap_or_else(|| Path::new("."));
    let name = path
        .file_name()
        .map(|name| name.to_string_lossy().into_owned())
        .unwrap_or_else(|| "config".to_string());
    let suffix = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos();
    let temp = parent.join(format!(".{name}.tmp.{}.{}", std::process::id(), suffix));
    let existing_permissions = fs::metadata(path)
        .ok()
        .map(|metadata| metadata.permissions());
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&temp)?;
    if let Some(permissions) = existing_permissions
        && let Err(error) = fs::set_permissions(&temp, permissions)
    {
        drop(file);
        let _ = fs::remove_file(&temp);
        return Err(error);
    }
    if let Err(error) = file
        .write_all(contents)
        .and_then(|()| file.flush())
        .and_then(|()| file.sync_all())
    {
        drop(file);
        let _ = fs::remove_file(&temp);
        return Err(error);
    }
    drop(file);
    if let Err(error) = fs::rename(&temp, path) {
        let _ = fs::remove_file(&temp);
        return Err(error);
    }
    Ok(())
}
