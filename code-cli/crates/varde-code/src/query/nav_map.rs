//! `nav_map` — assembled session-start repo orientation output.
//!
//! Wires the 7 standalone nav-map section modules built by earlier tasks
//! (see `memory-bank/working/plans/2026-09-03-nav-map-draft/plan.md`) into
//! one query mode: `entrypoints`, `foundational_files`, `module_layers`,
//! `subsystems`, `symbols`, `flows`, `hotspots`. No section logic lives
//! here — this module only opens the db connection, calls each section's
//! existing public function, and assembles the results into one JSON
//! object.

use std::collections::HashMap;

use rusqlite::Connection;

use crate::extract::langs::role_tags::RoleTag;
use crate::resolve::Community;

use super::{ApiError, db_err, open_db};

/// Cap for the nav_map `hotspots` section. nav_map is a session-start
/// orientation summary, so it surfaces the top risk hotspots rather than the
/// full ranked list (the standalone `hotspots` mode stays unbounded). Without
/// a cap this section listed every source file — 917 rows on a reference repo.
const HOTSPOTS_SECTION_LIMIT: usize = 50;

/// Cap for the nav_map `foundational_files` section, same orientation-summary
/// rationale as [`HOTSPOTS_SECTION_LIMIT`]: surface the most-depended-on files,
/// not the full fan-in leaderboard (562 rows on a reference repo). The
/// standalone `foundational_files` computation stays unbounded (`None`).
const FOUNDATIONAL_FILES_SECTION_LIMIT: usize = 50;

/// Cap for the nav_map `symbols` section. The symbols leaderboard is the
/// largest section (1333 rows on a reference repo); nav_map surfaces the top
/// symbols for orientation while the standalone `symbols` mode stays unbounded.
const SYMBOLS_SECTION_LIMIT: usize = 100;

/// Total token budget for the whole nav_map output (audit F1). nav_map is
/// injected at session start, so it must be a *fixed-cost* orientation, not
/// proportional to repo size — unbounded it reached 140K tokens on a
/// mainstream C# repo. Spent section-by-section in priority order by
/// [`budget_nav_map`]; overridable via the `maxTokensEstimate` input, mirroring
/// `context_pack`.
const NAV_MAP_DEFAULT_MAX_TOKENS: usize = 12000;

/// Per-subsystem member-list cap. One community can list hundreds of files
/// (C#: 298 subsystems, some huge), so each subsystem shows its first few
/// members plus a `membersOmitted` count rather than the full roster.
const SUBSYSTEM_MEMBER_CAP: usize = 8;

/// Caps for the `module_layers` object's inner arrays — it serializes the
/// whole resolved import graph (`edges`) and every cycle, which alone reached
/// 222 KB on the C# repo.
const MODULE_LAYERS_EDGE_CAP: usize = 50;
const MODULE_LAYERS_CYCLE_CAP: usize = 20;

/// Largest up-front allowance for one populated orientation section. The first
/// pass shares the available budget across populated sections and caps that
/// share here; priority spending receives every token left over.
const SECTION_RESERVE_TOKENS: usize = 200;

/// Depth/size caps for the per-flow summary nav_map embeds. `flows.rs` builds
/// each tree uncapped (thousands of nodes possible); nav_map is a fixed-cost
/// orientation, so it embeds only a bounded slice of each ranked flow — enough
/// to show the shape of the biggest call trees — and points at `explore` for
/// the full tree. `MAX_NODES` bounds total nodes across the whole summary;
/// `MAX_DEPTH` bounds how deep it descends.
const FLOW_SUMMARY_MAX_DEPTH: usize = 4;
const FLOW_SUMMARY_MAX_NODES: usize = 30;

#[derive(Clone, Copy)]
struct BudgetSection {
    name: &'static str,
    more: &'static str,
}

const BUDGET_SECTIONS: [BudgetSection; 6] = [
    BudgetSection {
        name: "entrypoints",
        more: "raise maxTokensEstimate to list more entrypoints",
    },
    BudgetSection {
        name: "foundational_files",
        more: "code_query dependents on a specific file, or raise maxTokensEstimate",
    },
    BudgetSection {
        name: "subsystems",
        more: "raise maxTokensEstimate to list more subsystems",
    },
    BudgetSection {
        name: "flows",
        more: "code_query mode=explore on an entrypoint symbol (direction=outgoing) for its full call tree, or raise maxTokensEstimate to list more flows",
    },
    BudgetSection {
        name: "symbols",
        more: "code_query mode=filter_symbols for the full symbol list",
    },
    BudgetSection {
        name: "hotspots",
        more: "code_query mode=hotspots for the full ranked list",
    },
];

const MODULE_LAYERS_MORE: &str =
    "raise maxTokensEstimate; module_layers holds the resolved module-dependency graph";

struct NavMapBudget {
    max_tokens: usize,
    remaining: usize,
    section_totals: [usize; BUDGET_SECTIONS.len()],
    module_edges_total: usize,
    cycles_total: usize,
    kept: [usize; BUDGET_SECTIONS.len()],
    kept_edges: usize,
    truncated: serde_json::Map<String, serde_json::Value>,
}

/// Assemble the full nav_map output: all 7 sections in one JSON object.
///
/// Inputs: `repoRoot`/`dbPath` only (same convention as every other mode).
/// Output: `{"entrypoints", "foundational_files", "module_layers",
/// "subsystems", "symbols", "flows", "hotspots"}`.
pub fn nav_map(input: &serde_json::Value) -> Result<serde_json::Value, ApiError> {
    super::freshen_for_mode("nav_map", input)?;
    let conn = open_db(input)?;
    let (listed, entrypoints_json) = entrypoint_sections(&conn)?;
    let foundational_files =
        super::foundational_files::leaderboard(&conn, Some(FOUNDATIONAL_FILES_SECTION_LIMIT))?;
    let module_layers_json = module_layers_section(&conn)?;
    let subsystems_json = subsystems_section(&conn, &listed)?;
    let entrypoint_ids: std::collections::HashSet<i64> = listed
        .iter()
        .map(|entrypoint| entrypoint.entity_id)
        .collect();
    let symbols =
        super::symbols_section::leaderboard(&conn, &entrypoint_ids, Some(SYMBOLS_SECTION_LIMIT))?;
    let flows_json = flow_section(&conn, &listed)?;
    let hotspots = super::mapping::hotspots_on(&conn, Some(HOTSPOTS_SECTION_LIMIT))?;
    let mut data = serde_json::json!({
        "entrypoints": entrypoints_json,
        "foundational_files": foundational_files,
        "module_layers": module_layers_json,
        "subsystems": subsystems_json,
        "symbols": symbols,
        "flows": flows_json,
        "hotspots": hotspots,
    });

    let max_tokens = input
        .get("maxTokensEstimate")
        .and_then(|value| value.as_u64())
        .map(|value| value as usize)
        .unwrap_or(NAV_MAP_DEFAULT_MAX_TOKENS);
    let guide = budget_nav_map(&mut data, max_tokens);
    data["guide"] = guide;
    Ok(data)
}

fn entrypoint_sections(
    conn: &rusqlite::Connection,
) -> Result<(Vec<super::entrypoints::Entrypoint>, Vec<serde_json::Value>), ApiError> {
    let entrypoints = super::entrypoints::detect(conn)?;
    let routes = super::entrypoints::detect_routes(conn)?;
    let process_mains = super::entrypoints::detect_process_mains(conn)?;
    let listed = entrypoints
        .into_iter()
        .chain(routes)
        .chain(process_mains)
        .collect::<Vec<_>>();
    let displayed = round_robin_entrypoints(&listed)
        .into_iter()
        .map(|entrypoint| entrypoint.to_json())
        .collect();
    Ok((listed, displayed))
}

