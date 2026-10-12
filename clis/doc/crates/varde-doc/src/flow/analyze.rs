//! Map one skill's own files and routes, and measure the result: edges,
//! routes with their cost and complexity, findings and structure.

use super::scan::{self, Body, Scanned, SkillDir};
use super::{
    Analysis, COGNITIVE_ERROR, COGNITIVE_WARN, CYCLOMATIC_WARN, CallerFinding, CycleFinding,
    DENSITY, DIAGRAM_EDGES_WARN, DensityFinding, Dispatch, Edge, EdgeKind, External, FAN_OUT,
    FanOutFinding, Findings, Inline, MissingFinding, OrderedMap, ROUTE_FILES_WARN, Route,
    SharedFinding, Structure,
};
use fancy_regex::Regex;
use std::collections::{BTreeMap, BTreeSet, HashMap, HashSet, VecDeque};
use std::fs;
use std::path::Path;
use std::sync::LazyLock;

const DIRS: [&str; 3] = ["references", "scripts", "assets"];
/// The file a gate reviewer reads.
pub(super) const GATE: [&str; 1] = ["references/review-gates.md"];
/// The builder runs this skill's route with this word.
pub(super) const BUILDER: (&str, &str) = ("varde-change", "builder");

static SKIP: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"(?i)\bskips?\b").expect("flow patterns are valid"));
static PRELOADS: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"(?m)^skills:\s*(.+)$").expect("flow patterns are valid"));

// ---- Small helpers --------------------------------------------------------

/// A file's module: scripts/assets by directory, else the text before the
/// first hyphen of its stem.
pub fn module_of(path: &str) -> String {
    let top = path.split('/').next().unwrap_or("");
    if top == "scripts" || top == "assets" {
        return top.to_string();
    }
    let name = path.rsplit('/').next().unwrap_or("");
    let stem = stem_of(name);
    stem.split('-').next().unwrap_or("").to_string()
}

fn stem_of(path: &str) -> String {
    Path::new(path)
        .file_stem()
        .map(|stem| stem.to_string_lossy().into_owned())
        .unwrap_or_default()
}

/// The agent definition folder under `agents/` for a dispatch target.
pub(super) fn agent_dir(target: &str) -> &'static str {
    match target {
        "builder" => "varde-builder",
        _ => "varde-reviewer",
    }
}

/// The skills named by the `skills:` line of an agent definition's frontmatter.
pub(super) fn preloaded_skills(definition: &str) -> Vec<String> {
    let head = definition.split("\n---").next().unwrap_or("");
    let Some(caps) = PRELOADS.captures(head).ok().flatten() else {
        return Vec::new();
    };
    caps[1]
        .split(',')
        .map(|name| name.trim().to_string())
        .collect()
}

fn unique(items: impl IntoIterator<Item = String>) -> Vec<String> {
    let mut seen = HashSet::new();
    items
        .into_iter()
        .filter(|item| seen.insert(item.clone()))
        .collect()
}

pub(super) fn sorted_unique(items: &[String]) -> Vec<String> {
    items
        .iter()
        .cloned()
        .collect::<BTreeSet<_>>()
        .into_iter()
        .collect()
}

/// Inline modes in first-seen order; a repeated target keeps its first
/// position and takes the last route it resolved to.
pub(super) fn dedupe_inline(pairs: &[(String, String)]) -> Vec<Inline> {
    let mut out: Vec<Inline> = Vec::new();
    for (target, resolved) in pairs {
        match out.iter_mut().find(|inline| inline.target == *target) {
            Some(inline) => inline.resolved = resolved.clone(),
            None => out.push(Inline {
                target: target.clone(),
                resolved: resolved.clone(),
            }),
        }
    }
    out
}

/// A route's own hand-offs plus the hand-off calls it reaches.
pub(super) fn merged_handoffs(route: &Route, external: &[External]) -> Vec<String> {
    let reached = external
        .iter()
        .filter(|x| x.is_handoff())
        .filter(|x| x.serves_route(&route.route) || route.files.contains(&x.from));
    let mut all: BTreeSet<String> = route.handoffs.iter().cloned().collect();
    all.extend(reached.map(|x| x.target.clone()));
    all.into_iter().collect()
}

/// Python-style `round(x, 2)`: round half to even on the exact binary value.
fn round2(value: f64) -> f64 {
    format!("{value:.2}").parse().unwrap_or(value)
}

/// A float as Python prints it: `2.0`, not `2`; the integer zero as `0`.
fn py_float(value: f64) -> String {
    if value == 0.0 {
        "0".to_string()
    } else if value.fract() == 0.0 {
        format!("{value:.1}")
    } else {
        value.to_string()
    }
}

// ---- Routes ---------------------------------------------------------------

/// The route whose name or entry file stem holds all the qualifier words, else
/// the route a mode names by entry stem or label word.
pub(super) fn match_route<'a>(
    routes: &'a [Route],
    mode: &str,
    qualifier: Option<&str>,
) -> Option<&'a Route> {
    let words = word_set(qualifier.unwrap_or(""));
    let candidates: Vec<&Route> = if words.is_empty() {
        routes.iter().collect()
    } else {
        routes.iter().filter(|r| names_all(r, &words)).collect()
    };
    if !words.is_empty() && candidates.is_empty() {
        return None;
    }
    let stemmed = candidates
        .iter()
        .copied()
        .filter(|r| r.entry.iter().any(|f| stem_of(f) == mode));
    if let Some(found) = fewest_entries(stemmed) {
        return Some(found);
    }
    let word = Regex::new(&format!(r"(?i)\b{}\b", fancy_regex::escape(mode))).ok()?;
    let labeled = candidates
        .iter()
        .copied()
        .find(|r| scan::matches(&word, &r.route));
    labeled.or_else(|| {
        if words.is_empty() {
            None
        } else {
            fewest_entries(candidates.iter().copied())
        }
    })
}

