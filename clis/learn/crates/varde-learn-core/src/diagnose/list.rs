use std::collections::{HashMap, HashSet};
use std::fs;
use std::io::Read;
use std::path::{Component, Path, PathBuf};

use serde::Serialize;
use serde_json::Value;
use time::{OffsetDateTime, format_description::well_known::Rfc3339};

use super::{DiscoveredSession, MAX_DISCOVERY_FILES, claude, codex, error, opencode};
use crate::LearnError;
use crate::session_link::{CandidateSession, ParentSession, link_workers};

const MAX_PASEO_RECORD_BYTES: u64 = 64 * 1024;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ListHarness {
    Codex,
    Claude,
    Opencode,
    All,
}

#[derive(Debug, Clone)]
pub struct ListRequest {
    pub harness: ListHarness,
    pub repo: PathBuf,
    pub codex_home: PathBuf,
    pub claude_projects_root: PathBuf,
    pub opencode_data_root: PathBuf,
    pub paseo_home: Option<PathBuf>,
    pub limit: usize,
    pub run: Option<String>,
}

#[derive(Debug, Serialize)]
pub struct SessionList {
    pub sessions: Vec<ListedSession>,
    #[serde(skip)]
    pub warnings: Vec<String>,
}

#[derive(Debug, Serialize)]
pub struct ListedSession {
    pub harness: String,
    pub session_id: String,
    pub source: String,
    pub link: Value,
    pub started_at: Option<String>,
    pub cwd: Option<String>,
    pub root: Value,
    pub workers: Vec<ListedWorker>,
}

#[derive(Debug, Serialize)]
pub struct ListedWorker {
    pub harness: String,
    pub session_id: String,
    pub source: String,
    pub link: Value,
}

#[derive(Debug)]
struct PaseoAgent {
    id: String,
    provider: String,
    session_id: String,
    parent_agent_id: Option<String>,
}