fn flow_section(
    conn: &rusqlite::Connection,
    entrypoints: &[super::entrypoints::Entrypoint],
) -> Result<Vec<serde_json::Value>, ApiError> {
    let roots = entrypoints
        .iter()
        .filter(|entrypoint| entrypoint.flow_root)
        .cloned()
        .collect::<Vec<_>>();
    let flows = super::flows::build_flows(conn, &roots)?;
    let mut trees = flows
        .iter()
        .filter(|tree| !tree.root.children.is_empty())
        .collect::<Vec<_>>();
    trees.sort_by_key(|tree| std::cmp::Reverse(count_flow_nodes(&tree.root)));
    let mut seen_roots = std::collections::HashSet::new();
    trees.retain(|tree| seen_roots.insert((tree.root.file.as_str(), tree.root.symbol.as_str())));
    Ok(trees.into_iter().map(summarize_flow).collect())
}

/// Rough token estimate (`chars / 4`), the same convention `context_pack`'s
/// budgeter and this audit use.
fn est_tokens(v: &serde_json::Value) -> usize {
    serde_json::to_string(v).map(|s| s.len() / 4).unwrap_or(0)
}

/// Interleave entrypoints by supported language while retaining detector rank
/// within each language. Language groups appear in the order first seen in
/// the ranked detector output.
fn round_robin_entrypoints(
    entrypoints: &[super::entrypoints::Entrypoint],
) -> Vec<super::entrypoints::Entrypoint> {
    let mut groups: Vec<(
        &str,
        std::collections::VecDeque<&super::entrypoints::Entrypoint>,
    )> = Vec::new();

    for entrypoint in entrypoints {
        let extension = entrypoint
            .file
            .rsplit_once('.')
            .map_or("", |(_, extension)| extension);
        let language = crate::parse::language_for_path(std::path::Path::new(&entrypoint.file))
            .map_or(extension, |language| crate::parse::language_name(&language));
        if let Some((_, group)) = groups.iter_mut().find(|(key, _)| *key == language) {
            group.push_back(entrypoint);
        } else {
            groups.push((language, std::collections::VecDeque::from([entrypoint])));
        }
    }

    let mut ordered = Vec::with_capacity(entrypoints.len());
    loop {
        let mut emitted = false;
        for (_, group) in &mut groups {
            if let Some(entrypoint) = group.pop_front() {
                ordered.push(entrypoint.clone());
                emitted = true;
            }
        }
        if !emitted {
            return ordered;
        }
    }
}

/// Trim the assembled nav_map to `max_tokens`, spending the budget across
/// sections in a fixed **priority order** (most valuable for orientation
/// first), and return a `guide` describing what was truncated (F1).
///
/// Priority rationale — an agent orienting in a repo wants, in order: where
/// execution starts (`entrypoints`), what everything depends on
/// (`foundational_files`), the architectural partition (`subsystems`), the
/// core interfaces (`symbols`), where the risk is (`hotspots`), the dependency
/// layering (`module_layers`), and last the call trees (`flows`, currently the
/// thinnest section). Each section also has a hard item cap so no single one
/// can eat the whole budget. A first pass gives every populated section a
/// bounded chance to retain one item. An item that cannot fit its share stays
/// omitted, so tiny budgets never force every section into the map.
///
/// Discoverability: each truncated section reports `{shown, total, more}` where
/// `more` names the follow-up that returns the full data — a dedicated query
/// mode where one exists (`hotspots`, `filter_symbols`), otherwise re-running
/// nav_map with a larger `maxTokensEstimate`. Per-subsystem member truncation
/// is reported inline as `membersOmitted` on the subsystem.
fn budget_nav_map(data: &mut serde_json::Value, max_tokens: usize) -> serde_json::Value {
    cap_subsystem_members(data);
    let (module_edges_total, cycles_total) = cap_module_layers(data);
    let mut budget = NavMapBudget::new(data, max_tokens, module_edges_total, cycles_total);

    budget.reserve_first_items(data);
    budget.spend_section_items(data);
    budget.spend_module_edges(data);
    budget.spend_cycles(data);
    budget.enforce_rendered_limit(data)
}

fn cap_subsystem_members(data: &mut serde_json::Value) {
    let Some(subsystems) = data["subsystems"].as_array_mut() else {
        return;
    };
    for subsystem in subsystems {
        let total = subsystem["members"].as_array().map_or(0, Vec::len);
        if total <= SUBSYSTEM_MEMBER_CAP {
            continue;
        }
        if let Some(members) = subsystem["members"].as_array_mut() {
            members.truncate(SUBSYSTEM_MEMBER_CAP);
        }
        subsystem["membersOmitted"] = serde_json::json!(total - SUBSYSTEM_MEMBER_CAP);
    }
}

fn cap_module_layers(data: &mut serde_json::Value) -> (usize, usize) {
    let edges_total = data["module_layers"]["edges"]
        .as_array()
        .map_or(0, Vec::len);
    if let Some(edges) = data["module_layers"]["edges"].as_array_mut() {
        edges.truncate(MODULE_LAYERS_EDGE_CAP);
    }

    let cycles_total = data["module_layers"]["cycles"]
        .as_array()
        .map_or(0, Vec::len);
    if let Some(cycles) = data["module_layers"]["cycles"].as_array_mut() {
        cycles.truncate(MODULE_LAYERS_CYCLE_CAP);
    }
    (edges_total, cycles_total)
}

impl NavMapBudget {
    fn new(
        data: &serde_json::Value,
        max_tokens: usize,
        module_edges_total: usize,
        cycles_total: usize,
    ) -> Self {
        let section_totals = std::array::from_fn(|index| {
            data[BUDGET_SECTIONS[index].name]
                .as_array()
                .map_or(0, Vec::len)
        });
        let fixed_cost = est_tokens(&serde_json::json!({ "edges": [], "cycles": [] }));
        Self {
            max_tokens,
            remaining: max_tokens.saturating_sub(fixed_cost),
            section_totals,
            module_edges_total,
            cycles_total,
            kept: [0; BUDGET_SECTIONS.len()],
            kept_edges: 0,
            truncated: serde_json::Map::new(),
        }
    }

    fn reserve_first_items(&mut self, data: &serde_json::Value) {
        let populated_sections = BUDGET_SECTIONS
            .iter()
            .filter(|section| {
                data[section.name]
                    .as_array()
                    .is_some_and(|items| !items.is_empty())
            })
            .count();
        let has_edges = data["module_layers"]["edges"]
            .as_array()
            .is_some_and(|edges| !edges.is_empty());
        let reserve = self
            .remaining
            .checked_div(populated_sections + usize::from(has_edges))
            .unwrap_or(0)
            .min(SECTION_RESERVE_TOKENS);

        for (index, section) in BUDGET_SECTIONS.iter().enumerate() {
            let Some(item) = data[section.name]
                .as_array()
                .and_then(|items| items.first())
            else {
                continue;
            };
            let cost = est_tokens(item).max(1);
            if cost <= reserve {
                self.kept[index] = 1;
                self.remaining -= cost;
            }
        }

        let edge = data["module_layers"]["edges"]
            .as_array()
            .and_then(|edges| edges.first());
        if let Some(cost) = edge.map(|edge| est_tokens(edge).max(1))
            && cost <= reserve
        {
            self.kept_edges = 1;
            self.remaining -= cost;
        }
    }

    fn spend_section_items(&mut self, data: &mut serde_json::Value) {
        for (index, section) in BUDGET_SECTIONS.iter().enumerate() {
            let Some(items) = data[section.name].as_array_mut() else {
                continue;
            };
            let total = items.len();
            while self.kept[index] < total {
                let cost = est_tokens(&items[self.kept[index]]).max(1);
                if cost > self.remaining {
                    break;
                }
                self.remaining -= cost;
                self.kept[index] += 1;
            }
            if self.kept[index] < total {
                items.truncate(self.kept[index]);
                self.record_truncation(section.name, self.kept[index], total, section.more);
            }
        }
    }