fn word_set(text: &str) -> HashSet<String> {
    text.to_lowercase()
        .split(|c: char| !(c.is_ascii_lowercase() || c.is_ascii_digit()))
        .filter(|word| !word.is_empty())
        .map(str::to_string)
        .collect()
}

fn names_all(route: &Route, words: &HashSet<String>) -> bool {
    std::iter::once(route.route.clone())
        .chain(route.entry.iter().map(|f| stem_of(f)))
        .any(|name| words.is_subset(&word_set(&name)))
}

/// The route with the fewest entry files; the first of equals.
fn fewest_entries<'a>(routes: impl Iterator<Item = &'a Route>) -> Option<&'a Route> {
    let mut best: Option<&Route> = None;
    for route in routes {
        if best.is_none_or(|b| route.entry.len() < b.entry.len()) {
            best = Some(route);
        }
    }
    best
}

/// Files this file's "skip" sentences name, to drop from its route.
fn skip_targets(dir: &SkillDir, source: &str) -> Vec<String> {
    let text = dir.read(source).split('\n').collect::<Vec<_>>().join(" ");
    let mut resolved = Vec::new();
    for found in SKIP.find_iter(&text).flatten() {
        let (_, stop) = scan::bounds(&text, found.start(), &scan::END);
        let rest = scan::slice(&text, found.end(), stop);
        let pointer = scan::targets(rest, false).into_iter().find(|t| !t.is_link);
        let Some(pointer) = pointer else { continue };
        if let (Some(rel), false) = scan::resolve(dir, source, &pointer.raw, false) {
            resolved.push(rel);
        }
    }
    resolved
}

/// Files reached from `starts` along `loads`, breadth first; with
/// `always_only`, only along unconditional loads. SKILL.md is never included.
pub(super) fn reach(loads: &[&Edge], starts: &[String], always_only: bool) -> Vec<String> {
    let mut reached: Vec<String> = Vec::new();
    let mut todo: VecDeque<String> = unique(starts.iter().cloned()).into();
    while let Some(current) = todo.pop_front() {
        if reached.contains(&current) || current == "SKILL.md" {
            continue;
        }
        let onward = loads
            .iter()
            .filter(|e| e.from == current && !(always_only && e.conditional))
            .map(|e| e.to.clone());
        todo.extend(onward);
        reached.push(current);
    }
    reached
}

/// Shortest hop count along load edges; a start is depth 1, SKILL.md is 0.
fn depths(loads: &[&Edge], starts: &[String]) -> HashMap<String, usize> {
    let mut depth: HashMap<String, usize> = HashMap::new();
    let mut todo: VecDeque<(String, usize)> = unique(starts.iter().cloned())
        .into_iter()
        .map(|s| (s, 1))
        .collect();
    while let Some((current, hop)) = todo.pop_front() {
        if current == "SKILL.md" || depth.get(&current).is_some_and(|d| *d <= hop) {
            continue;
        }
        let onward = loads
            .iter()
            .filter(|e| e.from == current)
            .map(|e| (e.to.clone(), hop + 1));
        todo.extend(onward);
        depth.insert(current, hop);
    }
    depth
}

/// Cyclomatic and cognitive complexity and lookups over one route's reachable
/// conditional edges. A conditional edge into a reference is a lookup,
/// excluded from both; a reference's own conditional edges count as its
/// caller's branches at the caller's depth (no added nesting).
fn route_complexity(
    edges: &[Edge],
    loads: &[&Edge],
    starts: &[String],
    reached: &[String],
    references: &HashSet<String>,
) -> (usize, usize, usize) {
    let depth = depths(loads, starts);
    let mut caller_depth: HashMap<&str, usize> = HashMap::new();
    for e in loads {
        if references.contains(&e.to) && reached.contains(&e.from) {
            let here = depth.get(&e.from).copied().unwrap_or(0);
            let slot = caller_depth.entry(&e.to).or_insert(here);
            *slot = (*slot).min(here);
        }
    }
    let branch_depth = |node: &str| {
        caller_depth
            .get(node)
            .or_else(|| depth.get(node))
            .copied()
            .unwrap_or(0)
    };
    let conditional = edges
        .iter()
        .filter(|e| e.conditional && reached.contains(&e.from));
    let (lookups, branches): (Vec<&Edge>, Vec<&Edge>) =
        conditional.partition(|e| references.contains(&e.to));
    let cognitive = branches.iter().map(|e| 1 + branch_depth(&e.from)).sum();
    (branches.len() + 1, cognitive, lookups.len())
}

fn edge_route(edge: &Edge) -> Option<&str> {
    edge.route
        .as_ref()
        .and_then(Option::as_deref)
        .filter(|route| !route.is_empty())
}

/// Everything route-building needs, gathered once.
struct RouteInputs<'a> {
    dir: &'a SkillDir,
    edges: &'a [Edge],
    sizes: &'a OrderedMap<usize>,
    references: &'a HashSet<String>,
}