pub fn list_sessions(request: &ListRequest) -> Result<SessionList, LearnError> {
    if !(1..=10).contains(&request.limit) {
        return Err(error("usage_error", "--limit must be between 1 and 10"));
    }
    if request
        .run
        .as_deref()
        .is_some_and(|session_id| session_id.trim().is_empty())
    {
        return Err(error("usage_error", "--run requires a session ID"));
    }
    let repo = request.repo.canonicalize().map_err(|cause| {
        error(
            "diagnose_repo_invalid",
            format!("cannot resolve --repo: {cause}"),
        )
    })?;

    let mut candidates = Vec::new();
    let mut archived_codex = HashSet::new();
    let mut codex_tool_results = HashMap::<String, Vec<String>>::new();
    let mut warnings = Vec::new();
    let mut readable_source_found = false;
    if matches!(request.harness, ListHarness::Codex | ListHarness::All) {
        match codex::list_sessions(&request.codex_home, &repo) {
            Ok(discovery) => {
                readable_source_found |= discovery.has_readable_source;
                if !discovery.has_readable_source && request.harness == ListHarness::All {
                    warnings.push(
                        "Codex discovery found no readable rollout metadata; Codex sessions were skipped".into(),
                    );
                }
                candidates.extend(discovery.sessions);
                archived_codex.extend(discovery.archived);
                codex_tool_results.extend(discovery.tool_call_results);
                warnings.extend(discovery.warnings);
            }
            Err(_) if request.harness == ListHarness::All => {
                warnings.push(
                    "Codex session source could not be read; Codex sessions were skipped".into(),
                );
            }
            Err(cause) => return Err(cause),
        }
    }
    if matches!(request.harness, ListHarness::Claude | ListHarness::All) {
        match claude::list_sessions(&request.claude_projects_root, &repo) {
            Ok(discovery) => {
                readable_source_found |= discovery.has_readable_source;
                if !discovery.has_readable_source && request.harness == ListHarness::All {
                    warnings.push(
                        "Claude discovery found no readable session metadata; Claude sessions were skipped".into(),
                    );
                }
                candidates.extend(discovery.sessions);
                warnings.extend(discovery.warnings);
            }
            Err(_) if request.harness == ListHarness::All => warnings.push(
                "Claude session source could not be read; Claude sessions were skipped".into(),
            ),
            Err(cause) => return Err(cause),
        }
    }
    if matches!(request.harness, ListHarness::Opencode | ListHarness::All) {
        match opencode::list_sessions(&request.opencode_data_root, &repo) {
            Ok(discovery) => {
                readable_source_found |= discovery.has_readable_source;
                if !discovery.has_readable_source && request.harness == ListHarness::All {
                    warnings.push(
                        "OpenCode discovery found no readable session metadata; OpenCode sessions were skipped".into(),
                    );
                }
                candidates.extend(discovery.sessions);
                warnings.extend(discovery.warnings);
            }
            Err(_) if request.harness == ListHarness::All => warnings.push(
                "OpenCode session source could not be read; OpenCode sessions were skipped".into(),
            ),
            Err(cause) => return Err(cause),
        }
    }

    candidates.retain(|candidate| {
        !candidate.retro_analyst
            && candidate
                .cwd
                .as_deref()
                .is_some_and(|cwd| cwd_is_in_repo(cwd, &repo))
    });

    if request.harness != ListHarness::All && !readable_source_found {
        let harness = match request.harness {
            ListHarness::Codex => "Codex",
            ListHarness::Claude => "Claude",
            ListHarness::Opencode => "OpenCode",
            ListHarness::All => unreachable!(),
        };
        return Err(error(
            "diagnose_source_invalid",
            format!("no readable {harness} session source was found"),
        ));
    }
    if request.harness == ListHarness::All && !readable_source_found {
        return Err(error(
            "diagnose_source_invalid",
            "no readable session source was found for the selected harnesses",
        ));
    }

    let paseo_agents = match request.paseo_home.as_deref() {
        Some(home) => match read_paseo_agents(home) {
            Ok(agents) => agents,
            Err(_) => {
                warnings.push(
                    "Paseo agent records could not be read; Paseo linkage was skipped and native parent links were used where available".into(),
                );
                Vec::new()
            }
        },
        None => Vec::new(),
    };
    let mut paseo_by_id = HashMap::new();
    let mut duplicate_agent_ids = HashSet::new();
    for agent in &paseo_agents {
        if paseo_by_id.insert(agent.id.clone(), agent).is_some() {
            duplicate_agent_ids.insert(agent.id.clone());
        }
    }
    for duplicate in &duplicate_agent_ids {
        paseo_by_id.remove(duplicate);
    }
    let mut paseo_candidate = HashMap::<String, usize>::new();
    for agent in &paseo_agents {
        if duplicate_agent_ids.contains(&agent.id) {
            continue;
        }
        let Some(candidate) = find_paseo_candidate(agent, &candidates) else {
            continue;
        };
        paseo_candidate.insert(agent.id.clone(), candidate);
    }

    let mut paseo_parent = HashMap::<usize, Option<usize>>::new();
    for agent in &paseo_agents {
        let Some(parent_agent_id) = agent.parent_agent_id.as_deref() else {
            continue;
        };
        let Some(&child) = paseo_candidate.get(&agent.id) else {
            continue;
        };
        let parent = paseo_by_id
            .get(parent_agent_id)
            .and_then(|parent| paseo_candidate.get(&parent.id))
            .copied();
        // A recorded Paseo parent takes precedence even when it cannot be
        // resolved inside this repository's filtered session set.
        paseo_parent.insert(child, parent);
    }

    let by_identity = candidates.iter().enumerate().fold(
        HashMap::<&str, Vec<usize>>::new(),
        |mut map, (index, candidate)| {
            map.entry(&candidate.identity).or_default().push(index);
            map
        },
    );
    let mut parents = vec![None; candidates.len()];
    let mut roots_known = vec![false; candidates.len()];
    let parent_sessions = candidates
        .iter()
        .filter(|candidate| candidate.harness == "codex")
        .map(|candidate| ParentSession {
            session_id: &candidate.session_id,
            tool_call_results: codex_tool_results
                .get(&candidate.session_id)
                .map(Vec::as_slice)
                .unwrap_or(&[]),
        })
        .collect::<Vec<_>>();
    let tool_candidates = candidates
        .iter()
        .filter(|candidate| candidate.harness == "codex")
        .map(|candidate| CandidateSession {
            session_id: &candidate.session_id,
        })
        .collect::<Vec<_>>();
    let tool_links = link_workers(&parent_sessions, &tool_candidates);
    let tool_link_by_id = candidates
        .iter()
        .filter(|candidate| candidate.harness == "codex")
        .zip(tool_links)
        .map(|(candidate, link)| (candidate.identity.clone(), link))
        .collect::<HashMap<_, _>>();
    for (index, candidate) in candidates.iter().enumerate() {
        if let Some(parent) = paseo_parent.get(&index) {
            parents[index] = *parent;
            roots_known[index] = parent.is_some();
        } else if let Some(identity) = candidate.parent_identity.as_deref() {
            if let Some(matches) = by_identity.get(identity)
                && let [parent] = matches.as_slice()
                && *parent != index
            {
                parents[index] = Some(*parent);
            }
            roots_known[index] = false;
        } else if let Some(Ok(Some(link))) = tool_link_by_id.get(&candidate.identity) {
            let matches = candidates
                .iter()
                .enumerate()
                .filter(|(_, parent)| {
                    parent.session_id == link.parent_id && parent.harness == "codex"
                })
                .map(|(parent, _)| parent)
                .collect::<Vec<_>>();
            if let [parent] = matches.as_slice() {
                parents[index] = Some(*parent);
                roots_known[index] = true;
            }
        } else {
            roots_known[index] = candidate.parent_known;
        }
    }

    let roots = candidates
        .iter()
        .enumerate()
        .map(|(index, _)| resolve_root(index, &parents, &roots_known))
        .collect::<Vec<_>>();
    let mut root_indices = (0..candidates.len())
        .filter(|index| roots[*index].0 == *index)
        .collect::<Vec<_>>();
    root_indices.sort_by(|left, right| compare_recency(&candidates[*left], &candidates[*right]));

    let selected_roots = if let Some(run) = request.run.as_deref() {
        let mut matches = candidates
            .iter()
            .enumerate()
            .filter(|(_, candidate)| candidate.session_id == run)
            .map(|(index, _)| index)
            .collect::<Vec<_>>();
        if matches.is_empty() {
            matches = candidates
                .iter()
                .enumerate()
                .filter(|(_, candidate)| candidate.aliases.iter().any(|alias| alias == run))
                .map(|(index, _)| index)
                .collect();
        }
        match matches.as_slice() {
            [index] => vec![roots[*index].0],
            [] => {
                return Err(error(
                    "diagnose_session_not_found",
                    format!("session `{run}` was not found in --repo"),
                ));
            }
            _ => {
                return Err(error(
                    "diagnose_session_ambiguous",
                    format!("session `{run}` matches multiple harness sessions"),
                ));
            }
        }
    } else {
        let mut selected = Vec::new();
        if request.harness == ListHarness::All {
            // Keep each available harness visible when the limit can include them all.
            let mut representatives = Vec::new();
            for harness in ["codex", "claude", "opencode"] {
                if let Some(root_index) = root_indices
                    .iter()
                    .copied()
                    .find(|index| candidates[*index].harness == harness)
                {
                    representatives.push(root_index);
                }
            }
            if representatives.len() <= request.limit {
                selected = representatives;
            }
        }
        for root_index in &root_indices {
            if selected.len() == request.limit {
                break;
            }
            if !selected.contains(root_index) {
                selected.push(*root_index);
            }
        }
        selected.sort_by(|left, right| compare_recency(&candidates[*left], &candidates[*right]));
        selected
    };

    let mut sessions = Vec::with_capacity(selected_roots.len());
    for root_index in selected_roots {
        let root = &candidates[root_index];
        let mut worker_indices = candidates
            .iter()
            .enumerate()
            .filter(|(index, _)| *index != root_index && roots[*index].0 == root_index)
            .map(|(index, _)| index)
            .collect::<Vec<_>>();
        worker_indices.sort_by(|left, right| {
            compare_recency(&candidates[*left], &candidates[*right])
                .then_with(|| candidates[*left].harness.cmp(candidates[*right].harness))
        });
        let workers = worker_indices
            .into_iter()
            .map(|index| ListedWorker {
                harness: candidates[index].harness.to_owned(),
                session_id: candidates[index].session_id.clone(),
                source: if archived_codex.contains(&candidates[index].identity) {
                    "archived".into()
                } else {
                    "active".into()
                },
                link: worker_link_value(&candidates[index], &tool_link_by_id),
            })
            .collect::<Vec<_>>();
        sessions.push(ListedSession {
            harness: root.harness.to_owned(),
            session_id: root.session_id.clone(),
            source: if archived_codex.contains(&root.identity) {
                "archived".into()
            } else {
                "active".into()
            },
            link: root_link_value(root),
            started_at: root.started_at.clone(),
            cwd: root.cwd.clone(),
            root: if roots[root_index].1 {
                Value::Bool(true)
            } else {
                Value::String("unknown".into())
            },
            workers,
        });
    }
    Ok(SessionList { sessions, warnings })
}