    fn spend_module_edges(&mut self, data: &mut serde_json::Value) {
        if let Some(edges) = data["module_layers"]["edges"].as_array() {
            while self.kept_edges < edges.len() && self.kept_edges < MODULE_LAYERS_EDGE_CAP {
                let cost = est_tokens(&edges[self.kept_edges]).max(1);
                if cost > self.remaining {
                    break;
                }
                self.remaining -= cost;
                self.kept_edges += 1;
            }
        }
        if let Some(edges) = data["module_layers"]["edges"].as_array_mut() {
            edges.truncate(self.kept_edges);
        }
        if self.kept_edges < self.module_edges_total {
            self.record_truncation(
                "module_layers.edges",
                self.kept_edges,
                self.module_edges_total,
                MODULE_LAYERS_MORE,
            );
        }
    }

    fn spend_cycles(&mut self, data: &mut serde_json::Value) {
        let mut kept_cycles = 0;
        if let Some(cycles) = data["module_layers"]["cycles"].as_array() {
            while kept_cycles < cycles.len() {
                let cost = est_tokens(&cycles[kept_cycles]).max(1);
                if cost > self.remaining {
                    break;
                }
                self.remaining -= cost;
                kept_cycles += 1;
            }
        }
        if let Some(cycles) = data["module_layers"]["cycles"].as_array_mut() {
            cycles.truncate(kept_cycles);
        }
        if kept_cycles < self.cycles_total {
            self.record_truncation(
                "module_layers.cycles",
                kept_cycles,
                self.cycles_total,
                MODULE_LAYERS_MORE,
            );
        }
    }

    fn enforce_rendered_limit(&mut self, data: &mut serde_json::Value) -> serde_json::Value {
        let mut guide = nav_map_guide(self.max_tokens, &self.truncated, None);
        loop {
            let mut rendered = data.clone();
            rendered["guide"] = guide.clone();
            if est_tokens(&rendered) <= self.max_tokens {
                return guide;
            }
            if !self.remove_lowest_priority_item(data) {
                return self.minimum_budget_guide(data, est_tokens(&rendered));
            }
            guide = nav_map_guide(self.max_tokens, &self.truncated, None);
        }
    }

    fn remove_lowest_priority_item(&mut self, data: &mut serde_json::Value) -> bool {
        let shown = data["module_layers"]["cycles"]
            .as_array_mut()
            .and_then(|items| items.pop().map(|_| items.len()));
        if let Some(shown) = shown {
            self.record_truncation(
                "module_layers.cycles",
                shown,
                self.cycles_total,
                MODULE_LAYERS_MORE,
            );
            return true;
        }

        for index in (0..BUDGET_SECTIONS.len()).rev() {
            let section = BUDGET_SECTIONS[index];
            let shown = data[section.name]
                .as_array_mut()
                .and_then(|items| items.pop().map(|_| items.len()));
            if let Some(shown) = shown {
                self.record_truncation(
                    section.name,
                    shown,
                    self.section_totals[index],
                    section.more,
                );
                return true;
            }
        }

        // Keep the reserved top edge while lower-priority detail can shrink.
        // Only drop module edges after all section items are exhausted.
        let shown = data["module_layers"]["edges"]
            .as_array_mut()
            .and_then(|items| items.pop().map(|_| items.len()));
        if let Some(shown) = shown {
            self.record_truncation(
                "module_layers.edges",
                shown,
                self.module_edges_total,
                MODULE_LAYERS_MORE,
            );
            return true;
        }
        false
    }

    fn minimum_budget_guide(
        &self,
        data: &serde_json::Value,
        initial_minimum: usize,
    ) -> serde_json::Value {
        let mut minimum = initial_minimum;
        loop {
            let guide = nav_map_guide(self.max_tokens, &self.truncated, Some(minimum));
            let mut rendered = data.clone();
            rendered["guide"] = guide.clone();
            let actual = est_tokens(&rendered);
            if actual == minimum {
                return guide;
            }
            minimum = actual;
        }
    }

    fn record_truncation(&mut self, name: &str, shown: usize, total: usize, more: &str) {
        self.truncated.insert(
            name.to_string(),
            serde_json::json!({ "shown": shown, "total": total, "more": more }),
        );
    }
}

fn nav_map_guide(
    max_tokens: usize,
    truncated: &serde_json::Map<String, serde_json::Value>,
    minimum_budget_tokens: Option<usize>,
) -> serde_json::Value {
    let mut guide = serde_json::Map::new();
    guide.insert("budgetTokens".to_string(), serde_json::json!(max_tokens));
    guide.insert(
        "truncated".to_string(),
        serde_json::Value::Object(truncated.clone()),
    );
    if let Some(minimum) = minimum_budget_tokens {
        guide.insert(
            "minimumBudgetTokens".to_string(),
            serde_json::json!(minimum),
        );
    }
    serde_json::Value::Object(guide)
}

/// File-level resolved edges as `(from_path, to_path)` pairs, the input
/// shape [`super::module_layers::compute_module_layers`] expects.
fn module_layers_section(conn: &Connection) -> Result<serde_json::Value, ApiError> {
    let mut stmt = conn
        .prepare(
            "SELECT f1.path, f2.path
             FROM resolved_edges re
             JOIN files f1 ON f1.id = re.from_file_id
             JOIN files f2 ON f2.id = re.to_file_id
             WHERE re.resolved = 1 AND re.to_file_id IS NOT NULL",
        )
        .map_err(db_err)?;
    let pairs: Vec<(String, String)> = stmt
        .query_map([], |r| Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?)))
        .map_err(db_err)?
        .collect::<Result<Vec<_>, _>>()
        .map_err(db_err)?;

    let edge_refs: Vec<(&str, &str)> = pairs
        .iter()
        .map(|(a, b)| (a.as_str(), b.as_str()))
        .collect();
    let layers = super::module_layers::compute_module_layers(edge_refs);
    serde_json::to_value(&layers).map_err(|e| ApiError::new("serialize_error", e.to_string()))
}

/// Read the persisted Louvain partition (same `community_members` table the
/// `clusters` mode reads) and hand it to [`super::subsystems::name_clusters`]
/// with a per-file dominant-role-tag map derived from the already-computed
/// entrypoints (first role tag seen per file).
///
/// Test files are excluded here (via the authoritative `is_test_path`
/// generated column) so a test directory never forms or pads a subsystem —
/// matching the entrypoints, foundational-files, symbols and hotspots
/// sections. Generated/vendored exclusion stays in `name_clusters`.
fn subsystems_section(
    conn: &Connection,
    entrypoints: &[super::entrypoints::Entrypoint],
) -> Result<serde_json::Value, ApiError> {
    let mut stmt = conn
        .prepare(
            "SELECT cm.community_id, f.path FROM community_members cm
             JOIN files f ON f.id = cm.file_id
             WHERE f.is_test_path = 0",
        )
        .map_err(db_err)?;
    let rows: Vec<(i64, String)> = stmt
        .query_map([], |r| Ok((r.get::<_, i64>(0)?, r.get::<_, String>(1)?)))
        .map_err(db_err)?
        .collect::<Result<Vec<_>, _>>()
        .map_err(db_err)?;

    let mut by_community: HashMap<i64, Vec<String>> = HashMap::new();
    for (community_id, path) in rows {
        by_community.entry(community_id).or_default().push(path);
    }
    let communities: Vec<Community> = by_community
        .into_iter()
        .map(|(id, members)| Community {
            id: id as u32,
            members,
        })
        .collect();

    let mut role_tags: HashMap<String, RoleTag> = HashMap::new();
    for ep in entrypoints {
        role_tags.entry(ep.file.clone()).or_insert(ep.role);
    }

    let mut named = super::subsystems::name_clusters(&communities, &role_tags);
    // Rank by significance so the budget's item cap surfaces the repo's biggest
    // real domains, not an arbitrary slice. `by_community` above is a HashMap,
    // so without this the emitted order — and thus which subsystems survive the
    // cap — is non-deterministic; on a large repo (a .NET repo yields ~275
    // named communities) that means orientation showed a random 20 instead of
    // the top ones. Sort by member count desc, then name, then id for a stable
    // order.
    named.sort_by(|a, b| {
        b.members
            .len()
            .cmp(&a.members.len())
            .then_with(|| a.name.cmp(&b.name))
            .then_with(|| a.id.cmp(&b.id))
    });
    Ok(serde_json::json!(
        named
            .into_iter()
            .map(|c| serde_json::json!({
                "id": c.id,
                "name": c.name,
                "members": c.members,
            }))
            .collect::<Vec<_>>()
    ))
}

