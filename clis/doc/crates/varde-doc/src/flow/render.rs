//! Text, Mermaid and FLOW.md renderings of a skill's [`Analysis`].
//!
//! Port of `text_report` through `flow_doc` in `skill-flow.py`; the output is
//! byte-identical except for the FLOW.md header, which names `varde doc flow`.

use super::{
    Analysis, DENSITY, Edge, EdgeKind, External, ExternalType, FAN_OUT, dispatch_cost, module_of,
    structure_rows,
};
use std::collections::{BTreeMap, BTreeSet, HashMap, HashSet};
use std::fmt::Write as _;
use std::path::Path;

/// The finding kinds that describe structure, which FLOW.md lists under Structure.
const STRUCTURE: [&str; 3] = ["cycle:", "fan-out:", "density:"];

fn tokens_of(data: &Analysis, name: &str) -> usize {
    data.tokens.get(name).copied().unwrap_or(0)
}

/// Text plus the file's estimated size; non-Markdown files carry none.
fn sized_label(data: &Analysis, name: &str, text: &str, unit: &str) -> String {
    if name.ends_with(".md") {
        format!("{text} (~{}{unit})", tokens_of(data, name))
    } else {
        text.to_string()
    }
}

fn escape_label(text: &str) -> String {
    text.replace('"', "#quot;")
        .replace('<', "#lt;")
        .replace('>', "#gt;")
}

/// A density average as Python prints it: `2.0`, not `2`.
fn py_float(value: f64) -> String {
    if value.fract() == 0.0 {
        format!("{value:.1}")
    } else {
        value.to_string()
    }
}

/// The `kind: detail` lines of the Findings section, in report order.
fn findings_lines(data: &Analysis) -> Vec<String> {
    let f = &data.findings;
    let mut lines = Vec::new();
    for item in &f.chain {
        lines.push(format!("chain: {} <- {}", item.file, item.caller));
    }
    for item in &f.single_caller {
        lines.push(format!("single caller: {} <- {}", item.file, item.caller));
    }
    for item in &f.shared {
        lines.push(format!(
            "shared: {} <- {}",
            item.file,
            item.callers.join("; ")
        ));
    }
    for item in &f.unreferenced {
        lines.push(format!("unreferenced: {item}"));
    }
    for item in &f.missing {
        lines.push(format!(
            "missing: {}:{} -> {}",
            item.from, item.line, item.target
        ));
    }
    for item in &f.cycle {
        lines.push(format!("cycle: {}", item.files.join(" <-> ")));
    }
    for item in &f.fan_out {
        lines.push(format!(
            "fan-out: {} ({} links out, target < {FAN_OUT})",
            item.file, item.links
        ));
    }
    for item in &f.density {
        lines.push(format!(
            "density: average {} links per linking file (target <= {DENSITY})",
            py_float(item.average)
        ));
    }
    lines
}

/// The plain-text report for one skill.
pub fn text_report(data: &Analysis) -> String {
    let mut out = vec![
        format!(
            "== {} (SKILL.md ~{} tokens)",
            data.skill,
            tokens_of(data, "SKILL.md")
        ),
        "Routes:".to_string(),
    ];
    for r in &data.routes {
        out.push(format!(
            "  {}  [~{}-{} tokens with SKILL.md; main agent ~{}-{}]",
            r.route, r.min_tokens, r.max_tokens, r.main_min_tokens, r.main_max_tokens
        ));
        out.extend(
            r.files
                .iter()
                .map(|f| format!("    {}", sized_label(data, f, f, ""))),
        );
        out.extend(r.handoffs.iter().map(|f| format!("    handoff: {f}")));
        out.extend(
            r.inline
                .iter()
                .map(|x| format!("    inline: {} -> {}", x.target, x.resolved)),
        );
        out.extend(r.unresolved.iter().map(|t| format!("    unresolved: {t}")));
        for d in &r.dispatches {
            let conditional = if d.conditional { " (conditional)" } else { "" };
            out.push(format!(
                "    dispatch {}{conditional}: {}, {} per dispatch, from {}",
                d.agent,
                d.runs,
                dispatch_cost(d),
                d.from.join(", ")
            ));
        }
    }
    if data.routes.is_empty() {
        out.push("  (none)".to_string());
    }
    out.push("Structure:".to_string());
    out.extend(structure_rows(&data.structure).into_iter().map(|row| {
        format!(
            "  {}: {} (target {}) {}",
            row.measure, row.value, row.target, row.status
        )
    }));
    out.push("Findings:".to_string());
    out.extend(findings_lines(data).into_iter().map(|l| format!("  {l}")));
    out.join("\n")
}

