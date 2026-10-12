use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::io;
use std::path::Path;

use varde_core::skill_relations::{IMPLICIT_SKILL, Relations, closure, parse};

use super::embedded::{Skill, retired_names, skills};
use super::fsops;
use super::{LinkMode, SyncContext};

const OWNERSHIP_MARKER: &str = ".varde-managed-skill";
const OWNERSHIP_VALUE: &[u8] = b"varde-managed-skill\n";

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum ManagedDirectory {
    Missing,
    Owned,
    Foreign,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum HarnessEntry {
    Missing,
    OwnedDirectory,
    CanonicalLink,
    Foreign,
}

fn paths_resolve_to_same_existing_path(first: &Path, second: &Path) -> io::Result<bool> {
    let first = match fs::canonicalize(first) {
        Ok(path) => path,
        Err(error) if error.kind() == io::ErrorKind::NotFound => return Ok(false),
        Err(error) => return Err(error),
    };
    let second = match fs::canonicalize(second) {
        Ok(path) => path,
        Err(error) if error.kind() == io::ErrorKind::NotFound => return Ok(false),
        Err(error) => return Err(error),
    };
    Ok(first == second)
}

fn marker_matches(directory: &Path) -> io::Result<bool> {
    let marker = directory.join(OWNERSHIP_MARKER);
    let metadata = match fs::symlink_metadata(&marker) {
        Ok(metadata) => metadata,
        Err(error) if error.kind() == io::ErrorKind::NotFound => return Ok(false),
        Err(error) => return Err(error),
    };
    if !metadata.file_type().is_file() {
        return Ok(false);
    }

    let contents = fs::read_to_string(marker)?;
    Ok(contents.lines().any(|line| line == "varde-managed-skill"))
}

fn managed_directory(path: &Path) -> io::Result<ManagedDirectory> {
    let metadata = match fs::symlink_metadata(path) {
        Ok(metadata) => metadata,
        Err(error) if error.kind() == io::ErrorKind::NotFound => {
            return Ok(ManagedDirectory::Missing);
        }
        Err(error) => return Err(error),
    };
    if !metadata.file_type().is_dir() {
        return Ok(ManagedDirectory::Foreign);
    }
    if marker_matches(path)? {
        Ok(ManagedDirectory::Owned)
    } else {
        Ok(ManagedDirectory::Foreign)
    }
}

fn harness_entry(path: &Path, canonical: &Path) -> io::Result<HarnessEntry> {
    let metadata = match fs::symlink_metadata(path) {
        Ok(metadata) => metadata,
        Err(error) if error.kind() == io::ErrorKind::NotFound => {
            return Ok(HarnessEntry::Missing);
        }
        Err(error) => return Err(error),
    };

    if metadata.file_type().is_symlink() {
        return if fs::read_link(path)? == canonical {
            Ok(HarnessEntry::CanonicalLink)
        } else {
            Ok(HarnessEntry::Foreign)
        };
    }
    if metadata.file_type().is_dir() && marker_matches(path)? {
        Ok(HarnessEntry::OwnedDirectory)
    } else {
        Ok(HarnessEntry::Foreign)
    }
}

fn preserve(path: &Path, dry_run: bool) {
    if dry_run {
        println!("would preserve unowned {}", path.display());
    } else {
        println!("Preserved unowned {}", path.display());
    }
}

/// The frontmatter block of a `SKILL.md`, without its `---` fences.
fn frontmatter(text: &str) -> &str {
    let Some(rest) = text.strip_prefix("---\n") else {
        return "";
    };
    rest.split_once("\n---").map_or("", |(block, _)| block)
}

/// The relations one embedded skill declares in its `SKILL.md` frontmatter.
fn relations(skill: &Skill) -> Result<Relations, String> {
    let file = skill
        .files
        .iter()
        .find(|file| file.relative_path == "SKILL.md")
        .ok_or_else(|| format!("skill {} has no SKILL.md", skill.name))?;
    let text = std::str::from_utf8(file.bytes)
        .map_err(|error| format!("skill {} SKILL.md is not UTF-8: {error}", skill.name))?;
    parse(frontmatter(text)).map_err(|error| format!("skill {}: {error}", skill.name))
}

pub(crate) fn skill_relations() -> Result<BTreeMap<&'static str, Relations>, String> {
    skills()
        .iter()
        .map(|skill| relations(skill).map(|relations| (skill.name, relations)))
        .collect()
}