/// Total number of nodes in a flow tree (the ranking metric — bigger trees
/// reach more of the codebase and lead the section). Backref/leaf nodes count
/// as one; `children` is empty on both.
fn count_flow_nodes(node: &super::flows::FlowNode) -> usize {
    1 + node.children.iter().map(count_flow_nodes).sum::<usize>()
}

/// Per-flow-summary path table: deduplicates the file paths within one flow
/// summary so a tree of many nodes concentrated in a few files pays each
/// path's tokens once (in the `files` array) instead of re-stating it on every
/// node (audit F: flows re-emitted the same absolute path per node — the
/// dominant cost of the section). Each node carries an `f` index into the
/// summary's `files` array instead of a `file` string.
///
/// Scoped per summary rather than per whole nav_map so the budgeter dropping a
/// flow tree drops its table with it — no dangling entries to prune. Paths are
/// interned as the index holds them (absolute); the `files` field name is one
/// [`super::output`] relativizes like every other repo-path field, so the
/// emitted table is repo-relative.
#[derive(Default)]
struct FileInterner {
    paths: Vec<String>,
    index: HashMap<String, usize>,
}

impl FileInterner {
    /// Index of `path` in the table, appending it on first sight.
    fn intern(&mut self, path: &str) -> usize {
        if let Some(&existing) = self.index.get(path) {
            return existing;
        }
        let idx = self.paths.len();
        self.paths.push(path.to_string());
        self.index.insert(path.to_string(), idx);
        idx
    }

    fn into_paths(self) -> Vec<String> {
        self.paths
    }
}

/// Embed one flow as a bounded, self-describing summary: the entrypoint, its
/// file, the full `nodeCount`, a `files` path table, a depth/size-capped `root`
/// tree whose nodes reference `files` by `f` index, and a `more` handle naming
/// the `explore` query that returns the complete tree. Bounding here (not in
/// `flows.rs`) keeps flows.rs the full-fidelity source while nav_map stays
/// fixed-cost.
fn summarize_flow(tree: &super::flows::FlowTree) -> serde_json::Value {
    let node_count = count_flow_nodes(&tree.root);
    // Whole-summary node budget, root included.
    let mut budget = FLOW_SUMMARY_MAX_NODES.saturating_sub(1);
    let mut files = FileInterner::default();
    let root = summarize_flow_node(&tree.root, 0, &mut budget, &mut files);
    let more = format!(
        "code_query mode=explore {{\"input\":\"{}\",\"direction\":\"outgoing\"}} for the full call tree",
        tree.entrypoint
    );
    serde_json::json!({
        "entrypoint": tree.entrypoint,
        "file": tree.root.file,
        "nodeCount": node_count,
        "files": files.into_paths(),
        "root": root,
        "more": more,
    })
}

/// Recursively serialize a flow node to bounded JSON, spending a shared node
/// `budget` and stopping at [`FLOW_SUMMARY_MAX_DEPTH`]. A `backref_to` node
/// (cycle back-edge) is emitted as a `recurses` leaf without descending, so a
/// cyclic call graph can't loop. When children are dropped (depth cap, node
/// budget, or a mix), the count is reported inline as `childrenOmitted` so the
/// renderer and JSON consumers know the tree continues.
fn summarize_flow_node(
    node: &super::flows::FlowNode,
    depth: usize,
    budget: &mut usize,
    files: &mut FileInterner,
) -> serde_json::Value {
    let mut obj = serde_json::json!({ "symbol": node.symbol, "f": files.intern(&node.file) });
    if node.backref_to.is_some() {
        obj["recurses"] = serde_json::json!(true);
        return obj;
    }
    if node.children.is_empty() {
        return obj;
    }
    // Collapse repeated sibling backrefs to the same target. A dispatch-style
    // parent (a big match/switch calling one callee from many arms) otherwise
    // emits the same `(↑ recurses)` leaf N times, spending the summary's fixed
    // node budget on zero-information restatements and crowding out distinct
    // calls. Distinct children and first expansions are untouched; only
    // provable duplicate backrefs collapse, into one node carrying
    // `recursesCount`. `total_children` becomes the distinct count, so the
    // `childrenOmitted` accounting reflects what a reader would expect to see.
    let mut ordered: Vec<(&super::flows::FlowNode, usize)> = Vec::new();
    let mut backref_pos: HashMap<i64, usize> = HashMap::new();
    for child in &node.children {
        if let Some(br) = &child.backref_to {
            if let Some(&pos) = backref_pos.get(&br.entity_id) {
                ordered[pos].1 += 1;
                continue;
            }
            backref_pos.insert(br.entity_id, ordered.len());
        }
        ordered.push((child, 1));
    }
    let total_children = ordered.len();
    if depth + 1 >= FLOW_SUMMARY_MAX_DEPTH {
        obj["childrenOmitted"] = serde_json::json!(total_children);
        return obj;
    }
    let mut kids = Vec::new();
    for (child, count) in &ordered {
        if *budget == 0 {
            break;
        }
        *budget -= 1;
        let mut child_json = summarize_flow_node(child, depth + 1, budget, files);
        if *count > 1 {
            child_json["recursesCount"] = serde_json::json!(count);
        }
        kids.push(child_json);
    }
    if kids.len() < total_children {
        obj["childrenOmitted"] = serde_json::json!(total_children - kids.len());
    }
    obj["children"] = serde_json::json!(kids);
    obj
}

#[cfg(test)]
mod nav_map_tests {
    use super::*;
    use crate::extract::langs::role_tags::RoleTag;
    use crate::query::entrypoints::Entrypoint;

    fn temp_root(label: &str) -> std::path::PathBuf {
        let path = std::env::temp_dir().join(format!(
            "varde-nav-map-{label}-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .expect("clock after epoch")
                .as_nanos()
        ));
        std::fs::create_dir_all(&path).expect("temp root creates");
        path
    }

    use crate::query::flows::{FlowNode, FlowTree};
    use crate::query::test_support::test_support::with_isolated_home;

    fn leaf(symbol: &str) -> FlowNode {
        FlowNode {
            entity_id: 0,
            file: format!("src/{symbol}.rs"),
            symbol: symbol.to_string(),
            children: Vec::new(),
            backref_to: None,
        }
    }

    /// `summarize_flow` reports the *full* node count for ranking, but embeds
    /// only a depth/size-bounded slice of the tree plus an `explore` follow-up
    /// handle — so one huge flow can't blow nav_map's fixed cost.
    #[test]
    fn summarize_flow_bounds_tree_but_reports_full_size() {
        // A wide root: far more children than FLOW_SUMMARY_MAX_NODES allows.
        let children: Vec<FlowNode> = (0..100).map(|i| leaf(&format!("c{i}"))).collect();
        let total = 1 + children.len();
        let tree = FlowTree {
            entrypoint: "handler".to_string(),
            root: FlowNode {
                entity_id: 1,
                file: "src/main.rs".to_string(),
                symbol: "handler".to_string(),
                children,
                backref_to: None,
            },
        };

        let summary = summarize_flow(&tree);

        // Full size is preserved for ranking, even though the tree is trimmed.
        assert_eq!(summary["nodeCount"], serde_json::json!(total));
        // The embedded tree is bounded: fewer children than the original 100.
        let shown = summary["root"]["children"].as_array().unwrap().len();
        assert!(
            shown <= FLOW_SUMMARY_MAX_NODES,
            "embedded tree must be bounded to the node budget (< the original 100): shown={shown}"
        );
        // The drop is reported inline so the reader knows it continues.
        assert_eq!(
            summary["root"]["childrenOmitted"],
            serde_json::json!(100 - shown)
        );
        // The follow-up handle names the explore query for the full tree.
        let more = summary["more"].as_str().unwrap();
        assert!(
            more.contains("explore") && more.contains("handler"),
            "{more}"
        );
    }