/// Non-reference files below SKILL.md by module, each list alphabetical. A
/// module of only reference files has no key, so it drops out of the diagrams.
fn module_groups(data: &Analysis) -> BTreeMap<String, Vec<String>> {
    let refs: HashSet<&String> = data.references.iter().collect();
    let mut groups: BTreeMap<String, Vec<String>> = BTreeMap::new();
    for (name, _) in data.tokens.iter() {
        if name != "SKILL.md" && !refs.contains(name) {
            groups
                .entry(module_of(name))
                .or_default()
                .push(name.clone());
        }
    }
    for files in groups.values_mut() {
        files.sort();
    }
    groups
}

/// A procedure's folded references and the non-reference files it reaches.
type Fold<'a> = (BTreeSet<String>, Vec<(String, &'a Edge)>);

/// Per procedure file: the references transitively folded into it, and the
/// non-reference files reached through those references over load/handoff
/// edges. A reference has no node of its own, so its edges attach to the
/// procedure that folds it.
fn fold(data: &Analysis) -> BTreeMap<String, Fold<'_>> {
    let refs: HashSet<&String> = data.references.iter().collect();
    let mut by_from: HashMap<&str, Vec<&Edge>> = HashMap::new();
    for e in &data.edges {
        if matches!(e.kind, EdgeKind::Load | EdgeKind::Handoff) && e.from != "SKILL.md" {
            by_from.entry(e.from.as_str()).or_default().push(e);
        }
    }

    fn walk<'a>(
        node: &str,
        visited: &HashSet<String>,
        by_from: &HashMap<&str, Vec<&'a Edge>>,
        refs: &HashSet<&String>,
    ) -> Fold<'a> {
        let mut folded = BTreeSet::new();
        let mut dests = Vec::new();
        for &e in by_from.get(node).into_iter().flatten() {
            if visited.contains(&e.to) {
                continue;
            }
            if refs.contains(&e.to) {
                folded.insert(e.to.clone());
                let mut deeper = visited.clone();
                deeper.insert(e.to.clone());
                let (sub_folded, sub_dests) = walk(&e.to, &deeper, by_from, refs);
                folded.extend(sub_folded);
                dests.extend(sub_dests);
            } else {
                dests.push((e.to.clone(), e));
            }
        }
        (folded, dests)
    }

    data.tokens
        .iter()
        .filter(|(name, _)| name.as_str() != "SKILL.md" && !refs.contains(name))
        .map(|(name, _)| {
            let visited = HashSet::from([name.clone()]);
            (name.clone(), walk(name, &visited, &by_from, &refs))
        })
        .collect()
}

/// (from-module, to-module) -> edge count, over folded procedure edges.
fn module_edge_pairs(folds: &BTreeMap<String, Fold<'_>>) -> BTreeMap<(String, String), usize> {
    let mut pairs = BTreeMap::new();
    for (proc, (_, dests)) in folds {
        for (dest, _) in dests {
            *pairs.entry((module_of(proc), module_of(dest))).or_insert(0) += 1;
        }
    }
    pairs
}

fn module_overview_mermaid(
    groups: &BTreeMap<String, Vec<String>>,
    pairs: &BTreeMap<(String, String), usize>,
) -> String {
    let ids: HashMap<&String, String> = groups
        .keys()
        .enumerate()
        .map(|(i, m)| (m, format!("m{i}")))
        .collect();
    let mut out = vec!["flowchart TD".to_string()];
    for (m, files) in groups {
        let count = files.len();
        let plural = if count == 1 { "" } else { "s" };
        out.push(format!("  {}[\"{m} ({count} file{plural})\"]", ids[m]));
    }
    for ((a, b), count) in pairs {
        if a != b {
            out.push(format!("  {} -->|\"{count}\"| {}", ids[a], ids[b]));
        }
    }
    out.join("\n")
}

