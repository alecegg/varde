//! Louvain community detection over the file graph.
//!
//! Faithful port of varde's TS `louvain()` in `community-detection.ts`:
//! greedy modularity optimization via local moving, with a resolution
//! parameter (1.0 = standard modularity). Deterministic: nodes processed in
//! id order, ties broken toward the smallest community id.

use std::collections::{BTreeMap, HashMap};

use crate::model::Entity;
use crate::resolve::{Community, EdgeTarget, FileNode, ResolvedEdge};

const MAX_PASSES: usize = 50;

/// Tolerance for the "same modularity gain" tie-break below. Two gains that
/// are mathematically equal can still differ by a few ULPs of floating-point
/// rounding; an exact `==` would pick whichever community was visited first
/// instead of the smallest id, breaking the "deterministic partition"
/// guarantee. The candidate map (`edges_to_comm`) is a `BTreeMap` so the
/// selection loop visits communities in ascending-id order and, combined with
/// this epsilon + id tie-break, produces bit-for-bit reproducible partitions
/// across runs (a `HashMap`'s per-run seed would otherwise vary the order).
const GAIN_EPSILON: f64 = 1e-9;

/// Detect communities over the file graph and assign `community_id` on each
/// node. Edges considered: every resolved file-to-file connection — import
/// edges (`EdgeTarget::File`) directly, call edges (`EdgeTarget::Entity`)
/// via the invoked entity's declaring file — weighted symmetrically (matches
/// the fan-metric semantics).
///
/// Returns communities keyed by a stable id (lex-smallest member path wins
/// the label, then sorted).
pub fn detect(
    nodes: &mut [FileNode],
    edges: &[ResolvedEdge],
    entities: &[Entity],
) -> Vec<Community> {
    let n = nodes.len();
    if n == 0 {
        return Vec::new();
    }
    let (adj, total_edges) = build_adjacency(n, edges, entities);
    if total_edges == 0.0 {
        return singleton_communities(nodes);
    }
    let degree: Vec<f64> = adj
        .iter()
        .map(|neighbors| neighbors.values().sum())
        .collect();
    let community = optimize_communities(&adj, &degree, total_edges);
    let comm_label = community_labels(nodes, &community);
    assign_communities(nodes, &community, &comm_label)
}

fn build_adjacency(
    count: usize,
    edges: &[ResolvedEdge],
    entities: &[Entity],
) -> (Vec<HashMap<usize, f64>>, f64) {
    let mut adj = vec![HashMap::new(); count];
    let mut total_edges = 0.0;
    for edge in edges.iter().filter(|edge| edge.resolved) {
        let Some(to) = edge_target_file(edge, entities) else {
            continue;
        };
        let from = edge.from as usize;
        if from == to {
            continue;
        }
        *adj[from].entry(to).or_insert(0.0) += 1.0;
        *adj[to].entry(from).or_insert(0.0) += 1.0;
        total_edges += 1.0;
    }
    (adj, total_edges)
}

fn edge_target_file(edge: &ResolvedEdge, entities: &[Entity]) -> Option<usize> {
    match edge.to {
        EdgeTarget::File(file_id) => Some(file_id as usize),
        EdgeTarget::Entity(entity_id) => entities
            .get(entity_id as usize)
            .map(|entity| entity.file_id as usize),
        EdgeTarget::Unknown => None,
    }
}

fn singleton_communities(nodes: &mut [FileNode]) -> Vec<Community> {
    nodes
        .iter_mut()
        .enumerate()
        .map(|(id, node)| {
            node.community_id = Some(id as u32);
            Community {
                id: id as u32,
                members: vec![node.path.clone()],
            }
        })
        .collect()
}