    /// Path interning: a flow summary emits a deduplicated `files` table and
    /// every node references it by `f` index instead of restating the path.
    /// Two nodes in the same file share one table entry (the dominant cost the
    /// interning targets — a tree of many nodes in few files).
    #[test]
    fn summarize_flow_interns_node_paths_into_a_deduped_files_table() {
        // Root and one child both live in `src/app.rs`; a second child is in
        // `src/util.rs`. The table must hold each path once.
        let child_same_file = FlowNode {
            entity_id: 2,
            file: "src/app.rs".to_string(),
            symbol: "sibling".to_string(),
            children: Vec::new(),
            backref_to: None,
        };
        let tree = FlowTree {
            entrypoint: "handler".to_string(),
            root: FlowNode {
                entity_id: 1,
                file: "src/app.rs".to_string(),
                symbol: "handler".to_string(),
                children: vec![child_same_file, leaf("util")],
                backref_to: None,
            },
        };

        let summary = summarize_flow(&tree);
        let files: Vec<&str> = summary["files"]
            .as_array()
            .expect("files table present")
            .iter()
            .map(|v| v.as_str().unwrap())
            .collect();
        // `src/app.rs` is deduped to one entry despite two nodes using it.
        assert_eq!(
            files,
            ["src/app.rs", "src/util.rs"],
            "deduped table: {files:?}"
        );

        // Nodes carry `f` indices, not `file` strings, that resolve back to the
        // right path through the table.
        let root = &summary["root"];
        assert!(
            root.get("file").is_none(),
            "node uses `f` index, not `file`"
        );
        let root_idx = root["f"].as_u64().unwrap() as usize;
        assert_eq!(files[root_idx], "src/app.rs");
        let kids = root["children"].as_array().unwrap();
        assert_eq!(files[kids[0]["f"].as_u64().unwrap() as usize], "src/app.rs");
        assert_eq!(
            files[kids[1]["f"].as_u64().unwrap() as usize],
            "src/util.rs"
        );
    }

    /// Repeated sibling backrefs to the same target collapse into one node
    /// carrying `recursesCount`, so a dispatch-style parent doesn't spend the
    /// summary budget on identical `(↑ recurses)` leaves. Distinct children and
    /// the first full expansion of the target are preserved.
    #[test]
    fn summarize_flow_collapses_repeated_sibling_backrefs() {
        // A parent that calls `dispatch` (entity 7) from 20 arms — the first is
        // a full expansion, the rest are backrefs to it — plus one distinct
        // call to `other`.
        fn backref_to(entity_id: i64, symbol: &str) -> FlowNode {
            FlowNode {
                entity_id,
                file: format!("src/{symbol}.rs"),
                symbol: symbol.to_string(),
                children: Vec::new(),
                backref_to: Some(crate::query::flows::Backref {
                    entrypoint: "root".to_string(),
                    file: format!("src/{symbol}.rs"),
                    symbol: symbol.to_string(),
                    entity_id,
                }),
            }
        }
        let mut children = vec![other_leaf(9, "other")];
        for _ in 0..20 {
            children.push(backref_to(7, "dispatch"));
        }
        let tree = FlowTree {
            entrypoint: "root".to_string(),
            root: FlowNode {
                entity_id: 1,
                file: "src/main.rs".to_string(),
                symbol: "root".to_string(),
                children,
                backref_to: None,
            },
        };

        let summary = summarize_flow(&tree);
        let kids = summary["root"]["children"].as_array().unwrap();
        // 21 raw children collapse to 2 distinct: `other` + one `dispatch`.
        assert_eq!(kids.len(), 2, "sibling backrefs collapsed: {kids:?}");
        let dispatch = kids
            .iter()
            .find(|k| k["symbol"] == serde_json::json!("dispatch"))
            .expect("dispatch node present");
        assert_eq!(
            dispatch["recursesCount"],
            serde_json::json!(20),
            "collapsed backref carries its multiplier: {dispatch}"
        );
        // The distinct child is untouched (no bogus multiplier).
        let other = kids
            .iter()
            .find(|k| k["symbol"] == serde_json::json!("other"))
            .expect("other node present");
        assert!(other.get("recursesCount").is_none(), "{other}");
    }

    fn other_leaf(entity_id: i64, symbol: &str) -> FlowNode {
        FlowNode {
            entity_id,
            file: format!("src/{symbol}.rs"),
            symbol: symbol.to_string(),
            children: Vec::new(),
            backref_to: None,
        }
    }

    #[test]
    fn entrypoints_round_robin_source_extensions_preserving_rank() {
        let entrypoint = |entity_id, file: &str, symbol: &str| Entrypoint {
            entity_id,
            file: file.to_string(),
            symbol: symbol.to_string(),
            role: RoleTag::RouteHandler,
            flow_root: true,
            method: None,
            path: None,
        };
        let ranked = vec![
            entrypoint(1, "src/rust_first.rs", "rust_first"),
            entrypoint(2, "src/rust_second.rs", "rust_second"),
            entrypoint(3, "app/python_first.py", "python_first"),
            entrypoint(4, "web/typescript_first.ts", "typescript_first"),
            entrypoint(5, "app/python_second.py", "python_second"),
            entrypoint(6, "src/rust_third.rs", "rust_third"),
        ];

        let symbols: Vec<_> = round_robin_entrypoints(&ranked)
            .into_iter()
            .map(|entrypoint| entrypoint.symbol)
            .collect();

        assert_eq!(
            symbols,
            [
                "rust_first",
                "python_first",
                "typescript_first",
                "rust_second",
                "python_second",
                "rust_third",
            ]
        );
    }

    #[test]
    fn entrypoints_round_robin_groups_javascript_variants() {
        let entrypoint = |entity_id, file: &str, symbol: &str| Entrypoint {
            entity_id,
            file: file.to_string(),
            symbol: symbol.to_string(),
            role: RoleTag::RouteHandler,
            flow_root: true,
            method: None,
            path: None,
        };
        let ranked = vec![
            entrypoint(1, "web/first.js", "javascript_first"),
            entrypoint(2, "web/second.mjs", "javascript_second"),
            entrypoint(3, "web/third.cjs", "javascript_third"),
            entrypoint(4, "web/fourth.jsx", "javascript_fourth"),
            entrypoint(5, "api/app.py", "python_first"),
        ];

        let symbols: Vec<_> = round_robin_entrypoints(&ranked)
            .into_iter()
            .map(|entrypoint| entrypoint.symbol)
            .collect();

        assert_eq!(
            symbols,
            [
                "javascript_first",
                "python_first",
                "javascript_second",
                "javascript_third",
                "javascript_fourth",
            ]
        );
    }

    #[test]
    fn default_budget_keeps_later_entrypoint_languages_visible() {
        let entrypoint = |entity_id, file: String, symbol: String| Entrypoint {
            entity_id,
            file,
            symbol,
            role: RoleTag::RouteHandler,
            flow_root: true,
            method: None,
            path: None,
        };
        let mut ranked: Vec<_> = (0..1_000)
            .map(|id| {
                entrypoint(
                    id,
                    format!("crates/service/src/handler_{id}.rs"),
                    format!("rust_handler_{id}"),
                )
            })
            .collect();
        ranked.push(entrypoint(
            1_000,
            "services/api/app.py".to_string(),
            "python_handler".to_string(),
        ));
        ranked.push(entrypoint(
            1_001,
            "web/src/routes.ts".to_string(),
            "typescript_handler".to_string(),
        ));
        let entrypoints_json: Vec<_> = round_robin_entrypoints(&ranked)
            .iter()
            .map(Entrypoint::to_json)
            .collect();
        let mut data = serde_json::json!({
            "entrypoints": entrypoints_json,
            "foundational_files": [],
            "module_layers": {"edges": [], "cycles": []},
            "subsystems": [],
            "symbols": [],
            "flows": [],
            "hotspots": [],
        });

        budget_nav_map(&mut data, NAV_MAP_DEFAULT_MAX_TOKENS);

        let symbols: Vec<_> = data["entrypoints"]
            .as_array()
            .expect("entrypoints array")
            .iter()
            .map(|entrypoint| entrypoint["symbol"].as_str().expect("symbol"))
            .collect();
        assert!(
            symbols.len() < ranked.len(),
            "default budget truncates output"
        );
        assert_eq!(
            &symbols[..3],
            ["rust_handler_0", "python_handler", "typescript_handler"]
        );
    }