/// This module's own procedures, plus one node per other module it links to or
/// from. Each procedure's label folds in every reference it points to.
fn module_mermaid(
    data: &Analysis,
    groups: &BTreeMap<String, Vec<String>>,
    pairs: &BTreeMap<(String, String), usize>,
    folds: &BTreeMap<String, Fold<'_>>,
    name: &str,
) -> String {
    let mut ids: HashMap<String, String> = groups[name]
        .iter()
        .enumerate()
        .map(|(i, f)| (f.clone(), format!("n{i}")))
        .collect();
    let mut out = vec!["flowchart TD".to_string()];
    for f in &groups[name] {
        let mut lines = vec![sized_label(data, f, &escape_label(f), " tok")];
        lines.extend(
            folds[f]
                .0
                .iter()
                .map(|r| format!("ref: {} (~{} tok)", escape_label(r), tokens_of(data, r))),
        );
        out.push(format!("  {}[\"{}\"]", ids[f], lines.join("<br/>")));
    }
    let others: BTreeSet<&String> = pairs
        .keys()
        .filter_map(|(a, b)| {
            if a == name && b != name {
                Some(b)
            } else if b == name && a != name {
                Some(a)
            } else {
                None
            }
        })
        .collect();
    for m in others {
        let id = format!("n{}", ids.len());
        out.push(format!("  {id}[\"{m}\"]"));
        ids.insert(m.clone(), id);
    }
    let mut seen = HashSet::new();
    for (proc, (_, dests)) in folds {
        let from_module = module_of(proc);
        let mut sorted: Vec<&(String, &Edge)> = dests.iter().collect();
        sorted.sort_by(|a, b| a.0.cmp(&b.0));
        for (dest, e) in sorted {
            let to_module = module_of(dest);
            if name != from_module && name != to_module {
                continue;
            }
            let source = if from_module == name {
                &ids[proc]
            } else {
                &ids[&from_module]
            };
            let target = if to_module == name {
                &ids[dest]
            } else {
                &ids[&to_module]
            };
            if !seen.insert((source.clone(), target.clone())) {
                continue;
            }
            let arrow = if e.kind == EdgeKind::Handoff {
                "==>"
            } else if e.conditional {
                "-.->"
            } else {
                "-->"
            };
            out.push(format!("  {source} {arrow} {target}"));
        }
    }
    out.join("\n")
}

/// One drawn pointer: an edge inside the skill or a call that leaves it.
struct Pointer<'a> {
    from: &'a str,
    /// The target file for an edge, `None` for an external call.
    to: Option<&'a str>,
    external: Option<&'a External>,
    context: &'a str,
    conditional: bool,
    kind: Option<EdgeKind>,
    route: Option<&'a str>,
}

impl<'a> Pointer<'a> {
    fn edge(e: &'a Edge) -> Self {
        Pointer {
            from: &e.from,
            to: Some(&e.to),
            external: None,
            context: &e.context,
            conditional: e.conditional,
            kind: Some(e.kind),
            route: e.route.as_ref().and_then(Option::as_deref),
        }
    }

    fn external(x: &'a External) -> Self {
        Pointer {
            from: &x.from,
            to: None,
            external: Some(x),
            context: &x.context,
            conditional: x.conditional,
            // Agent dispatches carry no kind in the data.
            kind: (x.external == ExternalType::Skill).then_some(x.kind),
            route: x.route.as_ref().and_then(Option::as_deref),
        }
    }
}

/// Node ids in order of first use.
#[derive(Default)]
struct Ids(HashMap<String, String>);

impl Ids {
    fn node(&mut self, name: &str) -> String {
        let next = self.0.len();
        self.0
            .entry(name.to_string())
            .or_insert_with(|| format!("n{next}"))
            .clone()
    }
}

