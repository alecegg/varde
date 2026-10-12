//! Advisory execution waves from task frontmatter and read-only code reach.
use crate::execution_wave_paths::{
    canonical_declaration, declarations_overlap, matches_declaration,
};
use crate::execution_wave_tools as tools;
use crate::task_ownership::OwnershipDeclarations;
use serde_json::{Value, json};
use serde_yaml::Value as Yaml;
use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::path::Path;
use varde_contracts::ImpactQuery;
use varde_workflow_core::frontmatter;

type Paths = BTreeSet<String>;
const OWNERSHIP: [&str; 4] = ["owns", "modifies", "creates", "renames"];

#[derive(Default)]
struct Task {
    status: String,
    dependencies: Vec<String>,
    writes: Paths,
    owns: Paths,
    modifies: Vec<String>,
    renames: Paths,
    creates: Paths,
    body: String,
    sources: Paths,
    missing: Vec<String>,
}

fn list(fm: &Yaml, key: &str) -> Result<Vec<String>, String> {
    let Some(value) = fm.get(key) else {
        return Ok(Vec::new());
    };
    let items = value
        .as_sequence()
        .ok_or_else(|| format!("{key} must be a list of strings"))?;
    items
        .iter()
        .map(|item| {
            item.as_str()
                .map(str::to_owned)
                .ok_or_else(|| format!("{key} must contain only strings"))
        })
        .collect()
}

fn scalar(fm: &Yaml, key: &str, default: &str, optional: bool) -> Result<String, String> {
    match fm.get(key) {
        None => Ok(default.into()),
        Some(Yaml::Null) if optional => Ok(default.into()),
        Some(value) => value
            .as_str()
            .map(str::to_owned)
            .ok_or_else(|| format!("{key} must be a string")),
    }
}

fn norm(path: &str) -> String {
    path.trim().trim_start_matches("./").to_owned()
}

/// Plan-level paths any task may touch (`shared:`, with legacy `generated:`).
/// They are resolved by the merge queue, not by wave conflicts.
fn load_shared(plan: &Path) -> Result<Paths, String> {
    let path = plan.join("plan.md");
    let bytes = match fs::read(&path) {
        Ok(bytes) => bytes,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(Paths::new()),
        Err(error) => return Err(format!("{}: {error}", path.display())),
    };
    let (frontmatter, _) =
        frontmatter::parse(&bytes).map_err(|error| format!("{}: {error}", path.display()))?;
    let mut paths = Paths::new();
    for key in ["shared", "generated"] {
        paths.extend(list(&frontmatter, key)?.iter().map(|value| norm(value)));
    }
    Ok(paths)
}

fn load_task(path: &Path) -> Result<Task, String> {
    let bytes = fs::read(path).map_err(|error| error.to_string())?;
    let (fm, body) = frontmatter::parse(&bytes).map_err(|error| error.to_string())?;
    let owns: Paths = list(&fm, "owns")?.iter().map(|value| norm(value)).collect();
    let modifies: Vec<_> = list(&fm, "modifies")?
        .iter()
        .map(|value| norm(value))
        .collect();
    let creates: Paths = list(&fm, "creates")?
        .iter()
        .map(|value| norm(value))
        .collect();
    scalar(&fm, "kind", "", true)?;
    scalar(&fm, "posture", "", true)?;
    let mut task = Task {
        status: scalar(&fm, "status", "todo", false)?,
        dependencies: list(&fm, "depends_on")?,
        sources: owns
            .iter()
            .chain(&modifies)
            .filter(|path| !path.contains('*') && !path.ends_with('/'))
            .cloned()
            .collect(),
        writes: owns
            .iter()
            .cloned()
            .chain(modifies.iter().cloned())
            .chain(creates.iter().cloned())
            .collect(),
        owns,
        modifies,
        creates,
        body,
        missing: if OWNERSHIP.iter().any(|key| fm.get(*key).is_some()) {
            Vec::new()
        } else {
            vec!["owns (or legacy modifies/creates/renames)".into()]
        },
        ..Task::default()
    };
    for rename in list(&fm, "renames")? {
        let parts: Vec<_> = rename.split("->").collect();
        if parts.len() != 2 || parts.iter().any(|part| part.trim().is_empty()) {
            let warning = "renames (expected \"old/path -> new/path\")".to_owned();
            if !task.missing.contains(&warning) {
                task.missing.push(warning);
            }
            continue;
        }
        let old = norm(parts[0]);
        let new = norm(parts[1]);
        task.writes.extend([old.clone(), new.clone()]);
        task.sources.extend([old.clone(), new.clone()]);
        task.renames.extend([old, new.clone()]);
        task.creates.insert(new);
    }
    Ok(task)
}