    /// Depth beyond `FLOW_SUMMARY_MAX_DEPTH` is cut with a `childrenOmitted`
    /// marker rather than descended, and `nodeCount` still counts the whole
    /// deep chain.
    #[test]
    fn summarize_flow_caps_depth() {
        // A single deep chain a > b > c > d > e > f.
        let mut node = leaf("f");
        for sym in ["e", "d", "c", "b", "a"] {
            let mut parent = leaf(sym);
            parent.children = vec![node];
            node = parent;
        }
        let tree = FlowTree {
            entrypoint: "a".to_string(),
            root: node,
        };

        let summary = summarize_flow(&tree);
        assert_eq!(summary["nodeCount"], serde_json::json!(6));

        // Walk the embedded chain; it must not exceed FLOW_SUMMARY_MAX_DEPTH
        // levels and the deepest rendered node must report an omitted child.
        let mut cur = &summary["root"];
        let mut depth = 1;
        while let Some(kids) = cur["children"].as_array() {
            if kids.is_empty() {
                break;
            }
            cur = &kids[0];
            depth += 1;
        }
        assert!(
            depth <= FLOW_SUMMARY_MAX_DEPTH,
            "embedded depth {depth} exceeds cap {FLOW_SUMMARY_MAX_DEPTH}"
        );
        assert!(
            cur.get("childrenOmitted").is_some(),
            "deepest rendered node flags the cut subtree: {cur}"
        );
    }

    /// AC1: `nav_map` against a built fixture repo returns all 7 section
    /// keys, no error.
    #[test]
    fn nav_map_returns_all_seven_sections() {
        with_isolated_home(
            "nav-map",
            "all-sections",
            nav_map_returns_all_seven_sections_inner,
        );
    }

    fn nav_map_returns_all_seven_sections_inner() {
        let root = temp_root("all-sections");
        std::fs::write(
            root.join("app.py"),
            "from flask import Flask\napp = Flask(__name__)\n\n@app.route(\"/hello\")\ndef hello():\n    return \"hi\"\n",
        )
        .expect("write app.py");

        crate::build::run_with_force(root.to_str().unwrap(), true).expect("full build");

        let input = serde_json::json!({ "repoRoot": root.to_str().unwrap() });
        let data = nav_map(&input).expect("nav_map computes");

        for key in [
            "entrypoints",
            "foundational_files",
            "module_layers",
            "subsystems",
            "symbols",
            "flows",
            "hotspots",
        ] {
            assert!(
                data.get(key).is_some(),
                "nav_map output missing section {key:?}: {data}"
            );
        }

        let db = crate::db::path::repo_db_path(&root);
        let _ = std::fs::remove_file(&db);
        let _ = std::fs::remove_dir_all(&root);
    }

    /// Default-budget orientation keeps one useful HTTP route from each
    /// supported server framework. An ordinary Nest injectable service must
    /// not consume an entrypoint slot.
    #[test]
    fn default_budget_keeps_mixed_framework_routes_and_excludes_nest_service() {
        with_isolated_home(
            "nav-map",
            "mixed-framework-default-budget",
            default_budget_keeps_mixed_framework_routes_and_excludes_nest_service_inner,
        );
    }

    fn default_budget_keeps_mixed_framework_routes_and_excludes_nest_service_inner() {
        let root = temp_root("mixed-framework-default-budget");
        let mut nest_handlers = String::new();
        for index in 0..45 {
            nest_handlers.push_str(&format!(
                "    @Get('extra-{index}')\n    extra{index}(): string {{ return 'extra'; }}\n"
            ));
        }
        let mut cats_controller = String::from(
            "@Controller('cats')\n\
             export class CatsController {\n\
             \x20\x20@Get(':id')\n\
             \x20\x20aFindOne(): string { return 'cat'; }\n",
        );
        cats_controller.push_str(&nest_handlers);
        cats_controller.push_str("}\n");
        std::fs::write(root.join("cats.controller.ts"), cats_controller)
            .expect("write Nest controller");
        std::fs::write(
            root.join("cats.service.ts"),
            "@Injectable()\n\
             export class CatsService {\n\
             \x20\x20resolveCatFromCache(): string { return 'service'; }\n\
             }\n",
        )
        .expect("write Nest service");
        std::fs::write(
            root.join("UserController.java"),
            "@RestController\n\
             @RequestMapping(\"/users\")\n\
             public class UserController {\n\
             \x20\x20@GetMapping(\"/{id}\")\n\
             \x20\x20public String getUser(int id) { return \"\"; }\n\
             }\n",
        )
        .expect("write Spring controller");
        std::fs::write(
            root.join("CatalogController.cs"),
            "using Microsoft.AspNetCore.Mvc;\n\n\
             [ApiController]\n\
             [Route(\"api/catalog\")]\n\
             public class CatalogController : ControllerBase\n\
             {\n\
             \x20\x20\x20\x20[HttpGet(\"{id}\")]\n\
             \x20\x20\x20\x20public int GetById(int id) { return id; }\n\
             }\n",
        )
        .expect("write ASP.NET controller");
        std::fs::write(
            root.join("routes.swift"),
            "import Vapor\nfunc routes(_ app: Application) throws {\n    app.get(\"/swift\") { req in \"ok\" }\n}\n",
        )
        .expect("write Vapor routes");
        std::fs::write(
            root.join("app.py"),
            "from flask import Flask\napp = Flask(__name__)\n@app.route(\"/flask\")\ndef flask_handler():\n    return \"ok\"\n",
        )
        .expect("write Flask handler");

        crate::build::run_with_force(root.to_str().unwrap(), true).expect("full build");
        let data = nav_map(&serde_json::json!({ "repoRoot": root.to_str().unwrap() }))
            .expect("nav_map computes");
        let entrypoints = data["entrypoints"].as_array().expect("entrypoints array");

        for (symbol, method, path) in [
            ("aFindOne", "GET", "/cats/:id"),
            ("getUser", "GET", "/users/{id}"),
            ("GetById", "GET", "/api/catalog/{id}"),
            ("GET /swift", "GET", "/swift"),
            ("flask_handler", "GET", "/flask"),
        ] {
            assert!(
                entrypoints.iter().any(|entrypoint| {
                    entrypoint["symbol"] == symbol
                        && entrypoint["method"] == method
                        && entrypoint["path"] == path
                }),
                "missing {method} {path} route {symbol:?}: {entrypoints:?}"
            );
        }
        assert!(
            !entrypoints
                .iter()
                .any(|entrypoint| entrypoint["symbol"] == "CatsService"),
            "ordinary Nest service must not be an entrypoint: {entrypoints:?}"
        );
        assert!(
            !entrypoints
                .iter()
                .any(|entrypoint| entrypoint["symbol"] == "resolveCatFromCache"),
            "ordinary Nest service method must not be an entrypoint: {entrypoints:?}"
        );
        assert!(
            data["guide"]["truncated"].get("entrypoints").is_none(),
            "default budget should retain all ranked entrypoints: {}",
            data["guide"]
        );

        let db = crate::db::path::repo_db_path(&root);
        let _ = std::fs::remove_file(&db);
        let _ = std::fs::remove_dir_all(&root);
    }

