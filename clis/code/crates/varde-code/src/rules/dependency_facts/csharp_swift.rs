//! C# and Swift dependency facts.
//!
//! Neither language imports files, so a fact needs a unit the repository
//! itself defines.  C# units are project directories (nearest ancestor with a
//! `.csproj`); Swift units are SwiftPM target directories
//! (`<package>/Sources/<Target>` beside a `Package.swift` that names the
//! target) or Xcode native-target directories (`*.xcodeproj/project.pbxproj`,
//! unit = the target's common source directory).  A fact exists only when the
//! imported namespace (C#) or module (Swift) maps to exactly one other unit.
//! Framework and package imports, namespaces spread over several projects,
//! global/static/alias usings, `#if`-guarded imports, Xcode targets that share
//! a source directory or module name, and build-setting-dependent Xcode source
//! paths yield no fact.  Source text is read from disk because the index keeps
//! only the import specifier.

use super::{Fact, FactInput, FileRow, IMPORT_KIND, ImportRow};
use std::collections::{BTreeMap, BTreeSet, HashMap, HashSet};
use std::path::{Path, PathBuf};

/// Certified dependency facts for C# and Swift.
pub(super) fn facts(input: &FactInput<'_>) -> Result<Vec<Fact>, String> {
    let mut imports_by_file: HashMap<i64, Vec<&ImportRow>> = HashMap::new();
    for import in input.imports.iter().filter(|import| !import.type_only) {
        imports_by_file
            .entry(import.file_id)
            .or_default()
            .push(import);
    }
    let mut facts = csharp_facts(input.files, &imports_by_file)?;
    facts.extend(swift_facts(input.files, &imports_by_file)?);
    facts.extend(xcode_facts(input.files, &imports_by_file)?);
    Ok(facts)
}

type ImportsByFile<'a> = HashMap<i64, Vec<&'a ImportRow>>;

/// One source line with comments removed and whether it sits inside `#if`.
struct Line {
    code: String,
    guarded: bool,
}

fn source_lines(text: &str) -> Vec<Line> {
    let mut lines = Vec::new();
    let mut in_block = false;
    let mut guard_depth = 0usize;
    for raw in text.lines() {
        let mut code = String::new();
        let mut rest = raw;
        loop {
            if in_block {
                let Some(end) = rest.find("*/") else { break };
                rest = &rest[end + 2..];
                in_block = false;
            } else if let Some(start) = rest.find("/*") {
                code.push_str(&rest[..start]);
                rest = &rest[start + 2..];
                in_block = true;
            } else {
                code.push_str(rest);
                break;
            }
        }
        if let Some(cut) = code.find("//") {
            code.truncate(cut);
        }
        let trimmed = code.trim();
        if trimmed.starts_with("#endif") {
            guard_depth = guard_depth.saturating_sub(1);
        }
        lines.push(Line {
            code: code.clone(),
            guarded: guard_depth > 0,
        });
        if trimmed.starts_with("#if") {
            guard_depth += 1;
        }
    }
    lines
}

fn read_source(file: &FileRow) -> Result<Option<String>, String> {
    match std::fs::read(&file.physical) {
        Ok(bytes) => Ok(Some(String::from_utf8_lossy(&bytes).into_owned())),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(None),
        Err(error) => Err(format!("read {}: {error}", file.relative)),
    }
}

fn extension(file: &FileRow) -> Option<&str> {
    Path::new(&file.relative)
        .extension()
        .and_then(|extension| extension.to_str())
}

fn is_candidate(file: &FileRow, wanted: &str) -> bool {
    !file.is_test && !file.is_tooling && extension(file) == Some(wanted)
}

fn is_identifier_path(name: &str) -> bool {
    !name.is_empty()
        && name.split('.').all(|part| {
            part.chars()
                .next()
                .is_some_and(|first| first.is_alphabetic() || first == '_')
                && part.chars().all(|c| c.is_alphanumeric() || c == '_')
        })
}

fn fact(source: &FileRow, import: &ImportRow, from_unit: &str, to: (&FileRow, &str)) -> Fact {
    Fact {
        from_file_id: source.id,
        from_unit: from_unit.to_string(),
        to_file_id: Some(to.0.id),
        to_unit: Some(to.1.to_string()),
        kind: IMPORT_KIND,
        certainty: "certified",
        source_entity_id: import.id,
        specifier: import.specifier.clone(),
    }
}

// ---- C# ----