/// The whole-skill Mermaid diagram.
pub fn mermaid(data: &Analysis) -> String {
    let mut ids = Ids::default();
    let skill_id = ids.node("SKILL.md");
    let mut out = vec![
        format!("%% {}", data.skill),
        "flowchart TD".to_string(),
        format!(
            "  {skill_id}[\"SKILL.md (~{} tok)\"]",
            tokens_of(data, "SKILL.md")
        ),
    ];
    for (name, _) in data.tokens.iter() {
        if name != "SKILL.md" {
            let label = sized_label(data, name, &escape_label(name), " tok");
            out.push(format!("  {}[\"{label}\"]", ids.node(name)));
        }
    }
    for r in &data.routes {
        let route = ids.node(&format!("route: {}", r.route));
        out.push(format!("  {route}([\"{}\"])", escape_label(&r.route)));
        out.push(format!("  {skill_id} --> {route}"));
    }
    let mut seen_targets = HashSet::new();
    let mut seen_keys = HashSet::new();
    let pointers = data
        .edges
        .iter()
        .map(Pointer::edge)
        .chain(data.external.iter().map(Pointer::external));
    for p in pointers {
        if matches!(p.kind, Some(EdgeKind::Mention | EdgeKind::Role)) {
            continue;
        }
        let route = p.route.filter(|route| !route.is_empty());
        let routed = route.is_some();
        let source = match route {
            Some(route) => ids.node(&format!("route: {route}")),
            None => ids.node(p.from),
        };
        let target = match (p.external, p.to) {
            (Some(x), _) => {
                let text = if x.external == ExternalType::Skill {
                    x.target.clone()
                } else {
                    format!("agent: {}", x.target)
                };
                let target = ids.node(&format!("external: {text}"));
                if seen_targets.insert(target.clone()) {
                    out.push(format!("  {target}[[\"{}\"]]", escape_label(&text)));
                }
                target
            }
            (None, to) => ids.node(to.unwrap_or_default()),
        };
        if !seen_keys.insert((source.clone(), target.clone(), p.context.to_string())) {
            continue;
        }
        if routed && p.external.is_none() {
            out.push(format!("  {source} --> {target}"));
            continue;
        }
        let arrow = if p.kind == Some(EdgeKind::Handoff) {
            "==>"
        } else if p.conditional {
            "-.->"
        } else {
            "-->"
        };
        out.push(format!(
            "  {source} {arrow}|\"{}\"| {target}",
            escape_label(p.context)
        ));
    }
    out.join("\n")
}

/// The indented Files tree: references nest under the longest reference whose
/// stem plus a hyphen prefixes theirs.
fn files_tree(data: &Analysis) -> Vec<String> {
    let mut references: Vec<&str> = data
        .tokens
        .iter()
        .map(|(name, _)| name.as_str())
        .filter(|name| name.starts_with("references/") && name.ends_with(".md"))
        .collect();
    references.sort_unstable();
    let stem = |path: &str| -> String {
        Path::new(path)
            .file_stem()
            .map(|s| s.to_string_lossy().into_owned())
            .unwrap_or_default()
    };
    let mut children: HashMap<&str, Vec<&str>> = HashMap::from([("SKILL.md", Vec::new())]);
    for &reference in &references {
        let own = stem(reference);
        let mut parent = "SKILL.md";
        let mut best = None;
        for &candidate in &references {
            let candidate_stem = stem(candidate);
            if own.starts_with(&format!("{candidate_stem}-"))
                && best.is_none_or(|len| candidate_stem.chars().count() > len)
            {
                best = Some(candidate_stem.chars().count());
                parent = candidate;
            }
        }
        children.entry(parent).or_default().push(reference);
        children.entry(reference).or_default();
    }
    let root_routes: Vec<&str> = data.routes.iter().map(|r| r.route.as_str()).collect();

    fn render(
        reference: &str,
        depth: usize,
        data: &Analysis,
        children: &HashMap<&str, Vec<&str>>,
        root_routes: &[&str],
        lines: &mut Vec<String>,
    ) {
        let entering: Vec<&str> = if reference == "SKILL.md" {
            root_routes.to_vec()
        } else {
            data.routes
                .iter()
                .filter(|r| r.files.iter().any(|f| f == reference))
                .map(|r| r.route.as_str())
                .collect()
        };
        let routes = if entering.is_empty() {
            "-".to_string()
        } else {
            entering.join(", ")
        };
        lines.push(format!(
            "{}- {reference} (~{} tok; routes: {routes})",
            "  ".repeat(depth),
            tokens_of(data, reference)
        ));
        let mut kids = children[reference].clone();
        kids.sort_unstable();
        for child in kids {
            render(child, depth + 1, data, children, root_routes, lines);
        }
    }

    let mut lines = Vec::new();
    render("SKILL.md", 0, data, &children, &root_routes, &mut lines);
    lines
}