impl RouteInputs<'_> {
    fn cost(&self, reached: &[String]) -> usize {
        let size = |file: &str| self.sizes.get(file).copied().unwrap_or(0);
        size("SKILL.md")
            + reached
                .iter()
                .filter(|f| f.ends_with(".md"))
                .map(|f| size(f))
                .sum::<usize>()
    }

    fn route(&self, name: &str, own: &[&Edge], everywhere: &[&Edge]) -> Route {
        let loads: Vec<&Edge> = self
            .edges
            .iter()
            .filter(|e| e.kind == EdgeKind::Load)
            .collect();
        let entry = unique(own.iter().map(|e| e.to.clone()));
        let dropped: HashSet<String> = entry
            .iter()
            .filter(|f| f.ends_with(".md"))
            .flat_map(|f| skip_targets(self.dir, f))
            .collect();
        let route_loads: Vec<&Edge> = loads
            .into_iter()
            .filter(|e| !dropped.contains(&e.from) && !dropped.contains(&e.to))
            .collect();
        let candidates: Vec<&&Edge> = own
            .iter()
            .chain(everywhere)
            .filter(|e| !dropped.contains(&e.to))
            .collect();
        let starts: Vec<String> = candidates.iter().map(|e| e.to.clone()).collect();
        let min_starts: Vec<String> = candidates
            .iter()
            .filter(|e| e.table || !e.conditional)
            .map(|e| e.to.clone())
            .collect();
        let minimum = reach(&route_loads, &min_starts, true);
        let reached = reach(&route_loads, &starts, false);
        let handoffs: BTreeSet<String> = self
            .edges
            .iter()
            .filter(|e| e.kind == EdgeKind::Handoff)
            .filter(|e| reached.contains(&e.from) && !reached.contains(&e.to))
            .map(|e| e.to.clone())
            .collect();
        let (cyclomatic, cognitive, lookups) =
            route_complexity(self.edges, &route_loads, &starts, &reached, self.references);
        Route {
            route: name.to_string(),
            entry,
            min_tokens: self.cost(&minimum),
            max_tokens: self.cost(&reached),
            files: reached,
            min_files: minimum,
            handoffs: handoffs.into_iter().collect(),
            cyclomatic,
            cognitive,
            lookups,
            main_min_tokens: 0,
            main_max_tokens: 0,
            inline: Vec::new(),
            unresolved: Vec::new(),
            dispatches: Vec::new(),
        }
    }
}

/// Group SKILL.md load edges by route, in first-seen order.
fn group_routes<'a>(top: &[&'a Edge]) -> Vec<(String, Vec<&'a Edge>)> {
    let mut routes: Vec<(String, Vec<&Edge>)> = Vec::new();
    for edge in top {
        let Some(name) = edge_route(edge) else {
            continue;
        };
        match routes.iter_mut().find(|(route, _)| route == name) {
            Some((_, own)) => own.push(edge),
            None => routes.push((name.to_string(), vec![*edge])),
        }
    }
    routes
}

// ---- Collection -----------------------------------------------------------

fn sibling_names(dir: &SkillDir) -> HashSet<String> {
    let parent = dir.dir.parent().unwrap_or(&dir.dir);
    let names: HashSet<String> = fs::read_dir(parent)
        .into_iter()
        .flatten()
        .flatten()
        .filter(|entry| entry.path().join("SKILL.md").exists())
        .map(|entry| entry.file_name().to_string_lossy().into_owned())
        .collect();
    let others = names.iter().any(|name| *name != dir.name);
    if others { names } else { HashSet::new() }
}

/// Files under references/, scripts/ and assets/, as sorted relative paths.
fn mapped_files(skill: &Path) -> Vec<String> {
    let mut files = Vec::new();
    for dir in DIRS {
        collect_files(&skill.join(dir), skill, &mut files);
    }
    files.sort();
    files
}

fn collect_files(dir: &Path, root: &Path, files: &mut Vec<String>) {
    for entry in fs::read_dir(dir).into_iter().flatten().flatten() {
        let path = entry.path();
        if entry.file_type().is_ok_and(|kind| kind.is_dir()) {
            collect_files(&path, root, files);
            continue;
        }
        let rel = path.strip_prefix(root).ok().filter(|_| path.is_file());
        if let Some(rel) = rel {
            let parts: Vec<String> = rel
                .iter()
                .map(|part| part.to_string_lossy().into_owned())
                .collect();
            files.push(parts.join("/"));
        }
    }
}

/// SKILL.md heading -> the table row that routes to it, from backticked
/// headings (`## Name`) in table rows.
fn route_sections(skill_md: &str) -> HashMap<String, String> {
    let mut sections = HashMap::new();
    for line in skill_md.split('\n') {
        let line = line.trim();
        if !line.starts_with('|') {
            continue;
        }
        let row = scan::short(line.trim_matches('|').split('|').next().unwrap_or(""));
        for caps in scan::find_all(&scan::SECTION, line) {
            sections.insert(scan::short(&caps[1]), row.clone());
        }
    }
    sections
}

/// Pointers and external calls of every Markdown file.
struct Collected {
    edges: Vec<Edge>,
    external: Vec<External>,
    missing: Vec<MissingFinding>,
}

struct Collector<'a> {
    dir: &'a SkillDir,
    sizes: &'a OrderedMap<usize>,
    sections: HashMap<String, String>,
    skill_names: HashSet<String>,
    out: Collected,
}