struct CSharpFile<'a> {
    file: &'a FileRow,
    unit: String,
    /// Namespaces imported by a plain, unguarded `using Name;`.
    usings: HashSet<String>,
}

/// Which projects declare a namespace, and the first declaring file of each.
#[derive(Default)]
struct Declarations<'a> {
    by_namespace: BTreeMap<String, BTreeMap<String, &'a FileRow>>,
    /// Projects with a nested `namespace`, whose full names are not tracked.
    opaque: BTreeSet<String>,
}

fn csharp_facts(
    files: &[FileRow],
    imports_by_file: &ImportsByFile<'_>,
) -> Result<Vec<Fact>, String> {
    let mut project_cache = HashMap::new();
    let mut declarations = Declarations::default();
    let mut sources = Vec::new();
    for file in files.iter().filter(|file| is_candidate(file, "cs")) {
        let Some(unit) = project_dir(file, &mut project_cache)? else {
            continue;
        };
        let Some(text) = read_source(file)? else {
            continue;
        };
        let lines = source_lines(&text);
        for namespace in declared_namespaces(&lines, &unit, &mut declarations.opaque) {
            declarations
                .by_namespace
                .entry(namespace)
                .or_default()
                .entry(unit.clone())
                .and_modify(|first| {
                    if file.relative < first.relative {
                        *first = file;
                    }
                })
                .or_insert(file);
        }
        sources.push(CSharpFile {
            file,
            unit,
            usings: plain_usings(&lines),
        });
    }

    let mut facts = Vec::new();
    for source in &sources {
        for import in imports_by_file.get(&source.file.id).into_iter().flatten() {
            let namespace = import.specifier.replace('/', ".");
            if !source.usings.contains(&namespace) {
                continue;
            }
            let Some(projects) = declarations.by_namespace.get(&namespace) else {
                continue;
            };
            let mut projects = projects.iter();
            let (Some((target, target_file)), None) = (projects.next(), projects.next()) else {
                continue;
            };
            if *target == source.unit
                || declarations.opaque.contains(target)
                || declarations.opaque.contains(&source.unit)
            {
                continue;
            }
            facts.push(fact(
                source.file,
                import,
                &source.unit,
                (target_file, target),
            ));
        }
    }
    Ok(facts)
}

/// Namespaces declared at the start of a line; an indented declaration is
/// nested, so it marks the project opaque instead.
fn declared_namespaces(lines: &[Line], unit: &str, opaque: &mut BTreeSet<String>) -> Vec<String> {
    let mut namespaces = Vec::new();
    for line in lines {
        let Some(rest) = line.code.trim_start().strip_prefix("namespace ") else {
            continue;
        };
        let name = rest.trim().trim_end_matches(['{', ';']).trim();
        if !is_identifier_path(name) {
            continue;
        }
        if line.code.starts_with(char::is_whitespace) {
            opaque.insert(unit.to_string());
        } else {
            namespaces.push(name.to_string());
        }
    }
    namespaces
}

fn plain_usings(lines: &[Line]) -> HashSet<String> {
    lines
        .iter()
        .filter(|line| !line.guarded)
        .filter_map(|line| {
            let name = line
                .code
                .trim()
                .strip_prefix("using ")?
                .strip_suffix(';')?
                .trim();
            is_identifier_path(name).then(|| name.to_string())
        })
        .collect()
}

/// Nearest ancestor directory holding a `.csproj`, as a repository-relative
/// path (`.` for the root).
fn project_dir(
    file: &FileRow,
    cache: &mut HashMap<PathBuf, bool>,
) -> Result<Option<String>, String> {
    let mut relative = Path::new(&file.relative).parent();
    let mut physical = file.physical.parent();
    while let (Some(rel), Some(phys)) = (relative, physical) {
        if has_project_file(phys, cache)? {
            return Ok(Some(relative_dir(rel)));
        }
        relative = rel.parent().filter(|_| !rel.as_os_str().is_empty());
        physical = phys.parent();
    }
    Ok(None)
}

fn relative_dir(relative: &Path) -> String {
    if relative.as_os_str().is_empty() {
        ".".to_string()
    } else {
        relative.to_string_lossy().replace('\\', "/")
    }
}