fn load_tasks(plan: &Path) -> Result<BTreeMap<String, Task>, String> {
    let directory = plan.join("tasks");
    if !directory.is_dir() {
        return Err(format!("{}/tasks is not a directory", plan.display()));
    }
    let mut tasks = BTreeMap::new();
    for entry in fs::read_dir(directory).map_err(|error| error.to_string())? {
        let path = entry.map_err(|error| error.to_string())?.path();
        if path.extension().and_then(|value| value.to_str()) != Some("md") {
            continue;
        }
        let id = path
            .file_stem()
            .and_then(|value| value.to_str())
            .ok_or("task filename must be UTF-8")?;
        let task = load_task(&path).map_err(|error| format!("{}: {error}", path.display()))?;
        tasks.insert(id.into(), task);
    }
    Ok(tasks)
}

/// Read the ownership declarations for every task using the same parser as
/// execution-wave planning. Each entry carries `(id, status, declarations)`.
pub(crate) fn ownership_declarations(
    plan: &Path,
) -> Result<Vec<(String, String, OwnershipDeclarations)>, String> {
    if !plan.join("tasks").exists() {
        return Ok(Vec::new());
    }
    let tasks = load_tasks(plan)?;
    let shared = load_shared(plan)?;
    Ok(tasks
        .into_iter()
        .map(|(id, task)| {
            let renamed_sources = task.renames.difference(&task.creates).cloned();
            let mut owned: Paths = task.modifies.into_iter().collect();
            owned.extend(renamed_sources);
            (
                id,
                task.status,
                OwnershipDeclarations {
                    owned,
                    owns: task.owns,
                    creates: task.creates,
                    generated: shared.clone(),
                },
            )
        })
        .collect())
}

fn has_cycle(tasks: &BTreeMap<String, Task>) -> bool {
    fn visit<'a>(
        id: &'a str,
        tasks: &'a BTreeMap<String, Task>,
        open: &mut BTreeSet<&'a str>,
        closed: &mut BTreeSet<&'a str>,
    ) -> bool {
        if closed.contains(id) {
            return false;
        }
        if !open.insert(id) {
            return true;
        }
        for dep in &tasks[id].dependencies {
            if tasks.contains_key(dep) && visit(dep, tasks, open, closed) {
                return true;
            }
        }
        open.remove(id);
        closed.insert(id);
        false
    }
    let mut open = BTreeSet::new();
    let mut closed = BTreeSet::new();
    tasks
        .keys()
        .any(|id| visit(id, tasks, &mut open, &mut closed))
}

fn mentions(body: &str, path: &str) -> bool {
    fn boundary(character: char, left: bool, references: bool) -> bool {
        character.is_ascii_alphanumeric()
            || "_.-".contains(character)
            || (character == '/' && (!left || !references))
    }
    let mut spellings = BTreeSet::from([norm(path)]);
    let parts: Vec<_> = path.split('/').collect();
    if let Some(index) = parts.iter().position(|part| *part == "references") {
        spellings.insert(parts[index..].join("/"));
    }
    spellings.extend(
        spellings
            .clone()
            .into_iter()
            .map(|value| format!("./{value}")),
    );
    spellings.iter().any(|spelling| {
        !spelling.is_empty()
            && body.match_indices(spelling).any(|(index, _)| {
                let before = body[..index].chars().next_back();
                let after = body[index + spelling.len()..].chars().next();
                !before.is_some_and(|character| {
                    boundary(character, true, spelling.starts_with("references/"))
                }) && !after.is_some_and(|character| boundary(character, false, false))
            })
    })
}