impl Collector<'_> {
    fn source(&mut self, source: &str) {
        for item in scan::scan(self.dir, source, &self.skill_names) {
            self.item(source, item);
        }
    }

    fn item(&mut self, source: &str, item: Scanned) {
        let skill_md = source == "SKILL.md";
        let (context, table) = match &item.body {
            Body::Pointer(p) => (p.context.as_str(), p.table),
            Body::External(x) => (x.context.as_str(), x.table),
        };
        let route = if table {
            Some(context.to_string())
        } else {
            self.sections.get(&item.section).cloned()
        };
        let edit_gate = skill_md && item.edits && route.as_deref().is_none_or(str::is_empty);
        match item.body {
            Body::External(mut x) => {
                x.from = source.to_string();
                x.conditional |= edit_gate;
                x.route = skill_md.then_some(route);
                self.out.external.push(x);
            }
            Body::Pointer(p) => {
                if !self.dir.actual_path(&p.to).is_file() {
                    self.out.missing.push(MissingFinding {
                        from: source.to_string(),
                        line: p.line,
                        target: p.raw,
                    });
                } else if self.sizes.contains_key(&p.to) {
                    self.out.edges.push(Edge {
                        from: source.to_string(),
                        to: p.to,
                        context: p.context,
                        conditional: p.conditional || edit_gate,
                        kind: p.kind,
                        table: p.table,
                        line: p.line,
                        route: skill_md.then_some(route),
                    });
                }
            }
        }
    }
}

// ---- Analysis -------------------------------------------------------------

/// Map one skill's own files and routes; cross-skill costs come later.
pub(super) fn analyze_skill(skill: &Path) -> Analysis {
    let dir = SkillDir::new(skill);
    let files = mapped_files(skill);
    let shared = dir.shared_files(&files);
    let listed: Vec<String> = files.iter().chain(&shared).cloned().collect();
    let sizes = OrderedMap(
        std::iter::once("SKILL.md".to_string())
            .chain(listed.iter().cloned())
            .map(|f| (f.clone(), scan::tokens(&dir.actual_path(&f))))
            .collect(),
    );
    let references: HashSet<String> = listed
        .iter()
        .filter(|f| scan::is_reference(&dir.actual_path(f)))
        .cloned()
        .collect();
    let mut collector = Collector {
        dir: &dir,
        sizes: &sizes,
        sections: route_sections(&dir.read("SKILL.md")),
        skill_names: sibling_names(&dir),
        out: Collected {
            edges: Vec::new(),
            external: Vec::new(),
            missing: Vec::new(),
        },
    };
    collector.source("SKILL.md");
    for source in listed.iter().filter(|f| f.ends_with(".md")) {
        collector.source(source);
    }
    let Collected {
        mut edges,
        mut external,
        missing,
    } = collector.out;
    label_routes_by_context(&mut edges, &mut external);
    let routes = build_routes(&dir, &edges, &sizes, &references);
    let mut sorted_references: Vec<String> = references.into_iter().collect();
    sorted_references.sort();
    Analysis {
        skill: dir.name.clone(),
        structure: structure(&edges, &routes),
        findings: findings(&files, &edges, missing),
        tokens: sizes,
        references: sorted_references,
        edges,
        external,
        routes,
    }
}

/// Without a routing table, each SKILL.md label is a route.
fn label_routes_by_context(edges: &mut [Edge], external: &mut [External]) {
    let is_top = |e: &Edge| e.kind == EdgeKind::Load && e.from == "SKILL.md";
    if edges.iter().any(|e| is_top(e) && e.table) {
        return;
    }
    for edge in edges.iter_mut().filter(|e| is_top(e)) {
        edge.route = Some(Some(edge.context.clone()));
    }
    for x in external.iter_mut().filter(|x| x.from == "SKILL.md") {
        x.route = Some(Some(x.context.clone()));
    }
}

fn build_routes(
    dir: &SkillDir,
    edges: &[Edge],
    sizes: &OrderedMap<usize>,
    references: &HashSet<String>,
) -> Vec<Route> {
    let top: Vec<&Edge> = edges
        .iter()
        .filter(|e| e.kind == EdgeKind::Load && e.from == "SKILL.md")
        .collect();
    let everywhere: Vec<&Edge> = top
        .iter()
        .copied()
        .filter(|e| edge_route(e).is_none())
        .collect();
    let inputs = RouteInputs {
        dir,
        edges,
        sizes,
        references,
    };
    group_routes(&top)
        .iter()
        .map(|(name, own)| inputs.route(name, own, &everywhere))
        .collect()
}

// ---- Findings and structure -----------------------------------------------

/// Group non-mention edges by the file they point to, then by calling place
/// (a file, or a SKILL.md route).
fn places(edges: &[Edge]) -> HashMap<&str, BTreeMap<String, Vec<&Edge>>> {
    let mut places: HashMap<&str, BTreeMap<String, Vec<&Edge>>> = HashMap::new();
    for e in edges
        .iter()
        .filter(|e| !matches!(e.kind, EdgeKind::Mention | EdgeKind::Role))
    {
        let place = if e.from == "SKILL.md" {
            format!("SKILL.md: {}", e.context)
        } else {
            e.from.clone()
        };
        places
            .entry(&e.to)
            .or_default()
            .entry(place)
            .or_default()
            .push(e);
    }
    places
}