fn has_project_file(dir: &Path, cache: &mut HashMap<PathBuf, bool>) -> Result<bool, String> {
    if let Some(known) = cache.get(dir) {
        return Ok(*known);
    }
    let entries = match std::fs::read_dir(dir) {
        Ok(entries) => entries,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(false),
        Err(error) => return Err(format!("read {}: {error}", dir.display())),
    };
    let mut found = false;
    for entry in entries {
        let path = entry
            .map_err(|error| format!("read {}: {error}", dir.display()))?
            .path();
        found |= path
            .extension()
            .is_some_and(|extension| extension == "csproj");
    }
    cache.insert(dir.to_path_buf(), found);
    Ok(found)
}

// ---- Swift ----

struct SwiftTarget {
    module: String,
    unit: String,
    /// Whether the owning `Package.swift` declares a remote package.
    remote_packages: bool,
}

fn swift_facts(
    files: &[FileRow],
    imports_by_file: &ImportsByFile<'_>,
) -> Result<Vec<Fact>, String> {
    let mut manifests = HashMap::new();
    let mut sources = Vec::new();
    let mut units_by_module: BTreeMap<String, BTreeMap<String, &FileRow>> = BTreeMap::new();
    for file in files.iter().filter(|file| is_candidate(file, "swift")) {
        let Some(target) = swift_target(file, &mut manifests)? else {
            continue;
        };
        units_by_module
            .entry(target.module.clone())
            .or_default()
            .entry(target.unit.clone())
            .and_modify(|first| {
                if file.relative < first.relative {
                    *first = file;
                }
            })
            .or_insert(file);
        sources.push((file, target));
    }

    let mut facts = Vec::new();
    for (file, target) in &sources {
        let imports = imports_by_file.get(&file.id);
        if imports.is_none_or(|imports| imports.is_empty()) {
            continue;
        }
        let Some(text) = read_source(file)? else {
            continue;
        };
        let plain = plain_swift_imports(&source_lines(&text));
        for import in imports.into_iter().flatten() {
            let module = import.specifier.split('/').next().unwrap_or_default();
            if !plain.contains(&import.specifier) || module == target.module {
                continue;
            }
            let Some(units) = units_by_module.get(module) else {
                continue;
            };
            let mut units = units.iter();
            let (Some((unit, unit_file)), None) = (units.next(), units.next()) else {
                continue;
            };
            let same_package = package_of(unit) == package_of(&target.unit);
            if target.remote_packages && !same_package {
                continue;
            }
            facts.push(fact(file, import, &target.unit, (unit_file, unit)));
        }
    }
    Ok(facts)
}

/// Plain top-level `import Module` lines (attributes and guards excluded),
/// keyed like the extracted specifier: the last token with `.` as `/`.
fn plain_swift_imports(lines: &[Line]) -> HashSet<String> {
    lines
        .iter()
        .filter(|line| !line.guarded)
        .filter_map(|line| {
            let mut tokens = line.code.split_whitespace();
            if tokens.next()? != "import" {
                return None;
            }
            let path = tokens.next_back()?;
            is_identifier_path(path).then(|| path.replace('.', "/"))
        })
        .collect()
}

/// The SwiftPM target containing `file`: `<package>/Sources/<Target>/…` where
/// `<package>/Package.swift` names `<Target>`.
fn swift_target(
    file: &FileRow,
    manifests: &mut HashMap<PathBuf, Option<String>>,
) -> Result<Option<SwiftTarget>, String> {
    let components: Vec<&str> = file.relative.split('/').collect();
    let Some(sources) = (0..components.len().saturating_sub(2))
        .rev()
        .find(|index| components[*index] == "Sources")
    else {
        return Ok(None);
    };
    let Some(package) = file.physical.ancestors().nth(components.len() - sources) else {
        return Ok(None);
    };
    let manifest = match manifests.get(package) {
        Some(known) => known.clone(),
        None => {
            let text = match std::fs::read_to_string(package.join("Package.swift")) {
                Ok(text) => Some(text),
                Err(error) if error.kind() == std::io::ErrorKind::NotFound => None,
                Err(error) => {
                    return Err(format!("read {}/Package.swift: {error}", package.display()));
                }
            };
            manifests.insert(package.to_path_buf(), text.clone());
            text
        }
    };
    let module = components[sources + 1];
    Ok(manifest
        .filter(|text| text.contains(&format!("\"{module}\"")))
        .map(|text| SwiftTarget {
            module: module.to_string(),
            unit: components[..sources + 2].join("/"),
            remote_packages: text.contains(".package(url:") || text.contains(".package(name:"),
        }))
}

fn package_of(unit: &str) -> Option<&Path> {
    Path::new(unit).parent()?.parent()
}

// ---- Xcode ----