    /// AC2: a missing/broken index (repo path doesn't exist, so
    /// build-on-read auto-freshening itself fails) returns the uniform
    /// error envelope, not a panic or a bespoke shape.
    #[test]
    fn nav_map_missing_index_returns_error() {
        let root = temp_root("missing-index");
        let nonexistent = root.join("does-not-exist");
        let input = serde_json::json!({ "repoRoot": nonexistent.to_str().unwrap() });

        let result = nav_map(&input);
        assert!(
            result.is_err(),
            "missing/broken index must error, not succeed: {result:?}"
        );

        let _ = std::fs::remove_dir_all(&root);
    }

    /// F1: `budget_nav_map` trims sections to the token budget in priority
    /// order, caps per-subsystem members inline, and reports every cut in a
    /// `guide.truncated` block with shown/total + a follow-up hint.
    #[test]
    fn budget_trims_low_priority_first_and_reports_truncation() {
        // 30 foundational files, a subsystem with 50 members, 40 symbols,
        // and a fat flows tree — far more than a tight budget allows.
        let founds: Vec<_> = (0..30)
            .map(|i| serde_json::json!({"file": format!("src/f{i}.rs"), "dependents": i}))
            .collect();
        let members: Vec<_> = (0..50).map(|i| format!("src/m{i}.rs")).collect();
        // Above the symbols item cap (40), so it is always truncated.
        let symbols: Vec<_> = (0..200)
            .map(|i| serde_json::json!({"symbol": format!("s{i}"), "count": i}))
            .collect();
        let mut data = serde_json::json!({
            "entrypoints": [{"symbol": "main", "file": "src/main.rs", "role": "process_main"}],
            "foundational_files": founds,
            "module_layers": {"edges": [], "cycles": []},
            "subsystems": [{"id": 1, "name": "core", "members": members}],
            "symbols": symbols,
            // One flows tree bigger than the whole budget, so it can never fit.
            "flows": [{"entrypoint": "main", "root": {"symbol": "main", "children":
                (0..1000).map(|i| serde_json::json!({"symbol": format!("child_symbol_{i}")})).collect::<Vec<_>>()}}],
            "hotspots": [{"file": "src/h.rs", "score": 9}],
        });

        let guide = budget_nav_map(&mut data, 1500);
        let trunc = &guide["truncated"];

        // High-priority entrypoints survive; low-priority flows is dropped
        // (its one item is huge and the budget is gone by the time it runs).
        assert_eq!(data["entrypoints"].as_array().unwrap().len(), 1);
        assert_eq!(data["flows"].as_array().unwrap().len(), 0);
        assert_eq!(trunc["flows"]["shown"], 0);
        assert!(trunc["flows"]["total"].as_u64().unwrap() >= 1);
        assert!(
            trunc["flows"]["more"]
                .as_str()
                .unwrap()
                .contains("maxTokensEstimate")
        );

        // Subsystem members are capped inline with a membersOmitted count.
        let sub = &data["subsystems"][0];
        assert_eq!(
            sub["members"].as_array().unwrap().len(),
            SUBSYSTEM_MEMBER_CAP
        );
        assert_eq!(
            sub["membersOmitted"],
            serde_json::json!(50 - SUBSYSTEM_MEMBER_CAP)
        );

        // symbols' follow-up points at the dedicated query mode.
        assert!(
            trunc["symbols"]["more"]
                .as_str()
                .unwrap()
                .contains("filter_symbols")
        );
        assert_eq!(guide["budgetTokens"], serde_json::json!(1500));
    }

    /// Every populated orientation section gets a bounded first-item reserve
    /// before priority overflow spends the rest. This keeps later sections
    /// useful without forcing oversized items into a tiny map.
    #[test]
    fn budget_reserves_an_item_for_each_populated_orientation_section() {
        let entrypoints: Vec<_> = (0..3)
            .map(|i| {
                serde_json::json!({
                    "symbol": format!("entrypoint_{i}"),
                    "file": format!("src/entrypoint_{i}.rs"),
                    "role": "process_main",
                })
            })
            .collect();
        let foundational_files: Vec<_> = (0..5)
            .map(|i| {
                serde_json::json!({
                    "file": format!("src/foundation_{i}.rs"),
                    "dependents": i,
                })
            })
            .collect();
        let subsystems: Vec<_> = (0..5)
            .map(|i| {
                serde_json::json!({
                    "id": i,
                    "name": format!("subsystem_{i}"),
                    "members": [format!("src/subsystem_{i}.rs")],
                })
            })
            .collect();
        let flows: Vec<_> = (0..3)
            .map(|i| {
                serde_json::json!({
                    "entrypoint": format!("entrypoint_{i}"),
                    "root": {"symbol": format!("entrypoint_{i}")},
                })
            })
            .collect();
        let symbols: Vec<_> = (0..5)
            .map(|i| {
                serde_json::json!({
                    "symbol": format!("symbol_{i}"),
                    "file": format!("src/symbol_{i}.rs"),
                })
            })
            .collect();
        let hotspots: Vec<_> = (0..5)
            .map(|i| {
                serde_json::json!({
                    "file": format!("src/hotspot_{i}.rs"),
                    "score": i,
                })
            })
            .collect();
        let mut data = serde_json::json!({
            "entrypoints": entrypoints,
            "foundational_files": foundational_files,
            "module_layers": {"edges": [], "cycles": []},
            "subsystems": subsystems,
            "flows": flows,
            "symbols": symbols,
            "hotspots": hotspots,
        });

        let guide = budget_nav_map(&mut data, 1_200);

        for section in [
            "entrypoints",
            "foundational_files",
            "subsystems",
            "flows",
            "symbols",
            "hotspots",
        ] {
            assert!(
                !data[section].as_array().unwrap().is_empty(),
                "{section} must retain its bounded orientation reserve: {data}"
            );
        }
        if let Some(symbols) = guide["truncated"].get("symbols") {
            assert!(
                symbols["shown"].as_u64().unwrap() >= 1,
                "symbols must retain at least their reserve: {guide}"
            );
            assert_eq!(symbols["total"], serde_json::json!(5));
        }
        let retained_cost = [
            "entrypoints",
            "foundational_files",
            "subsystems",
            "flows",
            "symbols",
            "hotspots",
        ]
        .iter()
        .flat_map(|section| data[*section].as_array().unwrap())
        .map(est_tokens)
        .sum::<usize>()
            + est_tokens(&data["module_layers"]);
        assert!(
            retained_cost <= 1_200,
            "retained cost {retained_cost} exceeds budget"
        );
        data["guide"] = guide;
        assert!(
            est_tokens(&data) <= 1_200,
            "complete rendered map exceeds its budget: {data}"
        );
    }

    /// Regression (module_layers reservation): even when the higher-priority
    /// sections would exhaust the whole token budget, module_layers still
    /// surfaces its top edges instead of being starved to empty (the old
    /// all-or-nothing drop zeroed it on every non-trivial repo). The reserved
    /// allotment guarantees the architectural layering view is never silently
    /// dropped.
    #[test]
    fn module_layers_edges_survive_a_tight_budget() {
        // Priority sections large enough to blow the budget on their own.
        let founds: Vec<_> = (0..40)
            .map(|i| serde_json::json!({"file": format!("src/really/long/path/f{i}.rs"), "dependents": i}))
            .collect();
        let symbols: Vec<_> = (0..200)
            .map(|i| serde_json::json!({"symbol": format!("symbol_number_{i}"), "count": i}))
            .collect();
        // 15 real module-dependency edges.
        let edges: Vec<_> = (0..15)
            .map(|i| {
                serde_json::json!({
                    "from_module": format!("src/feature_{i}/endpoints"),
                    "to_module": format!("src/feature_{i}/core"),
                    "crossing_files": i + 3,
                })
            })
            .collect();
        let mut data = serde_json::json!({
            "entrypoints": [{"symbol": "main", "file": "src/main.rs", "role": "process_main"}],
            "foundational_files": founds,
            "module_layers": {"edges": edges, "cycles": []},
            "subsystems": [],
            "symbols": symbols,
            "flows": [],
            "hotspots": [{"file": "src/h.rs", "score": 9}],
        });

        let guide = budget_nav_map(&mut data, 1500);

        let kept = data["module_layers"]["edges"].as_array().unwrap().len();
        assert!(
            kept > 0,
            "module_layers edges must survive a tight budget via the reservation, got {kept}"
        );
        // If any were trimmed, the cut is reported honestly with a non-zero
        // shown count and a follow-up hint.
        if kept < 15 {
            let t = &guide["truncated"]["module_layers.edges"];
            assert_eq!(t["shown"], serde_json::json!(kept));
            assert_eq!(t["total"], serde_json::json!(15));
            assert!(t["more"].as_str().unwrap().contains("maxTokensEstimate"));
        }
    }