pub(super) fn findings(files: &[String], edges: &[Edge], missing: Vec<MissingFinding>) -> Findings {
    let places = places(edges);
    let called: HashSet<&str> = edges.iter().map(|e| e.to.as_str()).collect();
    let mut out = Findings {
        chain: Vec::new(),
        single_caller: Vec::new(),
        shared: Vec::new(),
        unreferenced: Vec::new(),
        missing,
        cycle: Vec::new(),
        fan_out: Vec::new(),
        density: Vec::new(),
    };
    for file in files {
        let callers = places.get(file.as_str());
        if !called.contains(file.as_str()) {
            out.unreferenced.push(file.clone());
            continue;
        }
        let Some(callers) = callers.filter(|_| file.starts_with("references/")) else {
            continue;
        };
        if callers.len() > 1 {
            out.shared.push(SharedFinding {
                file: file.clone(),
                callers: callers.keys().cloned().collect(),
            });
        } else if let Some((place, hits)) = callers.iter().next() {
            let always = !place.starts_with("SKILL.md")
                && hits
                    .iter()
                    .any(|e| e.kind == EdgeKind::Load && !e.conditional);
            let finding = CallerFinding {
                file: file.clone(),
                caller: place.clone(),
            };
            if always {
                out.chain.push(finding)
            } else {
                out.single_caller.push(finding)
            }
        }
    }
    let shape = structure(edges, &[]);
    out.cycle = shape
        .mutual_pairs
        .iter()
        .cloned()
        .map(|files| CycleFinding { files })
        .collect();
    out.fan_out = shape
        .links_out
        .iter()
        .filter(|(_, links)| **links >= FAN_OUT)
        .map(|(file, links)| FanOutFinding {
            file: file.clone(),
            links: *links,
        })
        .collect();
    if shape.average_links > DENSITY as f64 {
        out.density.push(DensityFinding {
            average: shape.average_links,
        });
    }
    out
}

/// Measure file-to-file load and hand-off links, SKILL.md excluded. With
/// `routes`, also the route-complexity maxima.
pub(super) fn structure(edges: &[Edge], routes: &[Route]) -> Structure {
    let links: BTreeSet<(&str, &str)> = edges
        .iter()
        .filter(|e| matches!(e.kind, EdgeKind::Load | EdgeKind::Handoff) && e.from != "SKILL.md")
        .map(|e| (e.from.as_str(), e.to.as_str()))
        .collect();
    let mut links_out: Vec<(String, usize)> = Vec::new();
    for (source, _) in &links {
        match links_out.last_mut() {
            Some((last, count)) if last == source => *count += 1,
            _ => links_out.push((source.to_string(), 1)),
        }
    }
    let mutual_pairs: Vec<[String; 2]> = links
        .iter()
        .filter(|(a, b)| a < b && links.contains(&(*b, *a)))
        .map(|(a, b)| [a.to_string(), b.to_string()])
        .collect();
    let top = links_out
        .iter()
        .max_by(|a, b| (a.1, &a.0).cmp(&(b.1, &b.0)));
    let cross_module = links
        .iter()
        .filter(|(a, b)| module_of(a) != module_of(b))
        .count();
    let average_links = match links_out.len() {
        0 => 0.0,
        linking => round2(links.len() as f64 / linking as f64),
    };
    let widest = widest_route(routes);
    Structure {
        mutual_links: mutual_pairs.len(),
        mutual_pairs,
        max_links_out: top.map_or(0, |(_, count)| *count),
        max_links_out_file: top.map(|(file, _)| file.clone()),
        average_links,
        linking_files: links_out.len(),
        links: links.len(),
        links_out: OrderedMap(links_out),
        cross_module_edges: cross_module,
        diagram_edges: edges.len(),
        max_route_cyclomatic: routes.iter().map(|r| r.cyclomatic).max(),
        max_route_cognitive: routes.iter().map(|r| r.cognitive).max(),
        max_route_files: widest.map(|r| r.files.len()),
        max_route_files_route: widest.map(|r| r.route.clone()),
    }
}

/// The route reaching the most files; the first of equals.
fn widest_route(routes: &[Route]) -> Option<&Route> {
    let mut widest: Option<&Route> = None;
    for route in routes {
        if widest.is_none_or(|w| route.files.len() > w.files.len()) {
            widest = Some(route);
        }
    }
    widest
}

/// One row of the Structure table.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct StructureRow {
    pub measure: String,
    pub value: String,
    pub target: String,
    pub status: &'static str,
}

fn row(measure: &str, value: String, target: String, status: &'static str) -> StructureRow {
    StructureRow {
        measure: measure.to_string(),
        value,
        target,
        status,
    }
}

fn warn_if(condition: bool) -> &'static str {
    if condition { "warning" } else { "ok" }
}