/// One certifiable Xcode native target: its module name, the repository
/// directory holding its sources, and the indexed files it owns.
struct XcodeTarget {
    module: String,
    unit: String,
    files: Vec<i64>,
}

/// Certify Swift `import <Module>` against Xcode native targets.  A target is
/// certifiable only when every one of its `PBXSourcesBuildPhase` Swift sources
/// resolves to a path inside the repository, and its module name and source
/// directory are unique among the discovered targets.
fn xcode_facts(
    files: &[FileRow],
    imports_by_file: &ImportsByFile<'_>,
) -> Result<Vec<Fact>, String> {
    let Some(root) = repository_root(files) else {
        return Ok(Vec::new());
    };
    let projects = find_xcode_projects(files, &root)?;
    if projects.is_empty() {
        return Ok(Vec::new());
    }
    let by_relative: HashMap<&str, i64> = files
        .iter()
        .map(|file| (file.relative.as_str(), file.id))
        .collect();
    let by_id: HashMap<i64, &FileRow> = files.iter().map(|file| (file.id, file)).collect();

    let mut targets = Vec::new();
    for project in &projects {
        targets.extend(parse_xcode_targets(project, &root, &by_relative)?);
    }
    if targets.is_empty() {
        return Ok(Vec::new());
    }

    let mut module_counts: BTreeMap<&str, usize> = BTreeMap::new();
    let mut unit_counts: BTreeMap<&str, usize> = BTreeMap::new();
    let mut file_counts: HashMap<i64, usize> = HashMap::new();
    for target in &targets {
        *module_counts.entry(target.module.as_str()).or_default() += 1;
        *unit_counts.entry(target.unit.as_str()).or_default() += 1;
        for file in &target.files {
            *file_counts.entry(*file).or_default() += 1;
        }
    }

    let mut module_targets: BTreeMap<&str, (&str, i64)> = BTreeMap::new();
    let mut file_owner: HashMap<i64, (&str, &str)> = HashMap::new();
    for target in &targets {
        let ambiguous = module_counts[target.module.as_str()] > 1
            || unit_counts[target.unit.as_str()] > 1
            || target.files.iter().any(|file| file_counts[file] > 1);
        if ambiguous {
            continue;
        }
        let Some(first) = target.files.first() else {
            continue;
        };
        module_targets.insert(target.module.as_str(), (target.unit.as_str(), *first));
        for file in &target.files {
            file_owner.insert(*file, (target.module.as_str(), target.unit.as_str()));
        }
    }
    if module_targets.is_empty() {
        return Ok(Vec::new());
    }

    let mut facts = Vec::new();
    for file in files.iter().filter(|file| is_candidate(file, "swift")) {
        let Some((source_module, source_unit)) = file_owner.get(&file.id).copied() else {
            continue;
        };
        let imports = imports_by_file.get(&file.id);
        if imports.is_none_or(|imports| imports.is_empty()) {
            continue;
        }
        let Some(text) = read_source(file)? else {
            continue;
        };
        let plain = plain_swift_imports(&source_lines(&text));
        for import in imports.into_iter().flatten() {
            if !plain.contains(&import.specifier) {
                continue;
            }
            let module = import.specifier.split('/').next().unwrap_or_default();
            if module == source_module {
                continue;
            }
            let Some((to_unit, to_id)) = module_targets.get(module).copied() else {
                continue;
            };
            if to_unit == source_unit {
                continue;
            }
            let Some(target) = by_id.get(&to_id) else {
                continue;
            };
            facts.push(fact(file, import, source_unit, (target, to_unit)));
        }
    }
    Ok(facts)
}

/// The repository root, derived from any indexed file's absolute path and its
/// repository-relative path.  `FactInput` carries no root, and every per-group
/// builder that touches the filesystem reconstructs it the same way.
fn repository_root(files: &[FileRow]) -> Option<PathBuf> {
    let file = files.first()?;
    let depth = file.relative.split('/').count();
    file.physical.ancestors().nth(depth).map(Path::to_path_buf)
}

/// Bounded upward search for `*.xcodeproj` directories, memoized per directory
/// so a repository with many Swift files reads each directory once.
fn find_xcode_projects(files: &[FileRow], root: &Path) -> Result<BTreeSet<PathBuf>, String> {
    let mut cache: HashMap<PathBuf, Option<PathBuf>> = HashMap::new();
    let mut projects = BTreeSet::new();
    for file in files.iter().filter(|file| is_candidate(file, "swift")) {
        let mut directory = file.physical.parent();
        while let Some(current) = directory {
            if !current.starts_with(root) {
                break;
            }
            if let Some(project) = project_in(current, &mut cache)? {
                projects.insert(project);
                break;
            }
            if current == root {
                break;
            }
            directory = current.parent();
        }
    }
    Ok(projects)
}

