//! Skill flow analysis: how a skill's Markdown files load one another.
//!
//! Port of the scan and analysis half of `skill-flow.py` (module docstring
//! there lists the edge kinds, findings and metrics). [`analyze`] returns the
//! data the script prints with `--json` for one skill; serialized with
//! `serde_json::to_string_pretty` it matches that output key for key.
//!
//! Sizes are estimated tokens: one per four characters of the whole file.
//! Offsets are byte offsets throughout; the heuristics only compare them.

mod analyze;
pub mod ledger;
mod render;
mod scan;

use serde::ser::SerializeMap;
use serde::{Serialize, Serializer};
use std::collections::{HashMap, HashSet};
use std::io;
use std::path::{Path, PathBuf};
use std::rc::Rc;

pub use analyze::{StructureRow, dispatch_cost, module_of, structure_rows};
pub use render::{flow_doc, mermaid, text_report};

/// Structure warning: links out of one file.
pub const FAN_OUT: usize = 6;
/// Structure warning: average links per linking file.
pub const DENSITY: usize = 2;
/// Structure warning: a route's cyclomatic complexity.
pub const CYCLOMATIC_WARN: usize = 10;
/// Structure warning and error: a route's cognitive complexity.
pub const COGNITIVE_WARN: usize = 10;
pub const COGNITIVE_ERROR: usize = 15;
/// Structure warning: files reached by one route.
pub const ROUTE_FILES_WARN: usize = 15;
/// Structure warning: total edges in the skill's diagram.
pub const DIAGRAM_EDGES_WARN: usize = 60;

/// What a pointer does: loads the file, hands the request off, or only names it.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum EdgeKind {
    Load,
    Handoff,
    Mention,
    Role,
}

/// A pointer from one Markdown file to another file of the same skill.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct Edge {
    pub from: String,
    pub to: String,
    pub context: String,
    pub conditional: bool,
    pub kind: EdgeKind,
    pub table: bool,
    pub line: usize,
    /// Present for SKILL.md sources only; `Some(None)` serializes as null.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub route: Option<Option<String>>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum ExternalType {
    Agent,
    Skill,
}

/// What a dispatched agent runs: a file, or a skill mode.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
#[serde(untagged)]
pub enum Runs {
    File { file: String },
    Skill { skill: String, mode: String },
}

/// A call that leaves the skill: an inline skill mode or an agent dispatch.
///
/// `skill`, `mode` and `kind` describe skill calls; `runs` describes agent
/// dispatches. `report_order` keeps the script's key order for a dispatch
/// built from an independent `report` span.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct External {
    pub from: String,
    pub external: ExternalType,
    pub target: String,
    pub skill: String,
    pub mode: String,
    pub runs: Option<Runs>,
    pub context: String,
    pub conditional: bool,
    pub kind: EdgeKind,
    pub table: bool,
    pub line: usize,
    pub qualifier: Option<String>,
    pub route: Option<Option<String>>,
    pub(crate) report_order: bool,
}

impl External {
    /// True for a skill call classified as a hand-off.
    pub fn is_handoff(&self) -> bool {
        self.external == ExternalType::Skill && self.kind == EdgeKind::Handoff
    }

    /// True for a SKILL.md call that belongs to `route`: it names no route or this one.
    pub fn serves_route(&self, route: &str) -> bool {
        self.from == "SKILL.md"
            && self
                .route
                .as_ref()
                .and_then(Option::as_deref)
                .is_none_or(|own| own == route)
    }
}

impl Serialize for External {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        let mut map = serializer.serialize_map(None)?;
        map.serialize_entry("from", &self.from)?;
        map.serialize_entry("external", &self.external)?;
        map.serialize_entry("target", &self.target)?;
        match self.external {
            ExternalType::Agent => {
                map.serialize_entry("runs", &self.runs)?;
                map.serialize_entry("context", &self.context)?;
                if self.report_order {
                    map.serialize_entry("table", &self.table)?;
                    map.serialize_entry("line", &self.line)?;
                    map.serialize_entry("conditional", &self.conditional)?;
                } else {
                    map.serialize_entry("conditional", &self.conditional)?;
                    map.serialize_entry("table", &self.table)?;
                    map.serialize_entry("line", &self.line)?;
                }
            }
            ExternalType::Skill => {
                map.serialize_entry("skill", &self.skill)?;
                map.serialize_entry("mode", &self.mode)?;
                map.serialize_entry("context", &self.context)?;
                map.serialize_entry("conditional", &self.conditional)?;
                map.serialize_entry("kind", &self.kind)?;
                map.serialize_entry("table", &self.table)?;
                map.serialize_entry("line", &self.line)?;
                if let Some(qualifier) = &self.qualifier {
                    map.serialize_entry("qualifier", qualifier)?;
                }
            }
        }
        if let Some(route) = &self.route {
            map.serialize_entry("route", route)?;
        }
        map.end()
    }
}