/// A selection plus its `requires` closure, sorted and deduplicated.
fn resolve_names(
    names: &[String],
    relations: &BTreeMap<&'static str, Relations>,
) -> Result<Vec<String>, String> {
    closure(names, |name| {
        relations
            .get(name)
            .map(|relations| relations.requires.clone())
    })
    .map_err(|error| error.to_string())
}

#[derive(Debug)]
pub(crate) struct ResolvedSelection {
    pub(crate) skills: Vec<&'static Skill>,
    pub(crate) features: BTreeSet<&'static str>,
    relations: BTreeMap<&'static str, Relations>,
}

/// Features enabled by the effective skill closure.
fn features_for(names: &[String]) -> BTreeSet<&'static str> {
    let mut features = BTreeSet::new();
    for name in names {
        match name.as_str() {
            "varde-change" => {
                features.insert("change");
            }
            "varde-toz" => {
                features.insert("toz");
            }
            "varde-learn" => {
                features.insert("learn");
            }
            "varde-code" => {
                features.insert("code");
            }
            "varde-knowledge" => {
                features.insert("knowledge");
            }
            _ => {}
        }
    }
    features
}

/// Resolve the effective closure once for both installation and feature selection.
pub(crate) fn resolve_selection(
    context: &SyncContext,
    relations: &BTreeMap<&'static str, Relations>,
) -> Result<ResolvedSelection, String> {
    let selection = context
        .selected_skills
        .as_ref()
        .filter(|names| !names.is_empty());
    let resolved = match selection {
        Some(names) => resolve_names(names, relations)?,
        None => skills()
            .iter()
            .map(|skill| skill.name.to_string())
            .collect(),
    };
    let selected = skills()
        .iter()
        .filter(|skill| {
            skill.name == IMPLICIT_SKILL || resolved.iter().any(|name| name == skill.name)
        })
        .collect();
    Ok(ResolvedSelection {
        skills: selected,
        features: features_for(&resolved),
        relations: relations.clone(),
    })
}

/// One line for each `recommends` skill the selection does not install. The
/// printed command repeats the saved selection so that following it replaces
/// rather than narrows the selection.
fn print_recommends_hints(
    selected: &[&Skill],
    selection: &[String],
    relations: &BTreeMap<&'static str, Relations>,
) {
    let mut hinted = BTreeSet::new();
    for skill in selected {
        let Some(relations) = relations.get(skill.name) else {
            continue;
        };
        for recommended in &relations.recommends {
            if selected.iter().any(|other| other.name == recommended) {
                continue;
            }
            if hinted.insert(recommended.clone()) {
                let mut names = selection.to_vec();
                if !names.iter().any(|name| name == recommended) {
                    names.push(recommended.clone());
                }
                println!(
                    "Hint: {} works better with {}; add it with --skills {}",
                    skill.name,
                    recommended,
                    names.join(",")
                );
            }
        }
    }
}

