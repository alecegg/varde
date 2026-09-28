//! Reverse symbol traversal over resolved calls and inheritance relationships.
//! File imports are not evidence that a particular declaration is referenced.

use std::collections::{BTreeSet, HashMap, HashSet, VecDeque};

use crate::model::EntityKind;
use crate::resolve::EdgeKind;

use super::simple::matches_path;
use super::{ApiError, db_err, freshen_for_mode, open_db, opt_str, req_str};

struct Node {
    id: i64,
    file: i64,
    path: String,
    kind: EntityKind,
    name: String,
    start: i64,
    end: i64,
}

fn declaration(kind: EntityKind) -> bool {
    matches!(
        kind,
        EntityKind::Function
            | EntityKind::Class
            | EntityKind::Interface
            | EntityKind::Variable
            | EntityKind::Parameter
    )
}

struct Source {
    file: i64,
    owner: Option<i64>,
}

/// A call belongs to its nearest callable span. Anonymous boundaries stop
/// propagation: attributing them to the surrounding function invents a link.
fn call_owner(site: &Node, callables: &HashMap<i64, Vec<&Node>>) -> Option<i64> {
    let candidates = callables.get(&site.file)?;
    let mut enclosing: Vec<_> = candidates
        .iter()
        .filter(|node| node.start <= site.start && node.end >= site.end && node.end > node.start)
        .collect();
    enclosing.sort_by_key(|node| node.end - node.start);
    let nearest = enclosing.first()?;
    if nearest.kind == EntityKind::CallableBoundary
        || enclosing
            .get(1)
            .is_some_and(|other| other.end - other.start == nearest.end - nearest.start)
    {
        return None;
    }
    Some(nearest.id)
}

fn load_nodes(tx: &rusqlite::Connection) -> Result<HashMap<i64, Node>, ApiError> {
    let mut stmt = tx
        .prepare("SELECT e.id, e.file_id, f.path, e.kind, e.name, e.start_byte, e.end_byte FROM entities e JOIN files f ON f.id = e.file_id WHERE e.kind IN (0, 1, 2, 3, 4, 5, 6, 19)")
        .map_err(db_err)?;
    let rows = stmt
        .query_map([], |row| {
            Ok(Node {
                id: row.get(0)?,
                file: row.get(1)?,
                path: row.get(2)?,
                kind: EntityKind::from_i64(row.get(3)?).expect("query selects known kinds"),
                name: row.get(4)?,
                start: row.get(5)?,
                end: row.get(6)?,
            })
        })
        .map_err(db_err)?;
    rows.map(|row| row.map(|node| (node.id, node)))
        .collect::<rusqlite::Result<_>>()
        .map_err(db_err)
}

fn select_seed<'a>(
    input: &serde_json::Value,
    nodes: &'a HashMap<i64, Node>,
) -> Result<&'a Node, ApiError> {
    let name = req_str(input, "name")?;
    let file = opt_str(input, "filePath");
    let kind = opt_str(input, "kind");
    for field in ["filePath", "kind"] {
        if input.get(field).is_some_and(|value| !value.is_string()) {
            return Err(ApiError::new(
                "invalid_input",
                format!("{field} must be a string"),
            ));
        }
    }
    let kind = kind
        .map(|kind| {
            (0..=4)
                .filter_map(EntityKind::from_i64)
                .find(|candidate| candidate.as_str() == kind)
                .ok_or_else(|| {
                    ApiError::new(
                        "invalid_input",
                        format!("{kind:?} is not a declaration kind"),
                    )
                })
        })
        .transpose()?;
    let mut seeds = nodes.values().filter(|node| {
        declaration(node.kind)
            && node.name == name
            && kind.is_none_or(|kind| node.kind == kind)
            && file.is_none_or(|file| matches_path(&node.path, file))
    });
    let seed = seeds
        .next()
        .ok_or_else(|| ApiError::not_found(format!("declaration {name:?}")))?;
    if seeds.next().is_some() {
        return Err(ApiError::new(
            "ambiguous_symbol",
            format!(
                "multiple declarations match {name:?}; narrow filePath or kind (same-file overloads remain ambiguous)"
            ),
        ));
    }
    Ok(seed)
}

type Reverse = HashMap<i64, Vec<Source>>;

/// Imported calls can target an export wrapper. Require containment so a
/// re-export cannot accidentally resolve to an unrelated local declaration.
fn canonical_targets(nodes: &HashMap<i64, Node>) -> HashMap<i64, i64> {
    let mut declarations: HashMap<(i64, &str), Vec<&Node>> = HashMap::new();
    let mut targets = HashMap::new();
    for node in nodes.values().filter(|node| declaration(node.kind)) {
        declarations
            .entry((node.file, &node.name))
            .or_default()
            .push(node);
        targets.insert(node.id, node.id);
    }
    for wrapper in nodes
        .values()
        .filter(|node| node.kind == EntityKind::Export)
    {
        let mut candidates = declarations
            .get(&(wrapper.file, wrapper.name.as_str()))
            .into_iter()
            .flatten()
            .filter(|node| wrapper.start <= node.start && wrapper.end >= node.end);
        if let Some(node) = candidates.next()
            && candidates.next().is_none()
        {
            targets.insert(wrapper.id, node.id);
        }
    }
    targets
}