fn project_in(
    directory: &Path,
    cache: &mut HashMap<PathBuf, Option<PathBuf>>,
) -> Result<Option<PathBuf>, String> {
    if let Some(known) = cache.get(directory) {
        return Ok(known.clone());
    }
    let entries = match std::fs::read_dir(directory) {
        Ok(entries) => entries,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
            cache.insert(directory.to_path_buf(), None);
            return Ok(None);
        }
        Err(error) => return Err(format!("read {}: {error}", directory.display())),
    };
    let mut found = None;
    for entry in entries {
        let path = entry
            .map_err(|error| format!("read {}: {error}", directory.display()))?
            .path();
        if path
            .extension()
            .is_some_and(|extension| extension == "xcodeproj")
            && path.is_dir()
        {
            found = Some(path);
            break;
        }
    }
    cache.insert(directory.to_path_buf(), found.clone());
    Ok(found)
}

/// Parse one `project.pbxproj` into certifiable native targets.  A malformed
/// plist or an unusable object graph yields no targets (a conservative miss)
/// rather than an error: real repositories contain project variants this
/// reader does not model, and a scan must not fail on them.
fn parse_xcode_targets(
    project: &Path,
    root: &Path,
    by_relative: &HashMap<&str, i64>,
) -> Result<Vec<XcodeTarget>, String> {
    let pbxproj = project.join("project.pbxproj");
    let text = match std::fs::read_to_string(&pbxproj) {
        Ok(text) => text,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(Vec::new()),
        Err(error) => return Err(format!("read {}: {error}", pbxproj.display())),
    };
    let Ok(Plist::Dict(top)) = parse_plist(&text) else {
        return Ok(Vec::new());
    };
    let Some(Plist::Dict(objects)) = top.get("objects") else {
        return Ok(Vec::new());
    };
    let main_group = objects.values().find_map(|object| {
        let dict = as_dict(object)?;
        (dict.get("isa").and_then(as_str)? == "PBXProject")
            .then(|| dict.get("mainGroup").and_then(as_str))
            .flatten()
    });
    let Some(main_group) = main_group else {
        return Ok(Vec::new());
    };
    let project_dir = project.parent().unwrap_or(root);
    let file_refs = walk_groups(objects, main_group, project_dir);

    let mut targets = Vec::new();
    for object in objects.values() {
        let Some(dict) = as_dict(object) else {
            continue;
        };
        if dict.get("isa").and_then(as_str) != Some("PBXNativeTarget") {
            continue;
        }
        let Some(name) = dict.get("name").and_then(as_str) else {
            continue;
        };
        let Some(module) = target_module(objects, dict, name) else {
            continue;
        };
        let Some(sources) = target_swift_sources(objects, dict, &file_refs) else {
            continue;
        };
        let Some(unit) = target_unit(&sources, root) else {
            continue;
        };
        let mut files = Vec::new();
        for source in &sources {
            let source = normalize_path(source);
            let Ok(relative) = source.strip_prefix(root) else {
                continue;
            };
            let relative = relative.to_string_lossy().replace('\\', "/");
            if let Some(id) = by_relative.get(relative.as_str()) {
                files.push(*id);
            }
        }
        files.sort_unstable();
        files.dedup();
        targets.push(XcodeTarget {
            module,
            unit,
            files,
        });
    }
    Ok(targets)
}

/// A `PBXFileReference` reached while walking the project's group tree.
struct XcodeFileRef {
    path: Option<PathBuf>,
    is_swift: bool,
}