fn worker_link_value(
    candidate: &DiscoveredSession,
    tool_links: &HashMap<String, Result<Option<crate::session_link::WorkerLink>, Vec<String>>>,
) -> Value {
    if let Some(parent_id) = candidate.parent_identity.as_deref() {
        return serde_json::json!({"parent_id": parent_id, "evidence": parent_id});
    }
    match tool_links.get(&candidate.identity) {
        Some(Ok(Some(link))) => {
            serde_json::json!({"parent_id": format!("codex:{}", link.parent_id), "evidence": link.evidence})
        }
        _ => Value::String("unlinked".into()),
    }
}

fn root_link_value(candidate: &DiscoveredSession) -> Value {
    candidate.parent_identity.as_deref().map_or_else(
        || Value::String("unlinked".into()),
        |parent_id| serde_json::json!({"parent_id": parent_id, "evidence": parent_id}),
    )
}

fn resolve_root(start: usize, parents: &[Option<usize>], roots_known: &[bool]) -> (usize, bool) {
    let mut current = start;
    let mut seen = HashSet::new();
    loop {
        if !seen.insert(current) {
            return (start, false);
        }
        match parents[current] {
            Some(parent) => current = parent,
            None => return (current, roots_known[current]),
        }
    }
}

fn find_paseo_candidate(agent: &PaseoAgent, candidates: &[DiscoveredSession]) -> Option<usize> {
    let provider = canonical_provider(&agent.provider)?;
    let matches = candidates
        .iter()
        .enumerate()
        .filter(|(_, candidate)| {
            candidate.harness == provider && candidate.aliases.contains(&agent.session_id)
        })
        .collect::<Vec<_>>();
    let agent_matches = matches
        .iter()
        .filter(|(_, candidate)| candidate.aliases.contains(&agent.id))
        .map(|(index, _)| *index)
        .collect::<Vec<_>>();
    match agent_matches.as_slice() {
        [index] => return Some(*index),
        [] => {}
        _ => return None,
    }
    let public_matches = matches
        .iter()
        .filter(|(_, candidate)| candidate.session_id == agent.session_id)
        .map(|(index, _)| *index)
        .collect::<Vec<_>>();
    if let [index] = public_matches.as_slice() {
        return Some(*index);
    }
    match matches.as_slice() {
        [(index, _)] => Some(*index),
        _ => None,
    }
}