fn optimize_communities(
    adjacency: &[HashMap<usize, f64>],
    degree: &[f64],
    edge_weight: f64,
) -> Vec<usize> {
    let mut community: Vec<usize> = (0..adjacency.len()).collect();
    let mut sigma_tot = degree.to_vec();
    for _ in 0..MAX_PASSES {
        if !move_community_pass(
            adjacency,
            degree,
            edge_weight,
            &mut community,
            &mut sigma_tot,
        ) {
            break;
        }
    }
    community
}

fn move_community_pass(
    adjacency: &[HashMap<usize, f64>],
    degree: &[f64],
    edge_weight: f64,
    community: &mut [usize],
    sigma_tot: &mut [f64],
) -> bool {
    let mut changed = false;
    for node in 0..adjacency.len() {
        let weights = neighboring_community_weights(node, adjacency, community);
        let current = community[node];
        let best = best_community(current, degree[node], edge_weight, sigma_tot, &weights);
        if best == current {
            continue;
        }
        sigma_tot[current] -= degree[node];
        sigma_tot[best] += degree[node];
        community[node] = best;
        changed = true;
    }
    changed
}

fn neighboring_community_weights(
    node: usize,
    adjacency: &[HashMap<usize, f64>],
    community: &[usize],
) -> BTreeMap<usize, f64> {
    let mut weights = BTreeMap::new();
    for (neighbor, weight) in &adjacency[node] {
        *weights.entry(community[*neighbor]).or_insert(0.0) += weight;
    }
    weights
}

fn best_community(
    current: usize,
    degree: f64,
    edge_weight: f64,
    sigma_tot: &[f64],
    weights: &BTreeMap<usize, f64>,
) -> usize {
    let current_weight = weights.get(&current).copied().unwrap_or(0.0);
    let denominator = 2.0 * edge_weight * edge_weight;
    let removal =
        -current_weight / edge_weight + degree * (sigma_tot[current] - degree) / denominator;
    let mut best = (current, 0.0);
    for (&candidate, &candidate_weight) in weights {
        if candidate == current {
            continue;
        }
        let gain =
            removal + candidate_weight / edge_weight - degree * sigma_tot[candidate] / denominator;
        if better_gain(candidate, gain, best) {
            best = (candidate, gain);
        }
    }
    best.0
}

fn better_gain(candidate: usize, gain: f64, best: (usize, f64)) -> bool {
    gain > best.1 + GAIN_EPSILON || ((gain - best.1).abs() <= GAIN_EPSILON && candidate < best.0)
}

fn community_labels(nodes: &[FileNode], community: &[usize]) -> HashMap<usize, String> {
    let mut labels = HashMap::new();
    for (node, &community_id) in nodes.iter().zip(community) {
        let label = labels
            .entry(community_id)
            .or_insert_with(|| node.path.clone());
        if node.path < *label {
            *label = node.path.clone();
        }
    }
    labels
}

/// Renumber the raw community assignment into stable `Community`s and set
/// each node's `community_id`. Labels are the lex-smallest member path;
/// ids are assigned in sorted-label order.
fn assign_communities(
    nodes: &mut [FileNode],
    community: &[usize],
    comm_label: &HashMap<usize, String>,
) -> Vec<Community> {
    let mut labels: Vec<&str> = comm_label.values().map(String::as_str).collect();
    labels.sort_unstable();
    let mut id_by_label: HashMap<&str, u32> = HashMap::new();
    for (id, label) in labels.into_iter().enumerate() {
        id_by_label.insert(label, id as u32);
    }

    let mut members_by_id: HashMap<u32, Vec<String>> = HashMap::new();
    for (i, node) in nodes.iter_mut().enumerate() {
        let id = id_by_label[comm_label[&community[i]].as_str()];
        node.community_id = Some(id);
        members_by_id.entry(id).or_default().push(node.path.clone());
    }

    let mut communities: Vec<Community> = members_by_id
        .into_iter()
        .map(|(id, mut members)| {
            members.sort();
            Community { id, members }
        })
        .collect();
    communities.sort_by_key(|c| c.id);
    communities
}