/// Walk `PBXGroup`/`PBXVariantGroup` children from the main group, resolving
/// each file reference's path against its group's directory.  A group whose
/// `sourceTree` depends on build settings resolves to `None`, and so does every
/// file reference beneath it.
fn walk_groups(
    objects: &BTreeMap<String, Plist>,
    main_group: &str,
    project_dir: &Path,
) -> HashMap<String, XcodeFileRef> {
    let mut refs = HashMap::new();
    let mut stack = vec![(main_group.to_string(), Some(project_dir.to_path_buf()))];
    let mut seen = HashSet::new();
    while let Some((id, base)) = stack.pop() {
        if !seen.insert(id.clone()) {
            continue;
        }
        let Some(object) = objects.get(&id).and_then(as_dict) else {
            continue;
        };
        match object.get("isa").and_then(as_str) {
            Some("PBXGroup") | Some("PBXVariantGroup") => {
                let directory = group_dir(
                    object.get("sourceTree").and_then(as_str),
                    object.get("path").and_then(as_str),
                    base,
                    project_dir,
                );
                for child in object
                    .get("children")
                    .and_then(as_array)
                    .into_iter()
                    .flatten()
                {
                    if let Some(child) = as_str(child) {
                        stack.push((child.to_string(), directory.clone()));
                    }
                }
            }
            Some("PBXFileReference") => {
                let name = object
                    .get("path")
                    .and_then(as_str)
                    .or_else(|| object.get("name").and_then(as_str));
                let path = file_ref_path(
                    object.get("sourceTree").and_then(as_str),
                    name,
                    base.as_deref(),
                    project_dir,
                );
                refs.insert(
                    id,
                    XcodeFileRef {
                        is_swift: name.is_some_and(|name| name.ends_with(".swift")),
                        path,
                    },
                );
            }
            _ => {}
        }
    }
    refs
}

fn group_dir(
    source_tree: Option<&str>,
    path: Option<&str>,
    base: Option<PathBuf>,
    project_dir: &Path,
) -> Option<PathBuf> {
    let base = match source_tree {
        None | Some("<group>") => base,
        Some("SOURCE_ROOT") | Some("PROJECT_DIR") => Some(project_dir.to_path_buf()),
        Some("<absolute>") => Some(PathBuf::new()),
        _ => None,
    }?;
    Some(path.map_or(base.clone(), |path| base.join(path)))
}

fn file_ref_path(
    source_tree: Option<&str>,
    name: Option<&str>,
    base: Option<&Path>,
    project_dir: &Path,
) -> Option<PathBuf> {
    let name = name?;
    let base = match source_tree {
        None | Some("<group>") => base.map(Path::to_path_buf),
        Some("SOURCE_ROOT") | Some("PROJECT_DIR") => Some(project_dir.to_path_buf()),
        Some("<absolute>") => Some(PathBuf::new()),
        _ => None,
    }?;
    Some(base.join(name))
}

/// The Swift source paths of a `PBXSourcesBuildPhase`.  Returns `None` when the
/// phase structure cannot be followed or a Swift source is build-setting
/// dependent, so an unresolved target never certifies a fact.
fn target_swift_sources(
    objects: &BTreeMap<String, Plist>,
    target: &BTreeMap<String, Plist>,
    file_refs: &HashMap<String, XcodeFileRef>,
) -> Option<Vec<PathBuf>> {
    let mut sources = Vec::new();
    for phase_id in str_array(target.get("buildPhases")) {
        let Some(phase) = objects.get(&phase_id).and_then(as_dict) else {
            return None;
        };
        if phase.get("isa").and_then(as_str) != Some("PBXSourcesBuildPhase") {
            continue;
        }
        for build_id in str_array(phase.get("files")) {
            let build = objects.get(&build_id).and_then(as_dict)?;
            let file_ref = file_refs.get(build.get("fileRef").and_then(as_str)?)?;
            if file_ref.is_swift {
                sources.push(file_ref.path.clone()?);
            }
        }
    }
    (!sources.is_empty()).then_some(sources)
}

/// The target's module name: `PRODUCT_MODULE_NAME`, else `PRODUCT_NAME`, else
/// the target name; `$(TARGET_NAME)` expands, any other build-setting reference
/// makes the target uncertifiable.  Configurations that disagree make it
/// ambiguous.  The result is sanitized the way Xcode sanitizes module names.
fn target_module(
    objects: &BTreeMap<String, Plist>,
    target: &BTreeMap<String, Plist>,
    name: &str,
) -> Option<String> {
    let mut modules: BTreeSet<String> = BTreeSet::new();
    if let Some(list) = target.get("buildConfigurationList").and_then(as_str) {
        for configuration in str_array(
            objects
                .get(list)
                .and_then(as_dict)
                .and_then(|list| list.get("buildConfigurations")),
        ) {
            let settings = objects
                .get(&configuration)
                .and_then(as_dict)
                .and_then(|configuration| configuration.get("buildSettings"))
                .and_then(as_dict);
            let Some(settings) = settings else {
                continue;
            };
            let value = settings
                .get("PRODUCT_MODULE_NAME")
                .and_then(as_str)
                .or_else(|| settings.get("PRODUCT_NAME").and_then(as_str));
            if let Some(value) = value {
                modules.insert(sanitize_module(&resolve_setting(value, name)?));
            }
        }
    }
    let module = match modules.len() {
        0 => name.to_string(),
        1 => modules.into_iter().next()?,
        _ => return None,
    };
    Some(sanitize_module(&module))
}