fn canonical_provider(provider: &str) -> Option<&'static str> {
    match provider.to_ascii_lowercase().as_str() {
        "codex" => Some("codex"),
        "claude" => Some("claude"),
        "opencode" => Some("opencode"),
        _ => None,
    }
}

fn read_paseo_agents(home: &Path) -> Result<Vec<PaseoAgent>, LearnError> {
    let root = home.join("agents");
    let providers = match fs::read_dir(root) {
        Ok(providers) => providers,
        Err(cause) if cause.kind() == std::io::ErrorKind::NotFound => return Ok(Vec::new()),
        Err(cause) => {
            return Err(error(
                "diagnose_paseo_discovery_failed",
                format!("cannot scan Paseo agent records: {cause}"),
            ));
        }
    };
    let mut agents = Vec::new();
    let mut scanned = 0usize;
    for provider in providers {
        scanned += 1;
        if scanned > MAX_DISCOVERY_FILES {
            return Err(error(
                "diagnose_discovery_incomplete",
                "Paseo agent discovery exceeded its entry bound",
            ));
        }
        let provider = provider.map_err(|cause| {
            error(
                "diagnose_paseo_discovery_failed",
                format!("cannot read Paseo agent directory entry: {cause}"),
            )
        })?;
        let kind = provider.file_type().map_err(|cause| {
            error(
                "diagnose_paseo_discovery_failed",
                format!("cannot inspect Paseo agent directory: {cause}"),
            )
        })?;
        if !kind.is_dir() || kind.is_symlink() {
            continue;
        }
        let records = fs::read_dir(provider.path()).map_err(|cause| {
            error(
                "diagnose_paseo_discovery_failed",
                format!("cannot scan Paseo agent records: {cause}"),
            )
        })?;
        for entry in records {
            let entry = entry.map_err(|cause| {
                error(
                    "diagnose_paseo_discovery_failed",
                    format!("cannot read Paseo agent record entry: {cause}"),
                )
            })?;
            scanned += 1;
            if scanned > MAX_DISCOVERY_FILES {
                return Err(error(
                    "diagnose_discovery_incomplete",
                    "Paseo agent discovery exceeded its entry bound",
                ));
            }
            let path = entry.path();
            if path.extension().and_then(|ext| ext.to_str()) != Some("json") {
                continue;
            }
            let kind = entry.file_type().map_err(|cause| {
                error(
                    "diagnose_paseo_discovery_failed",
                    format!("cannot inspect Paseo agent record: {cause}"),
                )
            })?;
            if !kind.is_file() || kind.is_symlink() {
                continue;
            }
            let metadata = entry.metadata().map_err(|cause| {
                error(
                    "diagnose_paseo_discovery_failed",
                    format!("cannot stat Paseo agent record: {cause}"),
                )
            })?;
            if metadata.len() > MAX_PASEO_RECORD_BYTES {
                return Err(error(
                    "diagnose_discovery_incomplete",
                    "Paseo agent record exceeded its byte bound",
                ));
            }
            let file = fs::File::open(&path).map_err(|cause| {
                error(
                    "diagnose_paseo_discovery_failed",
                    format!("cannot read Paseo agent record: {cause}"),
                )
            })?;
            let mut bytes = Vec::new();
            file.take(MAX_PASEO_RECORD_BYTES + 1)
                .read_to_end(&mut bytes)
                .map_err(|cause| {
                    error(
                        "diagnose_paseo_discovery_failed",
                        format!("cannot read Paseo agent record: {cause}"),
                    )
                })?;
            if bytes.len() as u64 > MAX_PASEO_RECORD_BYTES {
                return Err(error(
                    "diagnose_discovery_incomplete",
                    "Paseo agent record exceeded its byte bound",
                ));
            }
            let value = serde_json::from_slice::<Value>(&bytes).map_err(|cause| {
                error(
                    "diagnose_paseo_discovery_incomplete",
                    format!("cannot parse Paseo agent record: {cause}"),
                )
            })?;
            let (Some(id), Some(provider), Some(session_id)) = (
                path.file_stem().and_then(|id| id.to_str()),
                value.get("provider").and_then(Value::as_str),
                value
                    .pointer("/persistence/sessionId")
                    .and_then(Value::as_str),
            ) else {
                continue;
            };
            if id.is_empty() || session_id.is_empty() {
                continue;
            }
            let parent_agent_id = value
                .pointer("/labels/paseo.parent-agent-id")
                .and_then(Value::as_str)
                .filter(|parent| !parent.is_empty())
                .map(str::to_owned);
            agents.push(PaseoAgent {
                id: id.to_owned(),
                provider: provider.to_owned(),
                session_id: session_id.to_owned(),
                parent_agent_id,
            });
        }
    }
    Ok(agents)
}