fn canonical_set(
    root: &Path,
    values: impl IntoIterator<Item = impl AsRef<str>>,
) -> Result<Paths, String> {
    values
        .into_iter()
        .map(|value| canonical_declaration(root, value.as_ref()))
        .collect()
}

fn overlapping_paths(left: &Paths, right: &Paths) -> Paths {
    let mut overlaps = Paths::new();
    for a in left {
        for b in right {
            if !declarations_overlap(a, b) {
                continue;
            }
            let a_is_path = !a.contains('*') && !a.ends_with('/');
            let b_is_path = !b.contains('*') && !b.ends_with('/');
            let path = if a_is_path && matches_declaration(b, a) {
                a
            } else if b_is_path && matches_declaration(a, b) {
                b
            } else {
                a
            };
            overlaps.insert(path.clone());
        }
    }
    overlaps
}

pub fn execution_wave(
    plan: &Path,
    root: &Path,
    workers: usize,
    impact: Option<&'static dyn ImpactQuery>,
) -> Result<Value, WaveError> {
    if workers == 0 {
        return Err(WaveError::Input(
            "--max-workers must be at least 1; omit --max-workers to use [orchestration] builders"
                .into(),
        ));
    }
    let tasks = load_tasks(plan).map_err(WaveError::Input)?;
    if has_cycle(&tasks) {
        return Err(WaveError::Cycle);
    }
    let root = root
        .canonicalize()
        .map_err(|error| WaveError::Input(error.to_string()))?;
    if !root.is_dir() {
        return Err(WaveError::Input("repo root is not a directory".into()));
    }
    Ok(resolve(&tasks, &root, workers, impact))
}

pub enum WaveError {
    Input(String),
    Cycle,
}
impl std::fmt::Display for WaveError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Input(message) => formatter.write_str(message),
            Self::Cycle => formatter.write_str("depends_on contains a cycle"),
        }
    }
}