fn resolve_setting(value: &str, target_name: &str) -> Option<String> {
    let mut resolved = String::new();
    let mut rest = value;
    while let Some(start) = rest.find("$(") {
        resolved.push_str(&rest[..start]);
        let after = &rest[start + 2..];
        let end = after.find(')')?;
        let expression = &after[..end];
        if expression == "TARGET_NAME" || expression.starts_with("TARGET_NAME:") {
            resolved.push_str(target_name);
        } else {
            return None;
        }
        rest = &after[end + 1..];
    }
    resolved.push_str(rest);
    (!resolved.contains("${")).then_some(resolved)
}

fn sanitize_module(name: &str) -> String {
    let mut module: String = name
        .chars()
        .map(|character| {
            if character.is_ascii_alphanumeric() || character == '_' {
                character
            } else {
                '_'
            }
        })
        .collect();
    if module.is_empty() || module.starts_with(|character: char| character.is_ascii_digit()) {
        module.insert(0, '_');
    }
    module
}

/// The repository-relative directory common to every source of a target.
fn target_unit(sources: &[PathBuf], root: &Path) -> Option<String> {
    let mut dirs = Vec::new();
    for source in sources {
        let source = normalize_path(source);
        let dir = normalize_path(source.parent()?);
        if !dir.starts_with(root) {
            return None;
        }
        dirs.push(dir);
    }
    let common = common_dir(&dirs)?;
    let relative = common.strip_prefix(root).ok()?;
    let relative = relative.to_string_lossy().replace('\\', "/");
    Some(if relative.is_empty() {
        ".".to_string()
    } else {
        relative
    })
}

fn common_dir(dirs: &[PathBuf]) -> Option<PathBuf> {
    let mut common: Vec<std::path::Component<'_>> = dirs.first()?.components().collect();
    for dir in &dirs[1..] {
        let components: Vec<std::path::Component<'_>> = dir.components().collect();
        let shared = common
            .iter()
            .zip(&components)
            .take_while(|(left, right)| left == right)
            .count();
        common.truncate(shared);
    }
    Some(common.iter().collect())
}

fn normalize_path(path: &Path) -> PathBuf {
    let mut normalized = PathBuf::new();
    for component in path.components() {
        match component {
            std::path::Component::ParentDir => {
                normalized.pop();
            }
            std::path::Component::CurDir => {}
            other => normalized.push(other),
        }
    }
    normalized
}

// ---- OpenStep plist ----

/// The subset of the OpenStep property-list syntax `project.pbxproj` uses.
enum Plist {
    Str(String),
    Array(Vec<Plist>),
    Dict(BTreeMap<String, Plist>),
}

fn as_dict(value: &Plist) -> Option<&BTreeMap<String, Plist>> {
    match value {
        Plist::Dict(dict) => Some(dict),
        _ => None,
    }
}

fn as_array(value: &Plist) -> Option<&[Plist]> {
    match value {
        Plist::Array(items) => Some(items),
        _ => None,
    }
}

fn as_str(value: &Plist) -> Option<&str> {
    match value {
        Plist::Str(text) => Some(text),
        _ => None,
    }
}

fn str_array(value: Option<&Plist>) -> Vec<String> {
    value
        .and_then(as_array)
        .into_iter()
        .flatten()
        .filter_map(as_str)
        .map(str::to_string)
        .collect()
}

fn parse_plist(text: &str) -> Result<Plist, String> {
    let mut parser = PlistParser {
        input: text.as_bytes(),
        pos: 0,
    };
    parser.parse_value()
}

struct PlistParser<'a> {
    input: &'a [u8],
    pos: usize,
}