pub(super) fn cwd_is_in_repo(cwd: &str, repo: &Path) -> bool {
    let raw = Path::new(cwd);
    if !raw.is_absolute() || is_sandbox_path(raw) {
        return false;
    }
    let repo = normalize_path(repo);
    let resolved = raw.canonicalize().unwrap_or_else(|_| normalize_path(raw));
    resolved.starts_with(repo)
}

fn is_sandbox_path(path: &Path) -> bool {
    path.components().any(|component| {
        let Component::Normal(name) = component else {
            return false;
        };
        let Some(name) = name.to_str() else {
            return false;
        };
        let Some((prefix, suffix)) = name.split_once("-sbox-") else {
            return false;
        };
        prefix.starts_with("varde-learn-")
            && prefix.len() > "varde-learn-".len()
            && !suffix.is_empty()
    })
}

fn normalize_path(path: &Path) -> PathBuf {
    let mut normalized = PathBuf::new();
    for component in path.components() {
        match component {
            Component::CurDir => {}
            Component::ParentDir => {
                normalized.pop();
            }
            component => normalized.push(component.as_os_str()),
        }
    }
    normalized
}

fn compare_recency(left: &DiscoveredSession, right: &DiscoveredSession) -> std::cmp::Ordering {
    timestamp_key(&right.started_at)
        .cmp(&timestamp_key(&left.started_at))
        .then_with(|| left.session_id.cmp(&right.session_id))
}

fn timestamp_key(timestamp: &Option<String>) -> Option<i128> {
    timestamp.as_deref().and_then(|value| {
        OffsetDateTime::parse(value, &Rfc3339)
            .ok()
            .map(|parsed| parsed.unix_timestamp_nanos())
    })
}