fn resolve(
    tasks: &BTreeMap<String, Task>,
    root: &Path,
    workers: usize,
    impact: Option<&'static dyn ImpactQuery>,
) -> Value {
    let ready: Vec<_> = tasks
        .iter()
        .filter(|(_, task)| {
            task.status == "todo"
                && task
                    .dependencies
                    .iter()
                    .all(|dep| tasks.get(dep).is_some_and(|task| task.status == "done"))
        })
        .map(|(id, _)| id.clone())
        .collect();
    let mut reasons = Vec::new();
    let mut blocked = Vec::new();
    for (id, task) in tasks.iter().filter(|(_, task)| task.status == "todo") {
        for dependency in &task.dependencies {
            let why = match tasks.get(dependency) {
                None => Some("missing"),
                Some(task) if task.status == "blocked" => Some("blocked"),
                _ => None,
            };
            if let Some(why) = why {
                blocked.push(json!({"task":id,"dependency":dependency,"reason":why}));
                reasons.push(format!("{id}: dependency {dependency} is {why}"));
            }
        }
    }
    let mut held = BTreeSet::new();
    for id in &ready {
        for (creator, task) in tasks
            .iter()
            .filter(|(creator, task)| *creator != id && task.status != "done")
        {
            for path in &task.creates {
                if mentions(&tasks[id].body, path) {
                    held.insert(id.clone());
                    reasons.push(format!(
                        "{id}: mentions {path} created by {creator}; add depends_on"
                    ));
                }
            }
        }
    }
    if impact.is_none() {
        reasons.push("varde map unavailable: independence cannot be checked".into());
    }
    let mut uncertain = false;
    let mut writes = BTreeMap::new();
    let mut sources = BTreeMap::new();
    let mut markdown = BTreeMap::new();
    let mut renames = BTreeMap::new();
    for id in &ready {
        let task = &tasks[id];
        if task
            .modifies
            .iter()
            .chain(&task.renames)
            .any(|path| path.contains('*') || path.ends_with('/'))
        {
            uncertain = true;
            reasons.push(format!(
                "{id}: source ownership pattern has unknown dependency reach"
            ));
        }
        if !task.missing.is_empty() {
            uncertain = true;
            reasons.push(format!(
                "{id}: missing ownership metadata: {}",
                task.missing.join(", ")
            ));
            continue;
        }
        let identities = (|| {
            Ok::<_, String>((
                canonical_set(root, &task.writes)?,
                canonical_set(
                    root,
                    task.sources
                        .iter()
                        .filter(|path| !path.contains('*') && !path.ends_with('/')),
                )?,
                canonical_set(
                    root,
                    task.owns
                        .iter()
                        .chain(&task.modifies)
                        .filter(|path| path.to_lowercase().ends_with(".md")),
                )?,
                canonical_set(root, &task.renames)?,
            ))
        })();
        match identities {
            Ok((w, s, m, r)) => {
                writes.insert(id.clone(), w);
                sources.insert(id.clone(), s);
                markdown.insert(id.clone(), m);
                renames.insert(id.clone(), r);
            }
            Err(error) => {
                uncertain = true;
                reasons.push(format!(
                    "{id}: ownership path identity is uncertain: {error}"
                ));
            }
        }
    }
    let mut reach = BTreeMap::new();
    let mut candidates = Vec::new();
    for id in &ready {
        if held.contains(id) {
            continue;
        }
        let Some(owned) = writes.get(id) else {
            continue;
        };
        if owned.is_empty() {
            reasons.push(format!("{id}: empty ownership declarations"));
            continue;
        }
        let Some(impact) = impact else {
            continue;
        };
        let mut area = owned.clone();
        let mut known = true;
        for path in &sources[id] {
            if !root.join(path).exists() {
                continue;
            }
            match tools::blast_radius(impact, root, path) {
                None => {
                    reasons.push(format!(
                        "{id}: blast_radius failed for {path} (impact query unavailable; if the code index is missing run: varde map build --repo-root {})",
                        root.display()
                    ));
                    known = false;
                    break;
                }
                Some(found) if !found.is_empty() => area.extend(found),
                Some(_) if !markdown[id].contains(path) || renames[id].contains(path) => {
                    match tools::basename_references(root, path) {
                        Some(found) => area.extend(found),
                        None => {
                            reasons.push(format!("{id}: git grep failed for {path}"));
                            known = false;
                            break;
                        }
                    }
                }
                Some(_) => {}
            }
        }
        if known {
            reach.insert(id.clone(), area);
            candidates.push(id.clone());
        }
    }
    let mut conflicts: BTreeMap<(String, String), Paths> = BTreeMap::new();
    for (index, left) in ready.iter().enumerate() {
        for right in ready.iter().skip(index + 1) {
            let (Some(left_writes), Some(right_writes)) = (writes.get(left), writes.get(right))
            else {
                continue;
            };
            let files = overlapping_paths(left_writes, right_writes);
            if !files.is_empty() {
                conflicts.insert((left.clone(), right.clone()), files);
            }
        }
    }
    let mut wave: Vec<String> = Vec::new();
    for id in candidates {
        let mut clash = false;
        for other in &wave {
            let mut shared = overlapping_paths(&writes[&id], &reach[other]);
            shared.extend(overlapping_paths(&writes[other], &reach[&id]));
            if !shared.is_empty() {
                conflicts
                    .entry((other.clone(), id.clone()))
                    .or_default()
                    .extend(shared);
                clash = true;
                break;
            }
        }
        if !clash && wave.len() < workers {
            wave.push(id);
        }
    }
    if wave.len() < 2 || uncertain {
        wave = ready
            .iter()
            .filter(|id| !held.contains(*id))
            .take(1)
            .cloned()
            .collect();
    }
    let mode = if wave.is_empty() {
        "single"
    } else {
        "worktree"
    };
    let conflicts: Vec<_> = conflicts
        .into_iter()
        .map(|((left, right), files)| json!({"tasks":[left,right],"files":files}))
        .collect();
    json!({"schema_version":3,"ready":ready,"blocked_by_dep":blocked,"next_wave":wave,"wave_mode":mode,"conflicts":conflicts,"reasons":reasons})
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::PathBuf;

    struct FakeImpact<F>(F);

    impl<F> ImpactQuery for FakeImpact<F>
    where
        F: Fn(&Path) -> Option<Vec<PathBuf>> + Send + Sync,
    {
        fn dependents(&self, _repo_root: &Path, file: &Path) -> Option<Vec<PathBuf>> {
            (self.0)(file)
        }
    }

    fn fake(
        impact: impl Fn(&Path) -> Option<Vec<PathBuf>> + Send + Sync + 'static,
    ) -> Option<&'static dyn ImpactQuery> {
        Some(Box::leak(Box::new(FakeImpact(impact))))
    }

    /// A plan with todo tasks alpha, beta and gamma each owning `src/<id>`.
    fn fixture(tag: &str) -> PathBuf {
        let root = std::env::temp_dir().join(format!("wave-unit-{tag}-{}", std::process::id()));
        let _ = fs::remove_dir_all(&root);
        fs::create_dir_all(root.join("tasks")).unwrap();
        fs::create_dir_all(root.join("src")).unwrap();
        for id in ["alpha", "beta", "gamma"] {
            fs::write(root.join(format!("src/{id}")), "").unwrap();
            fs::write(
                root.join(format!("tasks/{id}.md")),
                format!("---\nstatus: todo\ndepends_on: []\nmodifies: [src/{id}]\ncreates: []\nrenames: []\nverification_resources: []\n---\n"),
            )
            .unwrap();
        }
        root.canonicalize().unwrap()
    }

    fn wave(root: &Path, impact: Option<&'static dyn ImpactQuery>) -> Value {
        match execution_wave(root, root, 3, impact) {
            Ok(data) => data,
            Err(error) => panic!("{error}"),
        }
    }

    fn reasons(data: &Value) -> Vec<String> {
        data["reasons"]
            .as_array()
            .unwrap()
            .iter()
            .map(|reason| reason.as_str().unwrap().to_string())
            .collect()
    }

    #[test]
    fn unknown_reach_for_every_task_runs_only_the_first() {
        let root = fixture("all-unknown");
        let data = wave(&root, fake(|_| None));
        assert_eq!(data["next_wave"], serde_json::json!(["alpha"]));
        let expected_reason = format!(
            "alpha: blast_radius failed for src/alpha (impact query unavailable; if the code index is missing run: varde map build --repo-root {})",
            root.display()
        );
        assert!(reasons(&data).contains(&expected_reason));
    }

    #[test]
    fn failure_for_one_task_is_local_and_known_independent_tasks_still_run() {
        let root = fixture("local-failure");
        let data = wave(
            &root,
            fake(|file| {
                if file.ends_with("src/alpha") {
                    None
                } else {
                    Some(vec![PathBuf::from("src/unwritten-consumer")])
                }
            }),
        );
        assert_eq!(data["next_wave"], serde_json::json!(["beta", "gamma"]));
    }

    #[test]
    fn missing_impact_capability_is_reported_and_serializes_the_wave() {
        let root = fixture("no-impact");
        let data = wave(&root, None);
        assert_eq!(data["next_wave"], serde_json::json!(["alpha"]));
        assert!(
            reasons(&data)
                .iter()
                .any(|reason| reason.contains("varde map unavailable"))
        );
    }

    #[test]
    fn dependents_reported_by_the_impact_query_join_the_owned_area() {
        let root = fixture("dependents");
        let data = wave(
            &root,
            fake(|file| {
                let reach = match file.file_name().and_then(|name| name.to_str()) {
                    Some("alpha") => "src/beta",
                    Some("beta") => "src/consumer-of-beta",
                    _ => "src/consumer-of-gamma",
                };
                Some(vec![PathBuf::from(reach)])
            }),
        );
        assert_eq!(data["next_wave"], serde_json::json!(["alpha", "gamma"]));
    }
}