    /// Cycles are optional module-layer detail. Their payload must not consume
    /// the first-item reserve that keeps every populated orientation section
    /// visible under a tight budget.
    #[test]
    fn budgeted_cycles_do_not_starve_section_reserves() {
        let long_cycles: Vec<_> = (0..MODULE_LAYERS_CYCLE_CAP)
            .map(|i| serde_json::json!(format!("cycle-{i}-{}", "x".repeat(1_000))))
            .collect();
        let mut data = serde_json::json!({
            "entrypoints": [{"symbol": "main", "file": "src/main.rs"}],
            "foundational_files": [{"file": "src/core.rs", "dependents": 1}],
            "module_layers": {"edges": [{"from": "src/main.rs", "to": "src/core.rs"}], "cycles": long_cycles},
            "subsystems": [{"id": 1, "name": "core", "members": ["src/core.rs"]}],
            "flows": [{"entrypoint": "main", "root": {"symbol": "main"}}],
            "symbols": [{"symbol": "Core", "file": "src/core.rs"}],
            "hotspots": [{"file": "src/core.rs", "score": 1}],
        });

        let guide = budget_nav_map(&mut data, 1_200);

        for section in [
            "entrypoints",
            "foundational_files",
            "subsystems",
            "flows",
            "symbols",
            "hotspots",
        ] {
            assert!(
                !data[section].as_array().unwrap().is_empty(),
                "{section} lost its reserve to cycles: {data}"
            );
        }
        assert!(
            !data["module_layers"]["edges"]
                .as_array()
                .unwrap()
                .is_empty(),
            "module edges lost their reserve to cycles: {data}"
        );
        assert_eq!(
            guide["truncated"]["module_layers.cycles"]["total"],
            serde_json::json!(20)
        );
    }

    /// A normal budget covers the complete rendered map, including its guide.
    /// Below the structural lower bound, the guide explicitly reports that
    /// lower bound instead of falsely claiming the requested limit was met.
    #[test]
    fn budget_covers_rendered_map_or_reports_the_structural_lower_bound() {
        let mut data = serde_json::json!({
            "entrypoints": [{"symbol": "main", "file": "src/main.rs"}],
            "foundational_files": [],
            "module_layers": {"edges": [], "cycles": []},
            "subsystems": [],
            "flows": [],
            "symbols": [],
            "hotspots": [],
        });

        let guide = budget_nav_map(&mut data, 1);
        data["guide"] = guide;

        let minimum = data["guide"]["minimumBudgetTokens"]
            .as_u64()
            .expect("below the structural minimum, guide reports the lower bound")
            as usize;
        assert!(minimum > 1);
        assert_eq!(minimum, est_tokens(&data));
    }

    #[test]
    fn budget_spends_past_old_section_caps_and_reports_ranked_truncation() {
        let symbols: Vec<_> = (0..300)
            .map(|i| {
                serde_json::json!({
                    "symbol": format!("RankedSymbol{i}"),
                    "file": format!("src/features/feature_{i}/module.rs"),
                    "references": i,
                })
            })
            .collect();
        let mut data = serde_json::json!({
            "entrypoints": [],
            "foundational_files": [],
            "module_layers": {"edges": [], "cycles": []},
            "subsystems": [],
            "flows": [],
            "symbols": symbols,
            "hotspots": [],
        });

        let guide = budget_nav_map(&mut data, 2_000);
        let shown = data["symbols"].as_array().unwrap().len();

        assert!(
            shown > 40,
            "budget should exceed the former symbols cap: {shown}"
        );
        assert!(
            shown < 300,
            "fixture should exercise budget truncation: {shown}"
        );
        assert_eq!(
            guide["truncated"]["symbols"]["shown"],
            serde_json::json!(shown)
        );
        assert_eq!(
            guide["truncated"]["symbols"]["total"],
            serde_json::json!(300)
        );
        data["guide"] = guide;
        assert!(est_tokens(&data) <= 2_000, "rendered output exceeds budget");
    }

    /// The subsystems section drops test-file community members via the
    /// `is_test_path` column, so a test directory never pads or forms a
    /// subsystem. `src/api/helper.test.ts` (a test path) is excluded while
    /// its sibling production files remain.
    #[test]
    fn subsystems_section_excludes_test_file_members() {
        let conn = rusqlite::Connection::open_in_memory().expect("in-memory db");
        conn.execute_batch(crate::db::schema_ddl()).expect("schema");

        for path in [
            "src/api/users.rs",
            "src/api/orders.rs",
            "src/api/helper.test.ts",
        ] {
            conn.execute(
                "INSERT INTO files (path) VALUES (?1)",
                rusqlite::params![path],
            )
            .expect("insert file");
            let file_id = conn.last_insert_rowid();
            conn.execute(
                "INSERT INTO community_members (community_id, file_id) VALUES (1, ?1)",
                rusqlite::params![file_id],
            )
            .expect("insert community member");
        }

        let result = subsystems_section(&conn, &[]).expect("subsystems computes");
        let members: Vec<String> = result
            .as_array()
            .expect("array")
            .iter()
            .flat_map(|c| c["members"].as_array().expect("members array").clone())
            .map(|m| m.as_str().expect("member path").to_string())
            .collect();

        assert!(
            !members.iter().any(|m| m == "src/api/helper.test.ts"),
            "test file must be excluded from subsystem members: {members:?}"
        );
        assert!(
            members.iter().any(|m| m == "src/api/users.rs"),
            "production file should remain a member: {members:?}"
        );
    }

    /// Subsystems are emitted biggest-first so the budget's item cap surfaces
    /// the repo's largest real domains, not an arbitrary HashMap-order slice.
    /// A 3-file community must precede a 2-file one regardless of community id.
    #[test]
    fn subsystems_section_ranks_larger_domains_first() {
        let conn = rusqlite::Connection::open_in_memory().expect("in-memory db");
        conn.execute_batch(crate::db::schema_ddl()).expect("schema");

        // Community 5: a small 2-file domain. Community 9: a larger 3-file one.
        // Higher id given to the bigger community so id order can't accidentally
        // produce the expected result.
        let seed = [
            (5, "src/small/a.rs"),
            (5, "src/small/b.rs"),
            (9, "src/big/x.rs"),
            (9, "src/big/y.rs"),
            (9, "src/big/z.rs"),
        ];
        for (cid, path) in seed {
            conn.execute("INSERT INTO files (path) VALUES (?1)", [path])
                .expect("insert file");
            let file_id = conn.last_insert_rowid();
            conn.execute(
                "INSERT INTO community_members (community_id, file_id) VALUES (?1, ?2)",
                rusqlite::params![cid, file_id],
            )
            .expect("insert member");
        }

        let result = subsystems_section(&conn, &[]).expect("subsystems computes");
        let subs = result.as_array().expect("array");
        assert_eq!(subs.len(), 2, "both multi-file domains named: {result}");
        assert_eq!(
            subs[0]["members"].as_array().unwrap().len(),
            3,
            "larger domain ranks first: {result}"
        );
        assert_eq!(
            subs[1]["members"].as_array().unwrap().len(),
            2,
            "smaller domain ranks second: {result}"
        );
    }
}