fn load_reverse(
    tx: &rusqlite::Connection,
    nodes: &HashMap<i64, Node>,
) -> Result<(Reverse, usize), ApiError> {
    let mut callables: HashMap<i64, Vec<&Node>> = HashMap::new();
    for node in nodes.values() {
        if matches!(
            node.kind,
            EntityKind::Function | EntityKind::CallableBoundary
        ) {
            callables.entry(node.file).or_default().push(node);
        }
    }
    let targets = canonical_targets(nodes);
    let mut stmt = tx.prepare("SELECT from_file_id, from_entity_id, to_entity_id, kind, resolved FROM resolved_edges WHERE kind IN (0, 2, 3)").map_err(db_err)?;
    let rows = stmt
        .query_map([], |row| {
            Ok((
                row.get::<_, i64>(0)?,
                row.get::<_, Option<i64>>(1)?,
                row.get::<_, Option<i64>>(2)?,
                row.get::<_, i64>(3)?,
                row.get::<_, bool>(4)?,
            ))
        })
        .map_err(db_err)?;
    let mut reverse: HashMap<i64, Vec<Source>> = HashMap::new();
    let mut unresolved_edges = 0;
    for row in rows {
        let (file, source, target, edge_kind, resolved) = row.map_err(db_err)?;
        let Some(target) = target
            .filter(|_| resolved)
            .and_then(|id| targets.get(&id).copied())
        else {
            unresolved_edges += 1;
            continue;
        };
        let source = source.and_then(|id| nodes.get(&id));
        let owner = source.and_then(|source| {
            if declaration(source.kind) {
                Some(source.id)
            } else if edge_kind == EdgeKind::Call.as_i64() {
                call_owner(source, &callables)
            } else {
                None
            }
        });
        reverse
            .entry(target)
            .or_default()
            .push(Source { file, owner });
    }
    Ok((reverse, unresolved_edges))
}

fn affected_files(reverse: &Reverse, seed: i64) -> (BTreeSet<i64>, usize) {
    let mut files = BTreeSet::new();
    let mut visited = HashSet::from([seed]);
    let mut queue = VecDeque::from([seed]);
    let mut unmapped_owners = 0;
    while let Some(target) = queue.pop_front() {
        for source in reverse.get(&target).into_iter().flatten() {
            if source.owner == Some(seed) {
                continue;
            }
            files.insert(source.file);
            if let Some(owner) = source.owner {
                if visited.insert(owner) {
                    queue.push_back(owner);
                }
            } else {
                unmapped_owners += 1;
            }
        }
    }
    (files, unmapped_owners)
}

fn impact_paths(tx: &rusqlite::Connection, files: &BTreeSet<i64>) -> Result<Vec<String>, ApiError> {
    let mut stmt = tx
        .prepare("SELECT id, path FROM files ORDER BY path")
        .map_err(db_err)?;
    stmt.query_map([], |row| {
        Ok((row.get::<_, i64>(0)?, row.get::<_, String>(1)?))
    })
    .map_err(db_err)?
    .filter_map(|row| match row {
        Ok((id, path)) if files.contains(&id) => Some(Ok(path)),
        Ok(_) => None,
        Err(error) => Some(Err(error)),
    })
    .collect::<rusqlite::Result<Vec<_>>>()
    .map_err(db_err)
}

pub(super) fn run(input: &serde_json::Value) -> Result<serde_json::Value, ApiError> {
    freshen_for_mode("symbol_blast_radius", input)?;
    let conn = open_db(input)?;
    // Pin entities, ownership spans, and edges to one watcher generation.
    let tx = conn.unchecked_transaction().map_err(db_err)?;
    let nodes = load_nodes(&tx)?;
    let seed = select_seed(input, &nodes)?;
    let (reverse, unresolved_edges) = load_reverse(&tx, &nodes)?;
    let (files, unmapped_owners) = affected_files(&reverse, seed.id);
    let impact = impact_paths(&tx, &files)?;
    Ok(serde_json::json!({
        "declaring_file": seed.path,
        "blast_radius": impact,
        "analysis": {
            "status": "partial",
            "basis": "resolved_calls_and_inheritance",
            "unresolved_edges": unresolved_edges,
            "unmapped_owners": unmapped_owners,
            "limitations": [
                "Arbitrary data references and dynamic dispatch are not fully indexed; empty impact does not prove isolation.",
                "Calls without a unique named callable owner, including anonymous callbacks, report their file but stop symbol propagation."
            ]
        }
    }))
}