/// The (measure, value, target, status) rows of the Structure table.
pub fn structure_rows(shape: &Structure) -> Vec<StructureRow> {
    let top_file = shape
        .max_links_out_file
        .as_ref()
        .map_or(String::new(), |file| format!(" ({file})"));
    let plural = if shape.linking_files == 1 { "" } else { "s" };
    let mut rows = vec![
        row(
            "Mutual links",
            shape.mutual_links.to_string(),
            "0".to_string(),
            if shape.mutual_links > 0 {
                "defect"
            } else {
                "ok"
            },
        ),
        row(
            "Max links out of one file",
            format!("{}{top_file}", shape.max_links_out),
            format!("< {FAN_OUT}"),
            warn_if(shape.max_links_out >= FAN_OUT),
        ),
        row(
            "Average links per linking file",
            format!(
                "{} ({} links, {} file{plural})",
                py_float(shape.average_links),
                shape.links,
                shape.linking_files
            ),
            format!("<= {DENSITY}"),
            warn_if(shape.average_links > DENSITY as f64),
        ),
        row(
            "Cross-module edges",
            shape.cross_module_edges.to_string(),
            "-".to_string(),
            "-",
        ),
        row(
            "Diagram edges",
            shape.diagram_edges.to_string(),
            format!("<= {DIAGRAM_EDGES_WARN}"),
            warn_if(shape.diagram_edges > DIAGRAM_EDGES_WARN),
        ),
    ];
    if let Some(cyc) = shape.max_route_cyclomatic {
        rows.push(row(
            "Max route cyclomatic",
            cyc.to_string(),
            format!("<= {CYCLOMATIC_WARN}"),
            warn_if(cyc > CYCLOMATIC_WARN),
        ));
    }
    if let Some(cog) = shape.max_route_cognitive {
        let status = if cog > COGNITIVE_ERROR {
            "defect"
        } else {
            warn_if(cog > COGNITIVE_WARN)
        };
        rows.push(row(
            "Max route cognitive",
            cog.to_string(),
            format!("<= {COGNITIVE_WARN} warn, <= {COGNITIVE_ERROR} error"),
            status,
        ));
    }
    if let (Some(files), Some(route)) = (shape.max_route_files, &shape.max_route_files_route) {
        rows.push(row(
            "Most files reached by one route",
            format!("{files} ({route})"),
            format!("<= {ROUTE_FILES_WARN}"),
            warn_if(files > ROUTE_FILES_WARN),
        ));
    }
    rows
}