/// An insertion-ordered string-keyed map, serialized as a JSON object.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct OrderedMap<V>(pub Vec<(String, V)>);

impl<V> OrderedMap<V> {
    pub fn get(&self, key: &str) -> Option<&V> {
        self.0.iter().find(|(k, _)| k == key).map(|(_, v)| v)
    }

    pub fn contains_key(&self, key: &str) -> bool {
        self.get(key).is_some()
    }

    pub fn iter(&self) -> impl Iterator<Item = (&String, &V)> {
        self.0.iter().map(|(k, v)| (k, v))
    }
}

impl<V: Serialize> Serialize for OrderedMap<V> {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        let mut map = serializer.serialize_map(Some(self.0.len()))?;
        for (key, value) in &self.0 {
            map.serialize_entry(key, value)?;
        }
        map.end()
    }
}

/// An inline skill mode a route reaches, with the route it resolved to.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct Inline {
    pub target: String,
    pub resolved: String,
}

/// One agent dispatch reachable from a route, with its per-dispatch cost.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct Dispatch {
    pub agent: String,
    pub runs: String,
    pub from: Vec<String>,
    pub conditional: bool,
    pub min_tokens: Option<usize>,
    pub max_tokens: Option<usize>,
    pub files: Vec<DispatchFile>,
}

/// One file an agent reads, with its token estimate and the dispatch source.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct DispatchFile {
    pub file: String,
    pub tokens: usize,
    pub via: String,
}

/// One route of a skill: the files a request reaches and what they cost.
///
/// The fields from `main_min_tokens` on are filled by cross-skill resolution.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct Route {
    pub route: String,
    pub entry: Vec<String>,
    pub files: Vec<String>,
    pub min_files: Vec<String>,
    pub min_tokens: usize,
    pub max_tokens: usize,
    pub handoffs: Vec<String>,
    pub cyclomatic: usize,
    pub cognitive: usize,
    pub lookups: usize,
    pub main_min_tokens: usize,
    pub main_max_tokens: usize,
    pub inline: Vec<Inline>,
    pub unresolved: Vec<String>,
    pub dispatches: Vec<Dispatch>,
}

fn serialize_average<S: Serializer>(value: &f64, serializer: S) -> Result<S::Ok, S::Error> {
    // The script reports an integer 0 when no file links out.
    if *value == 0.0 {
        serializer.serialize_i64(0)
    } else {
        serializer.serialize_f64(*value)
    }
}