/// The FLOW.md document for one skill.
pub fn flow_doc(data: &Analysis) -> String {
    let folds = fold(data);
    let groups = module_groups(data);
    let pairs = module_edge_pairs(&folds);
    let mut out: Vec<String> = [
        &format!("# {} flow", data.skill) as &str,
        "",
        "Generated for human readers; agents do not load this file. Regenerate",
        "with `varde doc flow --write`. Dotted edges",
        "are conditional loads; min tokens follow only solid edges. Thick edges",
        "are hand-offs to a later stage, outside min and max. Double-bordered",
        "nodes are skill modes run inline or agent dispatches. Min and max count",
        "this skill; main adds modes the main agent runs inline, each file once.",
        "Subagents are per dispatch (multiply by the dispatch count); * marks a",
        "conditional dispatch. Module overview first, then one diagram per module.",
        "",
        "## Files",
        "",
    ]
    .iter()
    .map(|line| line.to_string())
    .collect();
    out.extend(files_tree(data));
    out.extend(
        ["", "```mermaid"]
            .map(String::from)
            .into_iter()
            .chain([module_overview_mermaid(&groups, &pairs), "```".to_string()]),
    );
    for name in groups.keys() {
        out.extend([
            String::new(),
            format!("### {name}"),
            String::new(),
            "```mermaid".to_string(),
            module_mermaid(data, &groups, &pairs, &folds, name),
            "```".to_string(),
        ]);
    }
    out.extend(
        [
            "",
            "## Routes",
            "",
            "| Route | Min tokens | Max tokens | Main min | Main max | Subagents per dispatch | Lookups | Files |",
            "|---|---|---|---|---|---|---|---|",
        ]
        .map(String::from),
    );
    for r in &data.routes {
        let name = r.route.replace('|', "\\|");
        let agents = r
            .dispatches
            .iter()
            .map(|d| {
                let star = if d.conditional { "*" } else { "" };
                format!("{}{star} {}", d.agent, dispatch_cost(d))
            })
            .collect::<Vec<_>>()
            .join(", ");
        let agents = if agents.is_empty() { "-" } else { &agents };
        let files = if r.files.is_empty() {
            "-".to_string()
        } else {
            r.files.join(", ")
        };
        let mut row = String::new();
        let _ = write!(
            row,
            "| {name} | ~{} | ~{} | ~{} | ~{} | {agents} | {} | {files} |",
            r.min_tokens, r.max_tokens, r.main_min_tokens, r.main_max_tokens, r.lookups
        );
        out.push(row);
    }
    let findings = findings_lines(data);
    let (shape, other): (Vec<&String>, Vec<&String>) = findings
        .iter()
        .partition(|line| STRUCTURE.iter().any(|kind| line.starts_with(kind)));
    out.extend(
        [
            "",
            "## Structure",
            "",
            "| Measure | Value | Target | Status |",
            "|---|---|---|---|",
        ]
        .map(String::from),
    );
    out.extend(structure_rows(&data.structure).into_iter().map(|row| {
        format!(
            "| {} | {} | {} | {} |",
            row.measure, row.value, row.target, row.status
        )
    }));
    if !shape.is_empty() {
        out.push(String::new());
        out.extend(shape.iter().map(|line| format!("- {line}")));
    }
    out.extend(["", "## Findings", ""].map(String::from));
    if other.is_empty() {
        out.push("None.".to_string());
    } else {
        out.extend(other.iter().map(|line| format!("- {line}")));
    }
    out.join("\n") + "\n"
}