impl PlistParser<'_> {
    fn skip_trivia(&mut self) {
        loop {
            while self.pos < self.input.len() && self.input[self.pos].is_ascii_whitespace() {
                self.pos += 1;
            }
            if self.input[self.pos..].starts_with(b"/*") {
                match self.input[self.pos + 2..]
                    .windows(2)
                    .position(|window| window == b"*/")
                {
                    Some(offset) => self.pos += 2 + offset + 2,
                    None => {
                        self.pos = self.input.len();
                        return;
                    }
                }
            } else if self.input[self.pos..].starts_with(b"//") {
                while self.pos < self.input.len() && self.input[self.pos] != b'\n' {
                    self.pos += 1;
                }
            } else {
                return;
            }
        }
    }

    fn peek(&mut self) -> Option<u8> {
        self.skip_trivia();
        self.input.get(self.pos).copied()
    }

    fn parse_value(&mut self) -> Result<Plist, String> {
        match self.peek() {
            Some(b'{') => self.parse_dict(),
            Some(b'(') => self.parse_array(),
            Some(b'"') => Ok(Plist::Str(self.parse_quoted()?)),
            Some(_) => Ok(Plist::Str(self.parse_bare())),
            None => Err("unexpected end of property list".to_string()),
        }
    }

    fn parse_dict(&mut self) -> Result<Plist, String> {
        self.pos += 1;
        let mut dict = BTreeMap::new();
        loop {
            match self.peek() {
                Some(b'}') => {
                    self.pos += 1;
                    return Ok(Plist::Dict(dict));
                }
                None => return Err("unterminated property-list dictionary".to_string()),
                _ => {}
            }
            let key = match self.peek() {
                Some(b'"') => self.parse_quoted()?,
                _ => self.parse_bare(),
            };
            if self.peek() != Some(b'=') {
                return Err(format!("expected '=' after {key}"));
            }
            self.pos += 1;
            let value = self.parse_value()?;
            if self.peek() != Some(b';') {
                return Err(format!("expected ';' after {key}"));
            }
            self.pos += 1;
            dict.insert(key, value);
        }
    }

    fn parse_array(&mut self) -> Result<Plist, String> {
        self.pos += 1;
        let mut items = Vec::new();
        loop {
            match self.peek() {
                Some(b')') => {
                    self.pos += 1;
                    return Ok(Plist::Array(items));
                }
                None => return Err("unterminated property-list array".to_string()),
                Some(b',') => self.pos += 1,
                _ => items.push(self.parse_value()?),
            }
        }
    }

    fn parse_quoted(&mut self) -> Result<String, String> {
        self.pos += 1;
        let mut bytes: Vec<u8> = Vec::new();
        while self.pos < self.input.len() {
            let byte = self.input[self.pos];
            self.pos += 1;
            match byte {
                b'"' => return Ok(String::from_utf8_lossy(&bytes).into_owned()),
                b'\\' => {
                    let Some(escaped) = self.input.get(self.pos).copied() else {
                        break;
                    };
                    self.pos += 1;
                    match escaped {
                        b'n' => bytes.push(b'\n'),
                        b't' => bytes.push(b'\t'),
                        b'r' => bytes.push(b'\r'),
                        b'U' => {
                            let end = (self.pos + 4).min(self.input.len());
                            if let Ok(hex) = std::str::from_utf8(&self.input[self.pos..end]) {
                                if let Ok(code) = u32::from_str_radix(hex, 16) {
                                    let mut buffer = [0u8; 4];
                                    let character = char::from_u32(code).unwrap_or('\u{fffd}');
                                    bytes.extend_from_slice(
                                        character.encode_utf8(&mut buffer).as_bytes(),
                                    );
                                }
                            }
                            self.pos = end;
                        }
                        other => bytes.push(other),
                    }
                }
                other => bytes.push(other),
            }
        }
        Err("unterminated property-list string".to_string())
    }

    fn parse_bare(&mut self) -> String {
        let start = self.pos;
        while self.pos < self.input.len() {
            let byte = self.input[self.pos];
            if byte.is_ascii_whitespace()
                || matches!(byte, b'{' | b'}' | b'(' | b')' | b'=' | b';' | b',' | b'"')
            {
                break;
            }
            if byte == b'/' && matches!(self.input.get(self.pos + 1), Some(b'*') | Some(b'/')) {
                break;
            }
            if byte == b'$' && self.input.get(self.pos + 1) == Some(&b'(') {
                let mut depth = 0usize;
                while self.pos < self.input.len() {
                    match self.input[self.pos] {
                        b'(' => {
                            depth += 1;
                            self.pos += 1;
                        }
                        b')' => {
                            depth = depth.saturating_sub(1);
                            self.pos += 1;
                            if depth == 0 {
                                break;
                            }
                        }
                        _ => self.pos += 1,
                    }
                }
                continue;
            }
            self.pos += 1;
        }
        String::from_utf8_lossy(&self.input[start..self.pos]).into_owned()
    }
}