/// Link counts between files (SKILL.md excluded) and route complexity maxima.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct Structure {
    pub mutual_links: usize,
    pub mutual_pairs: Vec<[String; 2]>,
    pub max_links_out: usize,
    pub max_links_out_file: Option<String>,
    #[serde(serialize_with = "serialize_average")]
    pub average_links: f64,
    pub linking_files: usize,
    pub links: usize,
    pub links_out: OrderedMap<usize>,
    pub cross_module_edges: usize,
    pub diagram_edges: usize,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub max_route_cyclomatic: Option<usize>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub max_route_cognitive: Option<usize>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub max_route_files: Option<usize>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub max_route_files_route: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct CallerFinding {
    pub file: String,
    pub caller: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct SharedFinding {
    pub file: String,
    pub callers: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct MissingFinding {
    pub from: String,
    pub line: usize,
    pub target: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct CycleFinding {
    pub files: [String; 2],
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct FanOutFinding {
    pub file: String,
    pub links: usize,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct DensityFinding {
    pub average: f64,
}

/// Problems and warnings found in a skill's files.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct Findings {
    pub chain: Vec<CallerFinding>,
    #[serde(rename = "single caller")]
    pub single_caller: Vec<CallerFinding>,
    pub shared: Vec<SharedFinding>,
    pub unreferenced: Vec<String>,
    pub missing: Vec<MissingFinding>,
    pub cycle: Vec<CycleFinding>,
    #[serde(rename = "fan-out")]
    pub fan_out: Vec<FanOutFinding>,
    pub density: Vec<DensityFinding>,
}

/// Everything the flow analysis knows about one skill.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct Analysis {
    pub skill: String,
    pub tokens: OrderedMap<usize>,
    pub references: Vec<String>,
    pub edges: Vec<Edge>,
    pub external: Vec<External>,
    pub routes: Vec<Route>,
    pub structure: Structure,
    pub findings: Findings,
}

/// Analyze the skill in `skill_dir`, resolving inline skill modes and agent
/// dispatches among its sibling skills.
pub fn analyze(skill_dir: &Path) -> io::Result<Analysis> {
    if !skill_dir.join("SKILL.md").is_file() {
        let message = format!("not a skill directory: {}", skill_dir.display());
        return Err(io::Error::new(io::ErrorKind::NotFound, message));
    }
    let skill = skill_dir.canonicalize()?;
    let name = scan::file_name(&skill);
    let parent = skill.parent().map(Path::to_path_buf).unwrap_or_default();
    Ok(Flow::new(parent).resolve(&name))
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Which {
    Min,
    Max,
}

impl Which {
    fn files(self, route: &Route) -> &[String] {
        match self {
            Which::Min => &route.min_files,
            Which::Max => &route.files,
        }
    }
}

type FileSet = HashSet<(String, String)>;

/// The files, inline modes, dispatches and unresolved calls one route reaches.
#[derive(Default)]
struct Journey {
    files: FileSet,
    inline: Vec<(String, String)>,
    /// Each dispatch with the skill whose route made it.
    dispatches: Vec<(String, External)>,
    unresolved: Vec<String>,
}

/// Resolves inline skill modes and agent dispatches among sibling skills.
struct Flow {
    parent: PathBuf,
    skills: HashMap<String, Option<Rc<Analysis>>>,
    definitions: HashMap<String, usize>,
}

impl Flow {
    fn new(parent: PathBuf) -> Self {
        Flow {
            parent,
            skills: HashMap::new(),
            definitions: HashMap::new(),
        }
    }

    fn skill(&mut self, name: &str) -> Option<Rc<Analysis>> {
        if !self.skills.contains_key(name) {
            let path = self.parent.join(name);
            let found = path
                .join("SKILL.md")
                .is_file()
                .then(|| Rc::new(analyze::analyze_skill(&path)));
            self.skills.insert(name.to_string(), found);
        }
        self.skills[name].clone()
    }

    /// Sum (skill, file) pairs; skill "agents" names an agent definition.
    fn tokens(&self, files: &FileSet) -> usize {
        files
            .iter()
            .map(|(skill, file)| self.file_tokens(skill, file))
            .sum()
    }

    fn file_tokens(&self, skill: &str, file: &str) -> usize {
        if skill == "agents" {
            self.definitions.get(file).copied().unwrap_or(0)
        } else if file.ends_with(".md") {
            self.skills
                .get(skill)
                .and_then(Option::as_ref)
                .and_then(|data| data.tokens.get(file))
                .copied()
                .unwrap_or(0)
        } else {
            0
        }
    }

    fn skill_load_via(&self, skill: &str, files: &FileSet) -> Option<String> {
        files
            .iter()
            .filter_map(|(parent_skill, parent_file)| {
                self.skills
                    .get(parent_skill)
                    .and_then(Option::as_ref)
                    .filter(|data| {
                        data.external.iter().any(|external| {
                            external.external == ExternalType::Skill
                                && external.kind == EdgeKind::Load
                                && external.skill == skill
                                && external.from == *parent_file
                        })
                    })
                    .map(|_| format!("skills/{parent_skill}/{parent_file}"))
            })
            .min()
    }

    fn dispatch_file_via(
        &self,
        skill: &str,
        file: &str,
        files: &FileSet,
        agent: &str,
        source: &str,
        source_file: &str,
    ) -> String {
        let dispatched_from = format!("skills/{source}/{source_file}");
        if skill == "agents" {
            return dispatched_from;
        }

        let agent_definition = format!("agents/{}/claude.md", analyze::agent_dir(agent));
        if file == "SKILL.md" && files.contains(&("agents".to_string(), agent.to_string())) {
            return agent_definition;
        }
        if file == "SKILL.md"
            && let Some(via) = self.skill_load_via(skill, files)
        {
            return via;
        }

        if let Some(data) = self.skills.get(skill).and_then(Option::as_ref) {
            let linked_from = data
                .edges
                .iter()
                .filter(|edge| edge.kind == EdgeKind::Load && edge.to == file)
                .filter(|edge| {
                    edge.from == "SKILL.md"
                        || files.iter().any(|(loaded_skill, loaded_file)| {
                            loaded_skill == skill && loaded_file == &edge.from
                        })
                })
                .map(|edge| format!("skills/{skill}/{}", edge.from))
                .min();
            if let Some(via) = linked_from {
                return via;
            }
        }

        dispatched_from
    }

    fn dispatch_files(
        &self,
        files: Option<&FileSet>,
        agent: &str,
        source: &str,
        source_file: &str,
    ) -> Vec<DispatchFile> {
        let Some(files) = files else {
            return Vec::new();
        };
        let mut out: Vec<DispatchFile> = files
            .iter()
            .map(|(skill, file)| DispatchFile {
                file: if skill == "agents" {
                    format!("agents/{}/claude.md", analyze::agent_dir(file))
                } else {
                    format!("skills/{skill}/{file}")
                },
                tokens: self.file_tokens(skill, file),
                via: self.dispatch_file_via(skill, file, files, agent, source, source_file),
            })
            .collect();
        out.sort_by(|left, right| left.file.cmp(&right.file));
        out
    }

    /// External calls reached by a route's min or max files.
    fn calls(&mut self, name: &str, route: &Route, which: Which) -> Vec<External> {
        let Some(data) = self.skill(name) else {
            return Vec::new();
        };
        let files: HashSet<&String> = which.files(route).iter().collect();
        data.external
            .iter()
            .filter(|x| !x.is_handoff())
            .filter(|x| which == Which::Max || !x.conditional)
            .filter(|x| x.serves_route(&route.route) || files.contains(&x.from))
            .cloned()
            .collect()
    }

    /// The files, inline modes, dispatches and unresolved calls of the agent
    /// running a route.
    fn journey(
        &mut self,
        name: &str,
        route: &Route,
        which: Which,
        seen: &HashSet<(String, String)>,
    ) -> Journey {
        let mut seen = seen.clone();
        seen.insert((name.to_string(), route.route.clone()));
        let mut journey = Journey::default();
        journey
            .files
            .insert((name.to_string(), "SKILL.md".to_string()));
        for file in which.files(route) {
            journey.files.insert((name.to_string(), file.clone()));
        }
        for x in self.calls(name, route, which) {
            if x.external == ExternalType::Agent {
                journey.dispatches.push((name.to_string(), x));
            } else if x.kind == EdgeKind::Load {
                self.follow_inline(&x, which, &seen, &mut journey);
            }
        }
        journey
    }

    fn follow_inline(
        &mut self,
        x: &External,
        which: Which,
        seen: &HashSet<(String, String)>,
        journey: &mut Journey,
    ) {
        let other = self.skill(&x.skill);
        let target = other.and_then(|data| {
            analyze::match_route(&data.routes, &x.mode, x.qualifier.as_deref()).cloned()
        });
        let Some(target) = target else {
            journey.unresolved.push(x.target.clone());
            return;
        };
        if seen.contains(&(x.skill.clone(), target.route.clone())) {
            return;
        }
        let resolved = format!("{}: {}", x.skill, target.route);
        journey.inline.push((x.target.clone(), resolved));
        let more = self.journey(&x.skill, &target, which, seen);
        journey.files.extend(more.files);
        journey.inline.extend(more.inline);
        journey.dispatches.extend(more.dispatches);
        journey.unresolved.extend(more.unresolved);
    }
}

impl Flow {
    /// The label of what a dispatch runs and the files its agent reads;
    /// `None` files when the run cannot be resolved.
    fn agent(&mut self, name: &str, x: &External, which: Which) -> (String, Option<FileSet>) {
        let mut files = self.agent_preloads(x);
        let Some(data) = self.skill(name) else {
            return (String::new(), Some(files));
        };
        let loads: Vec<&Edge> = data
            .edges
            .iter()
            .filter(|e| e.kind == EdgeKind::Load)
            .collect();
        let always_only = which == Which::Min;
        match &x.runs {
            Some(Runs::File { file }) => {
                for f in analyze::reach(&loads, std::slice::from_ref(file), always_only) {
                    files.insert((name.to_string(), f));
                }
                (file.clone(), Some(files))
            }
            Some(Runs::Skill { skill, mode }) => self.run_mode(skill, mode, which, files),
            None if x.target == "builder" => {
                let (skill, mode) = analyze::BUILDER;
                self.run_mode(skill, mode, which, files)
            }
            None => {
                let gate: Vec<String> = analyze::GATE
                    .iter()
                    .filter(|f| data.tokens.contains_key(f))
                    .map(|f| f.to_string())
                    .collect();
                let mut reached = gate.clone();
                reached.extend(analyze::reach(
                    &loads,
                    &gate[..gate.len().min(1)],
                    always_only,
                ));
                files.extend(reached.into_iter().map(|f| (name.to_string(), f)));
                ("review gate".to_string(), Some(files))
            }
        }
    }

    fn run_mode(
        &mut self,
        skill: &str,
        mode: &str,
        which: Which,
        mut files: FileSet,
    ) -> (String, Option<FileSet>) {
        let other = self.skill(skill);
        let target = other.and_then(|data| analyze::match_route(&data.routes, mode, None).cloned());
        let Some(target) = target else {
            return (format!("{skill} {mode}"), None);
        };
        let label = format!("{skill}: {}", target.route);
        files.extend(self.journey(skill, &target, which, &HashSet::new()).files);
        (label, Some(files))
    }

    /// The agent definition and the skills it preloads, from the repository's
    /// `agents/` folder (the skills directory's parent).
    fn agent_preloads(&mut self, x: &External) -> FileSet {
        let mut files = FileSet::new();
        let folder = analyze::agent_dir(&x.target);
        let root = self.parent.parent().unwrap_or(&self.parent);
        let definition = root.join("agents").join(folder).join("claude.md");
        if !definition.is_file() {
            return files;
        }
        self.definitions
            .insert(x.target.clone(), scan::tokens(&definition));
        files.insert(("agents".to_string(), x.target.clone()));
        for preload in analyze::preloaded_skills(&scan::read_text(&definition)) {
            if self.skill(&preload).is_some() {
                files.insert((preload, "SKILL.md".to_string()));
            }
        }
        files
    }

    /// Add main-agent costs and per-dispatch subagent costs to each route.
    fn resolve(&mut self, name: &str) -> Analysis {
        let mut data = (*self.skill(name).expect("analyzed skill exists")).clone();
        for route in &mut data.routes {
            let low = self.journey(name, route, Which::Min, &HashSet::new());
            let high = self.journey(name, route, Which::Max, &HashSet::new());
            route.main_min_tokens = self.tokens(&low.files);
            route.main_max_tokens = self.tokens(&high.files);
            route.inline = analyze::dedupe_inline(&high.inline);
            route.unresolved = analyze::sorted_unique(&high.unresolved);
            route.handoffs = analyze::merged_handoffs(route, &data.external);
            route.dispatches = self.dispatches(name, &low, &high);
        }
        data
    }

    fn dispatches(&mut self, name: &str, low: &Journey, high: &Journey) -> Vec<Dispatch> {
        let always: HashSet<(&str, &str, usize)> = low
            .dispatches
            .iter()
            .map(|(source, x)| (source.as_str(), x.from.as_str(), x.line))
            .collect();
        let mut out: Vec<Dispatch> = Vec::new();
        for (source, x) in &high.dispatches {
            let (runs, low_files) = self.agent(source, x, Which::Min);
            let (_, high_files) = self.agent(source, x, Which::Max);
            let min_tokens = low_files.as_ref().map(|files| self.tokens(files));
            let max_tokens = high_files.as_ref().map(|files| self.tokens(files));
            let files = self.dispatch_files(high_files.as_ref(), &x.target, source, &x.from);
            let index = match out
                .iter()
                .position(|d| d.agent == x.target && d.runs == runs)
            {
                Some(index) => index,
                None => {
                    out.push(Dispatch {
                        agent: x.target.clone(),
                        runs,
                        from: Vec::new(),
                        conditional: true,
                        min_tokens,
                        max_tokens,
                        files: Vec::new(),
                    });
                    out.len() - 1
                }
            };
            let item = &mut out[index];
            let place = format!("{}:{}", x.from, x.line);
            let place = if source == name {
                place
            } else {
                format!("{source}/{place}")
            };
            if !item.from.contains(&place) {
                item.from.push(place);
            }
            if always.contains(&(source.as_str(), x.from.as_str(), x.line)) {
                item.conditional = false;
            }
            for file in files {
                match item
                    .files
                    .iter_mut()
                    .find(|existing| existing.file == file.file)
                {
                    Some(existing) if file.via < existing.via => existing.via = file.via,
                    Some(_) => {}
                    None => item.files.push(file),
                }
            }
            item.files.sort_by(|left, right| left.file.cmp(&right.file));
        }
        out
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use tempfile::TempDir;

    fn write(root: &Path, rel: &str, text: &str) {
        let path = root.join(rel);
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        fs::write(path, text).unwrap();
    }

    fn tok(text: &str) -> usize {
        text.chars().count().div_ceil(4)
    }

    const A_SKILL: &str = "| Request | Read |\n|---|---|\n| Do a | `references/a.md` |\n";
    const A_MD: &str = "Then run `varde-b build` for the rest.\n\
                        Dispatch a builder for `references/job.md`.\n";
    const B_SKILL: &str =
        "| Request | Read |\n|---|---|\n| Build thing | `references/build.md` |\n";

    fn two_skills() -> TempDir {
        let tmp = TempDir::new().unwrap();
        let skills = tmp.path().join("skills");
        write(&skills, "varde-a/SKILL.md", A_SKILL);
        write(&skills, "varde-a/references/a.md", A_MD);
        write(&skills, "varde-a/references/job.md", "job steps\n");
        write(&skills, "varde-b/SKILL.md", B_SKILL);
        write(&skills, "varde-b/references/build.md", "build steps here\n");
        tmp
    }

    #[test]
    fn an_inline_mode_adds_the_called_route_to_the_main_agent_cost() {
        let tmp = two_skills();
        let a = analyze(&tmp.path().join("skills/varde-a")).unwrap();
        let route = &a.routes[0];
        assert_eq!(route.route, "Do a");
        assert_eq!(
            route.inline,
            [Inline {
                target: "varde-b build".to_string(),
                resolved: "varde-b: Build thing".to_string()
            }]
        );
        let own = tok(A_SKILL) + tok(A_MD);
        assert_eq!(route.min_tokens, own);
        // job.md is only a mention-style target of the dispatch, so it is not loaded.
        assert_eq!(route.files, ["references/a.md"]);
        let called = tok(B_SKILL) + tok("build steps here\n");
        assert_eq!(route.main_min_tokens, own + called);
        assert_eq!(route.main_max_tokens, own + called);
        assert!(route.unresolved.is_empty());
    }

    #[test]
    fn a_dispatch_costs_its_definition_preloaded_skills_and_file() {
        let tmp = two_skills();
        let definition = "---\nskills: varde-b\n---\nbody\n";
        write(tmp.path(), "agents/varde-builder/claude.md", definition);
        let a = analyze(&tmp.path().join("skills/varde-a")).unwrap();
        let dispatches = &a.routes[0].dispatches;
        assert_eq!(dispatches.len(), 1);
        let d = &dispatches[0];
        assert_eq!(
            (d.agent.as_str(), d.runs.as_str()),
            ("builder", "references/job.md")
        );
        assert_eq!(d.from, ["references/a.md:2"]);
        assert!(!d.conditional);
        let cost = tok(definition) + tok(B_SKILL) + tok("job steps\n");
        assert_eq!((d.min_tokens, d.max_tokens), (Some(cost), Some(cost)));
        assert_eq!(dispatch_cost(d), format!("~{cost}"));
    }

    #[test]
    fn an_unknown_inline_mode_is_unresolved() {
        let tmp = two_skills();
        write(
            &tmp.path().join("skills"),
            "varde-a/references/a.md",
            "Run `varde-b zzz`.\n",
        );
        let a = analyze(&tmp.path().join("skills/varde-a")).unwrap();
        assert_eq!(a.routes[0].unresolved, ["varde-b zzz"]);
        assert!(a.routes[0].inline.is_empty());
    }

    #[test]
    fn a_directory_without_skill_md_is_not_a_skill() {
        let tmp = TempDir::new().unwrap();
        let error = analyze(tmp.path()).unwrap_err();
        assert_eq!(error.kind(), io::ErrorKind::NotFound);
    }
}