fn install_canonical(context: &SyncContext, selected: &[&'static Skill]) -> Result<(), String> {
    for &skill in selected {
        let destination = context.skills_dir.join(skill.name);
        let state = managed_directory(&destination).map_err(|error| {
            format!(
                "could not inspect skill destination {}: {error}",
                destination.display()
            )
        })?;
        if state == ManagedDirectory::Foreign {
            preserve(&destination, context.dry_run);
            continue;
        }

        if context.dry_run {
            println!(
                "would install skill {} -> {}",
                skill.name,
                destination.display()
            );
            continue;
        }

        fsops::replace_directory(&destination, |staged| {
            for file in skill.files {
                fsops::write_file(
                    &staged.join(file.relative_path),
                    file.bytes,
                    file.executable,
                )?;
            }
            fsops::write_file(&staged.join(OWNERSHIP_MARKER), OWNERSHIP_VALUE, false)
        })
        .map_err(|error| {
            format!(
                "could not install skill {} at {}: {error}",
                skill.name,
                destination.display()
            )
        })?;
        println!(
            "Installed skill {} -> {}",
            skill.name,
            destination.display()
        );
    }

    for name in retired_names() {
        let destination = context.skills_dir.join(name);
        match managed_directory(&destination).map_err(|error| {
            format!(
                "could not inspect retired skill {}: {error}",
                destination.display()
            )
        })? {
            ManagedDirectory::Owned => {
                if context.dry_run {
                    println!("would remove retired skill {}", destination.display());
                } else {
                    fs::remove_dir_all(&destination).map_err(|error| {
                        format!(
                            "could not remove retired skill {}: {error}",
                            destination.display()
                        )
                    })?;
                    println!("Removed retired skill {}", destination.display());
                }
            }
            ManagedDirectory::Foreign => preserve(&destination, context.dry_run),
            ManagedDirectory::Missing => {}
        }
    }
    Ok(())
}

fn sync_entry(
    context: &SyncContext,
    directory: &Path,
    skill_name: &str,
    link_mode: LinkMode,
) -> Result<(), String> {
    let canonical = context.skills_dir.join(skill_name);
    let destination = directory.join(skill_name);
    let state = harness_entry(&destination, &canonical).map_err(|error| {
        format!(
            "could not inspect harness skill {}: {error}",
            destination.display()
        )
    })?;

    if state != HarnessEntry::CanonicalLink
        && paths_resolve_to_same_existing_path(&destination, &canonical).map_err(|error| {
            format!(
                "could not resolve harness skill {}: {error}",
                destination.display()
            )
        })?
    {
        println!(
            "Skipped {}: it resolves to the canonical skill {}",
            destination.display(),
            canonical.display()
        );
        return Ok(());
    }

    if state == HarnessEntry::Foreign {
        preserve(&destination, context.dry_run);
        return Ok(());
    }

    if link_mode == LinkMode::Symlink && state == HarnessEntry::CanonicalLink {
        if context.dry_run {
            println!(
                "would keep already linked {} -> {}",
                destination.display(),
                canonical.display()
            );
        } else {
            println!(
                "already linked {} -> {}",
                destination.display(),
                canonical.display()
            );
        }
        return Ok(());
    }

    if context.dry_run {
        match link_mode {
            LinkMode::Symlink => {
                println!(
                    "would link {} -> {}",
                    destination.display(),
                    canonical.display()
                );
            }
            LinkMode::Copy => {
                println!(
                    "would install copy {} -> {}",
                    skill_name,
                    destination.display()
                );
            }
        }
        return Ok(());
    }

    match link_mode {
        LinkMode::Symlink => {
            fsops::replace_with_symlink(&destination, &canonical).map_err(|error| {
                format!(
                    "could not link harness skill {} to {}: {error}",
                    destination.display(),
                    canonical.display()
                )
            })?
        }
        LinkMode::Copy => fsops::replace_directory(&destination, |staged| {
            fsops::copy_directory(&canonical, staged)?;
            fsops::write_file(&staged.join(OWNERSHIP_MARKER), OWNERSHIP_VALUE, false)
        })
        .map_err(|error| {
            format!(
                "could not copy harness skill {} from {}: {error}",
                destination.display(),
                canonical.display()
            )
        })?,
    }

    match link_mode {
        LinkMode::Symlink => println!(
            "Linked harness skill {} -> {}",
            destination.display(),
            canonical.display()
        ),
        LinkMode::Copy => println!("Installed harness skill copy {}", destination.display()),
    }
    Ok(())
}

fn sync_harness_directory(
    context: &SyncContext,
    directory: &Path,
    selected: &[&'static Skill],
) -> Result<(), String> {
    if paths_resolve_to_same_existing_path(directory, &context.skills_dir).map_err(|error| {
        format!(
            "could not resolve harness skills directory {}: {error}",
            directory.display()
        )
    })? {
        println!(
            "Skipped {}: it is the canonical skills folder",
            directory.display()
        );
        return Ok(());
    }

    if !context.dry_run {
        fs::create_dir_all(directory).map_err(|error| {
            format!(
                "could not create harness skills directory {}: {error}",
                directory.display()
            )
        })?;
    }

    for &skill in selected {
        sync_entry(context, directory, skill.name, context.link_mode)?;
    }

    for name in retired_names() {
        let destination = directory.join(name);
        let canonical = context.skills_dir.join(name);
        let state = harness_entry(&destination, &canonical).map_err(|error| {
            format!(
                "could not inspect retired harness skill {}: {error}",
                destination.display()
            )
        })?;
        match state {
            HarnessEntry::CanonicalLink | HarnessEntry::OwnedDirectory => {
                if context.dry_run {
                    println!(
                        "would remove retired harness skill {}",
                        destination.display()
                    );
                } else {
                    match state {
                        HarnessEntry::CanonicalLink => fs::remove_file(&destination),
                        HarnessEntry::OwnedDirectory => fs::remove_dir_all(&destination),
                        HarnessEntry::Missing | HarnessEntry::Foreign => unreachable!(),
                    }
                    .map_err(|error| {
                        format!(
                            "could not remove retired harness skill {}: {error}",
                            destination.display()
                        )
                    })?;
                    println!("Removed retired harness skill {}", destination.display());
                }
            }
            HarnessEntry::Foreign => preserve(&destination, context.dry_run),
            HarnessEntry::Missing => {}
        }
    }
    Ok(())
}

pub(crate) fn run(context: &SyncContext, resolved: ResolvedSelection) -> Result<(), String> {
    let selected = resolved.skills;
    print_recommends_hints(
        &selected,
        context.selected_skills.as_deref().unwrap_or_default(),
        &resolved.relations,
    );

    install_canonical(context, &selected)?;

    for harness in &context.harnesses {
        if let Some(directory) = &harness.skills_dir {
            sync_harness_directory(context, directory, &selected)?;
        }
    }

    let pi_skills = context.home.join(".agents/skills");
    if context
        .harnesses
        .iter()
        .any(|harness| harness.id == super::harness::HarnessId::Pi)
        && context.skills_dir != pi_skills
    {
        sync_harness_directory(context, &pi_skills, &selected)?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn frontmatter_returns_the_block_between_the_fences() {
        assert_eq!(frontmatter("---\nname: a\n---\nbody\n"), "name: a");
        assert_eq!(frontmatter("body only"), "");
        assert_eq!(frontmatter("---\nname: a\n"), "");
    }

    #[test]
    fn resolve_names_adds_the_requires_closure() {
        let required = |name: &str| Relations {
            requires: vec![name.to_string()],
            recommends: Vec::new(),
        };
        let relations = BTreeMap::from([
            ("varde-a", required("varde-b")),
            ("varde-b", required("varde-c")),
            ("varde-c", Relations::default()),
        ]);
        let selected = vec!["varde-a".to_string()];
        assert_eq!(
            resolve_names(&selected, &relations).unwrap(),
            vec![
                "varde-a".to_string(),
                "varde-b".to_string(),
                "varde-c".to_string()
            ]
        );
    }

    #[test]
    fn features_come_from_the_requires_closure() {
        let relations = BTreeMap::from([
            (
                "custom-skill",
                Relations {
                    requires: vec!["varde-change".into()],
                    recommends: vec![],
                },
            ),
            ("varde-change", Relations::default()),
        ]);
        let context = SyncContext {
            skills_dir: Path::new("skills").into(),
            agents_dir: Path::new("agents").into(),
            selected_skills: Some(vec!["custom-skill".into()]),
            link_mode: LinkMode::Symlink,
            harnesses: Vec::new(),
            dry_run: true,
            home: Path::new("home").into(),
        };
        let resolved = resolve_selection(&context, &relations).unwrap();
        assert!(resolved.features.contains("change"));
        assert!(
            resolved
                .skills
                .iter()
                .any(|skill| skill.name == "varde-change")
        );
    }

    #[test]
    fn feature_mapping_covers_supported_skill_selections() {
        let cases: &[(&str, &[&str], &[&str])] = &[
            ("toz", &["varde-toz"], &["toz"]),
            ("learn", &["varde-learn"], &["learn"]),
            ("scan", &["varde-scan", "varde-code"], &["code"]),
            ("docs", &["varde-docs"], &[]),
            ("knowledge", &["varde-knowledge"], &["knowledge"]),
            (
                "workflow/full",
                &[
                    "varde-change",
                    "varde-toz",
                    "varde-learn",
                    "varde-code",
                    "varde-knowledge",
                ],
                &["change", "toz", "learn", "code", "knowledge"],
            ),
        ];
        for (preset, skills, expected) in cases {
            let names = skills
                .iter()
                .map(|name| (*name).to_owned())
                .collect::<Vec<_>>();
            let actual = features_for(&names);
            assert_eq!(
                actual,
                expected.iter().copied().collect(),
                "preset: {preset}, skills: {skills:?}"
            );
        }
    }

    #[test]
    fn resolve_names_reports_an_unknown_skill() {
        let relations = BTreeMap::new();
        let selected = vec!["varde-absent".to_string()];
        assert!(resolve_names(&selected, &relations).is_err());
    }
}