/// A dispatch's per-run cost as text: `~N`, `~LOW-HIGH` or `unresolved`.
pub fn dispatch_cost(dispatch: &Dispatch) -> String {
    let Some(low) = dispatch.min_tokens else {
        return "unresolved".to_string();
    };
    let high = dispatch.max_tokens.unwrap_or(low);
    if low == high {
        format!("~{low}")
    } else {
        format!("~{low}-{high}")
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    fn write(root: &Path, rel: &str, text: &str) {
        let path = root.join(rel);
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        fs::write(path, text).unwrap();
    }

    fn tok(text: &str) -> usize {
        text.chars().count().div_ceil(4)
    }

    const SKILL_MD: &str = "# Demo\n\n\
        | Request | Read |\n|---|---|\n\
        | Build it | `references/build.md` |\n\
        | Check it | `references/check.md` |\n\n\
        Before edits, read `references/gate.md`.\n";
    const BUILD_MD: &str = "Then see `references/shared.md`.\n";
    const CHECK_MD: &str = "Run `references/shared.md` when needed.\nSee `references/ghost.md`.\n";

    fn demo() -> (TempDir, Analysis) {
        let tmp = TempDir::new().unwrap();
        let skill = tmp.path().join("demo");
        write(&skill, "SKILL.md", SKILL_MD);
        write(&skill, "references/build.md", BUILD_MD);
        write(&skill, "references/check.md", CHECK_MD);
        write(&skill, "references/gate.md", "gate\n");
        write(
            &skill,
            "references/shared.md",
            "<!-- kind: reference -->\nshared\n",
        );
        write(&skill, "references/lonely.md", "alone\n");
        write(&skill, "scripts/tool.sh", "echo\n");
        let analysis = analyze_skill(&skill);
        (tmp, analysis)
    }

    #[test]
    fn sizes_are_a_quarter_of_the_characters_rounded_up() {
        let (_tmp, a) = demo();
        assert_eq!(a.tokens.get("references/gate.md"), Some(&2)); // "gate\n" is 5 chars
        assert_eq!(a.tokens.get("SKILL.md"), Some(&tok(SKILL_MD)));
        let order: Vec<&str> = a.tokens.iter().map(|(k, _)| k.as_str()).collect();
        assert_eq!(order[0], "SKILL.md");
        assert_eq!(
            order[1..],
            [
                "references/build.md",
                "references/check.md",
                "references/gate.md",
                "references/lonely.md",
                "references/shared.md",
                "scripts/tool.sh"
            ]
        );
        assert_eq!(a.references, ["references/shared.md"]);
    }

    #[test]
    fn routes_reach_files_along_load_edges_with_min_and_max() {
        let (_tmp, a) = demo();
        let names: Vec<&str> = a.routes.iter().map(|r| r.route.as_str()).collect();
        assert_eq!(names, ["Build it", "Check it"]);
        let build = &a.routes[0];
        assert_eq!(build.entry, ["references/build.md"]);
        assert_eq!(
            build.min_files,
            ["references/build.md", "references/shared.md"]
        );
        assert_eq!(
            build.files,
            [
                "references/build.md",
                "references/gate.md",
                "references/shared.md"
            ]
        );
        let small = tok(SKILL_MD) + tok(BUILD_MD) + tok("<!-- kind: reference -->\nshared\n");
        assert_eq!(build.min_tokens, small);
        assert_eq!(build.max_tokens, small + tok("gate\n"));
        let check = &a.routes[1];
        assert_eq!(check.min_files, ["references/check.md"]);
        assert_eq!(check.files.len(), 3);
    }

    #[test]
    fn an_edit_gate_outside_a_table_counts_in_max_not_min() {
        let (_tmp, a) = demo();
        let gate = a
            .edges
            .iter()
            .find(|e| e.to == "references/gate.md")
            .unwrap();
        assert!(gate.conditional);
        assert_eq!(gate.route, Some(None));
        assert!(
            !a.routes[0]
                .min_files
                .contains(&"references/gate.md".to_string())
        );
    }

    #[test]
    fn findings_cover_unreferenced_missing_shared_and_single_caller() {
        let (_tmp, a) = demo();
        let f = &a.findings;
        assert_eq!(f.unreferenced, ["references/lonely.md", "scripts/tool.sh"]);
        assert_eq!(
            f.missing,
            [MissingFinding {
                from: "references/check.md".to_string(),
                line: 2,
                target: "references/ghost.md".to_string(),
            }]
        );
        assert_eq!(
            f.shared,
            [SharedFinding {
                file: "references/shared.md".to_string(),
                callers: vec![
                    "references/build.md".to_string(),
                    "references/check.md".to_string()
                ],
            }]
        );
        let single: Vec<(&str, &str)> = f
            .single_caller
            .iter()
            .map(|c| (c.file.as_str(), c.caller.as_str()))
            .collect();
        assert_eq!(
            single,
            [
                ("references/build.md", "SKILL.md: Build it"),
                ("references/check.md", "SKILL.md: Check it"),
                ("references/gate.md", "SKILL.md: Demo"),
            ]
        );
        assert!(f.chain.is_empty() && f.cycle.is_empty());
    }

    #[test]
    fn structure_counts_links_between_files_without_skill_md() {
        let (_tmp, a) = demo();
        let s = &a.structure;
        assert_eq!((s.links, s.linking_files, s.mutual_links), (2, 2, 0));
        assert_eq!(s.average_links, 1.0);
        assert_eq!(s.max_links_out, 1);
        assert_eq!(s.max_links_out_file.as_deref(), Some("references/check.md"));
        assert_eq!(s.diagram_edges, a.edges.len());
        assert_eq!(s.max_route_files, Some(3));
        assert_eq!(s.max_route_files_route.as_deref(), Some("Build it"));
    }

    #[test]
    fn complexity_counts_conditional_edges_that_are_not_lookups() {
        let (_tmp, a) = demo();
        // SKILL.md is never a reached file, so its gate adds no branch.
        assert_eq!((a.routes[0].cyclomatic, a.routes[0].cognitive), (1, 0));
        // check.md loads the reference shared.md conditionally: a lookup.
        assert_eq!((a.routes[1].cyclomatic, a.routes[1].lookups), (1, 1));

        let tmp = TempDir::new().unwrap();
        let skill = tmp.path().join("demo");
        write(
            &skill,
            "SKILL.md",
            "| R | A |\n|---|---|\n| Go | `references/a.md` |\n",
        );
        write(
            &skill,
            "references/a.md",
            "Read `references/b.md` when stale.\n",
        );
        write(&skill, "references/b.md", "b\n");
        let route = &analyze_skill(&skill).routes[0];
        // One branch at depth 1 (a.md is the entry file): 1 + 1.
        assert_eq!(
            (route.cyclomatic, route.cognitive, route.lookups),
            (2, 2, 0)
        );
    }

    #[test]
    fn an_unconditional_reference_that_loads_another_is_a_chain_and_mutual_links_cycle() {
        let tmp = TempDir::new().unwrap();
        let skill = tmp.path().join("demo");
        write(
            &skill,
            "SKILL.md",
            "| R | A |\n|---|---|\n| Go | `references/a.md` |\n",
        );
        write(&skill, "references/a.md", "Read `references/b.md`.\n");
        write(&skill, "references/b.md", "See `references/a.md`.\n");
        let a = analyze_skill(&skill);
        let chain: Vec<(&str, &str)> = a
            .findings
            .chain
            .iter()
            .map(|c| (c.file.as_str(), c.caller.as_str()))
            .collect();
        assert_eq!(chain, [("references/b.md", "references/a.md")]);
        assert_eq!(
            a.findings.cycle,
            [CycleFinding {
                files: ["references/a.md".to_string(), "references/b.md".to_string()]
            }]
        );
        assert_eq!(a.structure.mutual_links, 1);
    }

    #[test]
    fn a_skill_without_a_routing_table_makes_each_label_a_route() {
        let tmp = TempDir::new().unwrap();
        let skill = tmp.path().join("demo");
        write(
            &skill,
            "SKILL.md",
            "## First\n\nRead `references/a.md`.\n\n## Second\n\nRead `references/b.md`.\n",
        );
        write(&skill, "references/a.md", "a\n");
        write(&skill, "references/b.md", "b\n");
        let a = analyze_skill(&skill);
        let names: Vec<&str> = a.routes.iter().map(|r| r.route.as_str()).collect();
        assert_eq!(names, ["First", "Second"]);
    }

    #[test]
    fn a_shared_file_listed_for_the_skill_is_mapped() {
        let tmp = TempDir::new().unwrap();
        let skill = tmp.path().join("skills/demo");
        write(
            &skill,
            "SKILL.md",
            "| R | A |\n|---|---|\n| Go | `references/s.md` |\n",
        );
        write(tmp.path(), "skills/shared/references/s.md", "shared body\n");
        write(
            tmp.path(),
            "skills/shared/MANIFEST",
            "references/s.md demo other\n",
        );
        let a = analyze_skill(&skill);
        assert_eq!(a.tokens.get("references/s.md"), Some(&tok("shared body\n")));
        assert_eq!(a.routes[0].files, ["references/s.md"]);
    }

    #[test]
    fn a_skip_sentence_drops_the_named_file_from_a_route() {
        let tmp = TempDir::new().unwrap();
        let skill = tmp.path().join("demo");
        write(
            &skill,
            "SKILL.md",
            "| R | A |\n|---|---|\n| Go | `references/a.md` |\n",
        );
        write(
            &skill,
            "references/a.md",
            "Read `references/b.md`. Skip `references/c.md`.\n",
        );
        write(&skill, "references/b.md", "Read `references/c.md`.\n");
        write(&skill, "references/c.md", "c\n");
        let a = analyze_skill(&skill);
        assert_eq!(a.routes[0].files, ["references/a.md", "references/b.md"]);
    }

    fn route(name: &str, entry: &[&str]) -> Route {
        Route {
            route: name.to_string(),
            entry: entry.iter().map(|e| e.to_string()).collect(),
            files: Vec::new(),
            min_files: Vec::new(),
            min_tokens: 0,
            max_tokens: 0,
            handoffs: Vec::new(),
            cyclomatic: 1,
            cognitive: 0,
            lookups: 0,
            main_min_tokens: 0,
            main_max_tokens: 0,
            inline: Vec::new(),
            unresolved: Vec::new(),
            dispatches: Vec::new(),
        }
    }

    #[test]
    fn match_route_prefers_qualified_then_stem_then_label() {
        let routes = [
            route("Plan work", &["references/plan.md", "references/more.md"]),
            route("Build with builder", &["references/build.md"]),
            route("Build now", &["references/build-now.md"]),
        ];
        let pick =
            |mode, qualifier| match_route(&routes, mode, qualifier).map(|r| r.route.as_str());
        assert_eq!(pick("build", None), Some("Build with builder"));
        assert_eq!(pick("work", None), Some("Plan work"));
        assert_eq!(pick("nothing", None), None);
        assert_eq!(pick("build", Some("builder")), Some("Build with builder"));
        assert_eq!(pick("build", Some("absent")), None);
        // A qualifier with no mode match falls back to the fewest entry files.
        assert_eq!(pick("zzz", Some("now")), Some("Build now"));
    }

    #[test]
    fn json_keeps_the_scripts_key_order_and_float_format() {
        let (_tmp, a) = demo();
        let json = serde_json::to_string_pretty(&a).unwrap();
        let top = [
            "skill",
            "tokens",
            "references",
            "edges",
            "external",
            "routes",
            "structure",
            "findings",
        ];
        let at: Vec<usize> = top
            .iter()
            .map(|k| json.find(&format!("\n  \"{k}\"")).unwrap())
            .collect();
        assert!(at.windows(2).all(|w| w[0] < w[1]));
        assert!(json.contains("\"average_links\": 1.0,"));
        assert!(json.contains("\"single caller\": ["));
        assert!(json.contains("\"fan-out\": []"));
        let edge = [
            "\"from\": \"SKILL.md\"",
            "\"to\": \"references/build.md\"",
            "\"context\": \"Build it\"",
            "\"conditional\": false",
            "\"kind\": \"load\"",
            "\"table\": true",
            "\"line\": 5",
            "\"route\": \"Build it\"",
        ]
        .join(",\n      ");
        assert!(json.contains(&edge), "{json}");
    }

    #[test]
    fn the_average_is_the_integer_zero_when_no_file_links_out() {
        let tmp = TempDir::new().unwrap();
        let skill = tmp.path().join("demo");
        write(
            &skill,
            "SKILL.md",
            "| R | A |\n|---|---|\n| Go | `references/a.md` |\n",
        );
        write(&skill, "references/a.md", "a\n");
        let json = serde_json::to_string_pretty(&analyze_skill(&skill)).unwrap();
        assert!(json.contains("\"average_links\": 0,"));
        assert!(json.contains("\"max_links_out_file\": null"));
    }

    #[test]
    fn rounding_and_float_text_follow_python() {
        assert_eq!(round2(9.0 / 8.0), 1.12); // exact half: round to even
        assert_eq!(round2(2.0 / 3.0), 0.67);
        assert_eq!(py_float(2.0), "2.0");
        assert_eq!(py_float(1.5), "1.5");
        assert_eq!(py_float(0.0), "0");
    }

    #[test]
    fn module_of_groups_by_directory_or_stem_prefix() {
        assert_eq!(module_of("scripts/a-b.sh"), "scripts");
        assert_eq!(module_of("references/build-micro.md"), "build");
        assert_eq!(module_of("references/plan.md"), "plan");
    }

    #[test]
    fn structure_rows_report_status_per_measure() {
        let (_tmp, a) = demo();
        let rows = structure_rows(&a.structure);
        let first = &rows[0];
        assert_eq!(
            (first.measure.as_str(), first.value.as_str(), first.status),
            ("Mutual links", "0", "ok")
        );
        assert_eq!(rows[2].value, "1.0 (2 links, 2 files)");
        assert_eq!(rows[2].target, "<= 2");
        assert_eq!(rows.len(), 8);
        assert_eq!(rows[7].value, "3 (Build it)");
    }

    #[test]
    fn dispatch_cost_prints_a_point_a_range_or_unresolved() {
        let mut d = Dispatch {
            agent: "builder".to_string(),
            runs: "x".to_string(),
            from: Vec::new(),
            conditional: false,
            min_tokens: Some(5),
            max_tokens: Some(5),
            files: Vec::new(),
        };
        assert_eq!(dispatch_cost(&d), "~5");
        d.max_tokens = Some(9);
        assert_eq!(dispatch_cost(&d), "~5-9");
        d.min_tokens = None;
        assert_eq!(dispatch_cost(&d), "unresolved");
    }
}
