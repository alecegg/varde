//! Advisory execution waves from task frontmatter and read-only code reach.
use crate::execution_wave_paths::{canonical_path, compile_unit};
use crate::execution_wave_tools as tools;
use serde_json::{Value, json};
use serde_yaml::Value as Yaml;
use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::path::Path;
use varde_workflow_core::frontmatter;

type Paths = BTreeSet<String>;
const OWNERSHIP: [&str; 4] = ["modifies", "creates", "renames", "verification_resources"];

#[derive(Default)]
struct Task {
    status: String,
    dependencies: Vec<String>,
    kind: String,
    posture: String,
    writes: Paths,
    modifies: Vec<String>,
    renames: Paths,
    creates: Paths,
    body: String,
    sources: Paths,
    resources: Paths,
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

fn load_task(path: &Path) -> Result<Task, String> {
    let bytes = fs::read(path).map_err(|error| error.to_string())?;
    let (fm, body) = frontmatter::parse(&bytes).map_err(|error| error.to_string())?;
    let modifies: Vec<_> = list(&fm, "modifies")?
        .iter()
        .map(|value| norm(value))
        .collect();
    let creates: Paths = list(&fm, "creates")?
        .iter()
        .map(|value| norm(value))
        .collect();
    let mut task = Task {
        status: scalar(&fm, "status", "todo", false)?,
        dependencies: list(&fm, "depends_on")?,
        kind: scalar(&fm, "kind", "", true)?,
        posture: scalar(&fm, "posture", "", true)?,
        sources: modifies.iter().cloned().collect(),
        writes: modifies
            .iter()
            .cloned()
            .chain(creates.iter().cloned())
            .collect(),
        modifies,
        creates,
        body,
        resources: list(&fm, "verification_resources")?.into_iter().collect(),
        missing: OWNERSHIP
            .iter()
            .filter(|key| fm.get(**key).is_none())
            .map(|key| (*key).into())
            .collect(),
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
        .map(|value| canonical_path(root, value.as_ref()))
        .collect()
}

pub fn execution_wave(plan: &Path, root: &Path, workers: usize) -> Result<Value, WaveError> {
    if !(1..=3).contains(&workers) {
        return Err(WaveError::Input("--max-workers must be 1..3".into()));
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
    Ok(resolve(&tasks, &root, workers))
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

fn resolve(tasks: &BTreeMap<String, Task>, root: &Path, workers: usize) -> Value {
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
    let mut conflicts = Vec::new();
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
    let have_cli = tools::available();
    if !have_cli {
        reasons.push("varde-code unavailable: independence cannot be checked".into());
    }
    let mut uncertain = false;
    let mut writes = BTreeMap::new();
    let mut sources = BTreeMap::new();
    let mut markdown = BTreeMap::new();
    let mut renames = BTreeMap::new();
    for id in &ready {
        let task = &tasks[id];
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
                canonical_set(root, &task.sources)?,
                canonical_set(
                    root,
                    task.modifies
                        .iter()
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
            reasons.push(format!("{id}: empty modifies/creates/renames"));
            continue;
        }
        if !have_cli {
            continue;
        }
        let mut area = owned.clone();
        let mut known = true;
        for path in &sources[id] {
            if !root.join(path).exists() {
                continue;
            }
            match tools::blast_radius(root, path) {
                None => {
                    reasons.push(format!("{id}: blast_radius failed for {path}"));
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
    let mut wave: Vec<String> = Vec::new();
    for id in candidates {
        let mut clash = false;
        for other in &wave {
            let shared: Paths = writes[&id]
                .intersection(&reach[other])
                .cloned()
                .chain(writes[other].intersection(&reach[&id]).cloned())
                .collect();
            let resources: Paths = tasks[&id]
                .resources
                .intersection(&tasks[other].resources)
                .cloned()
                .collect();
            if !shared.is_empty() || !resources.is_empty() {
                conflicts.push(json!({"tasks":[other,id],"files":shared,"resources":resources}));
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
    let units: Vec<Paths> = wave
        .iter()
        .map(|id| {
            writes
                .get(id)
                .into_iter()
                .flatten()
                .filter_map(|path| compile_unit(root, path))
                .collect()
        })
        .collect();
    let shared_unit = units.iter().enumerate().any(|(index, unit)| {
        units[index + 1..]
            .iter()
            .any(|other| !unit.is_disjoint(other))
    });
    let special = wave
        .iter()
        .any(|id| tasks[id].kind == "spike" || tasks[id].posture == "refactor");
    let mode = if wave.len() <= 1 {
        "single"
    } else if shared_unit || special {
        "worktree"
    } else {
        "shared"
    };
    json!({"schema_version":3,"ready":ready,"blocked_by_dep":blocked,"next_wave":wave,"wave_mode":mode,"conflicts":conflicts,"reasons":reasons})
}
