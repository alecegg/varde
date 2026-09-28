//! Reusable, verified source inventory for specification refresh. This cache is
//! advisory; conclusion validates specs independently from current source.

use crate::cli::SpecInventoryArgs;
use crate::output::print_success;
use anyhow::{Context, Result, bail};
use serde::{Deserialize, Serialize};
use serde_json::json;
use sha1::{Digest, Sha1};
use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::path::{Component, Path, PathBuf};
use std::process::Command;
use std::time::{SystemTime, UNIX_EPOCH};

const CACHE_VERSION: u32 = 4;
const FULL_AFTER_REUSES: u32 = 10;
const FULL_AFTER_SECONDS: u64 = 24 * 60 * 60;

#[derive(Clone, Serialize, Deserialize)]
struct Domain {
    domain: String,
    status: String,
    reason: String,
    source_roots: Vec<String>,
    sources: Vec<String>,
}

#[derive(Serialize, Deserialize)]
struct Cache {
    version: u32,
    repository: PathBuf,
    knowledge: PathBuf,
    head: String,
    ignore_hash: String,
    paths: BTreeMap<String, String>,
    untracked: BTreeSet<String>,
    spec_hashes: BTreeMap<String, String>,
    domains: Vec<Domain>,
    pending_architecture_paths: BTreeSet<String>,
    acknowledged_architecture_paths: BTreeMap<String, String>,
    validated_at: u64,
    reuses: u32,
}

#[derive(Serialize, Deserialize)]
struct CacheFile {
    cache: Cache,
    seal: String,
}

pub fn run(args: SpecInventoryArgs) -> Result<()> {
    let repository = args
        .repository
        .canonicalize()
        .context("repository does not exist")?;
    let knowledge = args
        .knowledge
        .canonicalize()
        .context("knowledge does not exist")?;
    let working = args
        .working
        .canonicalize()
        .context("working vault does not exist")?;
    let cache_dir = working.join("spec-inventory");
    fs::create_dir_all(&cache_dir)?;
    let key = blob_hash(format!("{}\0{}", repository.display(), knowledge.display()).as_bytes());
    let cache_path = cache_dir.join(format!("{key}.json"));
    let previous = fs::read(&cache_path)
        .ok()
        .and_then(|bytes| serde_json::from_slice::<CacheFile>(&bytes).ok())
        .filter(|file| {
            serde_json::to_vec(&file.cache)
                .ok()
                .is_some_and(|bytes| blob_hash(&bytes) == file.seal)
        })
        .map(|file| file.cache)
        .filter(|cache| {
            cache.version == CACHE_VERSION
                && cache.repository == repository
                && cache.knowledge == knowledge
        });
    let head = git_text(&repository, &["rev-parse", "HEAD"])?;
    let ignore_hash = ignore_fingerprint(&repository)?;
    let current_paths = git_paths(
        &repository,
        &[
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "-z",
        ],
    )?
    .into_iter()
    .filter(|path| repository.join(path).is_file())
    .collect::<BTreeSet<_>>();
    let untracked = git_paths(
        &repository,
        &["ls-files", "--others", "--exclude-standard", "-z"],
    )?;
    let spec_hashes = spec_hashes(&knowledge)?;
    let previous_paths = previous.as_ref().map(|cache| cache.paths.clone());
    let mut pending_architecture_paths = previous
        .as_ref()
        .map(|cache| cache.pending_architecture_paths.clone())
        .unwrap_or_default();
    let mut acknowledged_architecture_paths = previous
        .as_ref()
        .map(|cache| cache.acknowledged_architecture_paths.clone())
        .unwrap_or_default();
    if previous.as_ref().is_some_and(|cache| {
        cache.spec_hashes.get("specs/architecture.md") != spec_hashes.get("specs/architecture.md")
    }) {
        pending_architecture_paths.clear();
        acknowledged_architecture_paths.clear();
    }
    let pending_path_removed = pending_architecture_paths
        .iter()
        .any(|path| !current_paths.contains(path));
    pending_architecture_paths.retain(|path| current_paths.contains(path));
    if let Some(cache) = previous.as_ref() {
        pending_architecture_paths.extend(
            current_paths
                .iter()
                .filter(|path| !cache.paths.contains_key(*path))
                .cloned(),
        );
    } else {
        pending_architecture_paths.extend(untracked.iter().cloned());
    }
    pending_architecture_paths.extend(
        architecture_additions_since_index(&repository, &knowledge, &current_paths)?.into_iter(),
    );
    let now = SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs();
    let unreliable_index = git_bytes(&repository, &["ls-files", "-v", "-z"])?
        .split(|byte| *byte == 0)
        .filter(|entry| !entry.is_empty())
        .any(|entry| entry[0].is_ascii_lowercase() || entry[0] == b'S');
    let due = previous.as_ref().is_some_and(|cache| {
        cache.reuses >= FULL_AFTER_REUSES
            || now.saturating_sub(cache.validated_at) >= FULL_AFTER_SECONDS
    });
    let mut full = args.refresh
        || previous.is_none()
        || due
        || unreliable_index
        || pending_path_removed
        || previous.as_ref().is_some_and(|cache| {
            cache.ignore_hash != ignore_hash
                || cache.spec_hashes.get("specs/index.md") != spec_hashes.get("specs/index.md")
        });
    let mut cache = if full {
        full_inventory(
            &repository,
            &knowledge,
            head,
            &current_paths,
            untracked,
            spec_hashes,
            ignore_hash,
            now,
        )?
    } else {
        match incremental_inventory(
            previous.expect("checked above"),
            &repository,
            &knowledge,
            head.clone(),
            &current_paths,
            untracked.clone(),
            spec_hashes.clone(),
            ignore_hash.clone(),
            now,
        ) {
            Ok(cache) => cache,
            Err(_) => {
                full = true;
                full_inventory(
                    &repository,
                    &knowledge,
                    head,
                    &current_paths,
                    untracked,
                    spec_hashes,
                    ignore_hash,
                    now,
                )?
            }
        }
    };
    cache.pending_architecture_paths = pending_architecture_paths;
    cache.acknowledged_architecture_paths = acknowledged_architecture_paths;
    for path in &args.acknowledge_architecture_paths {
        let value = path.to_string_lossy().replace('\\', "/");
        if !safe_relative(&value) || !cache.paths.contains_key(&value) {
            bail!("acknowledged architecture path must be an existing repository file: {value}");
        }
        if is_definite_declaration(&value) {
            bail!("architecture declaration cannot be acknowledged away: {value}");
        }
        cache
            .acknowledged_architecture_paths
            .insert(value.clone(), cache.paths[&value].clone());
    }
    let mut architecture_inspect_paths = Vec::new();
    if let Some(architecture) = cache
        .domains
        .iter_mut()
        .find(|domain| domain.domain == "architecture")
    {
        if architecture.status == "inspect"
            && architecture.reason == "new path needs architecture classification"
        {
            architecture.status = "reuse".into();
            architecture.reason = "verified provenance".into();
        }
        architecture_inspect_paths = cache
            .pending_architecture_paths
            .iter()
            .chain(cache.acknowledged_architecture_paths.keys())
            .filter(|path| {
                cache.paths.contains_key(*path)
                    && !is_definite_declaration(path)
                    && !architecture
                        .source_roots
                        .iter()
                        .any(|root| contains(root, path))
                    && cache.acknowledged_architecture_paths.get(*path) != cache.paths.get(*path)
            })
            .cloned()
            .collect::<BTreeSet<_>>()
            .into_iter()
            .collect();
        if architecture.status == "reuse" && !architecture_inspect_paths.is_empty() {
            architecture.status = "inspect".into();
            architecture.reason = "new path needs architecture classification".into();
        }
    }
    let cache_hit = !full;
    let (overlapping, unmatched) = classify_paths(&cache.paths, &cache.domains);
    let unclassified_paths = unclassified_paths(
        &cache.paths,
        &cache.domains,
        if full { None } else { previous_paths.as_ref() },
    );
    let architecture = cache
        .domains
        .iter()
        .find(|domain| domain.domain == "architecture");
    let architecture_status = architecture
        .map(|domain| domain.status.as_str())
        .unwrap_or_else(|| {
            if cache.paths.keys().any(|path| is_definite_declaration(path)) {
                "missing"
            } else {
                "none"
            }
        });
    let architecture_candidates: Vec<_> = if architecture.is_none() {
        cache
            .paths
            .keys()
            .filter(|path| is_declaration(path) && !is_definite_declaration(path))
            .cloned()
            .collect()
    } else {
        Vec::new()
    };
    let data = json!({
        "cache_hit": cache_hit,
        "full_validation_due": due,
        "full_validation": full,
        "domains": cache.domains,
        "architecture": architecture,
        "architecture_status": architecture_status,
        "architecture_candidates": architecture_candidates,
        "architecture_inspect_paths": architecture_inspect_paths,
        "overlapping": overlapping,
        "unmatched": unmatched,
        "unclassified_paths": unclassified_paths,
        "missing": missing_domains(&cache.paths, &cache.domains),
    });
    write_cache(&cache_path, &cache)?;
    if args.json {
        print_success(data)
    } else {
        println!("{}", serde_json::to_string_pretty(&data)?);
        Ok(())
    }
}

fn full_inventory(
    repository: &Path,
    knowledge: &Path,
    head: String,
    paths: &BTreeSet<String>,
    untracked: BTreeSet<String>,
    spec_hashes: BTreeMap<String, String>,
    ignore_hash: String,
    now: u64,
) -> Result<Cache> {
    let mut hashes = BTreeMap::new();
    for path in paths {
        hashes.insert(path.clone(), hash_file(repository, path)?);
    }
    let domains = verify_domains(repository, knowledge, &hashes, None, &BTreeSet::new())?;
    Ok(Cache {
        version: CACHE_VERSION,
        repository: repository.to_path_buf(),
        knowledge: knowledge.to_path_buf(),
        head,
        ignore_hash,
        paths: hashes,
        untracked,
        spec_hashes,
        domains,
        pending_architecture_paths: BTreeSet::new(),
        acknowledged_architecture_paths: BTreeMap::new(),
        validated_at: now,
        reuses: 0,
    })
}

#[allow(clippy::too_many_arguments)]
fn incremental_inventory(
    mut cache: Cache,
    repository: &Path,
    knowledge: &Path,
    head: String,
    paths: &BTreeSet<String>,
    untracked: BTreeSet<String>,
    spec_hashes: BTreeMap<String, String>,
    ignore_hash: String,
    now: u64,
) -> Result<Cache> {
    let mut changed = BTreeSet::new();
    if cache.head != head {
        changed.extend(git_paths(
            repository,
            &["diff", "--name-only", "-z", &cache.head, &head],
        )?);
    }
    changed.extend(git_paths(
        repository,
        &["diff", "--name-only", "--cached", "-z"],
    )?);
    changed.extend(git_paths(repository, &["diff", "--name-only", "-z"])?);
    for path in cache.paths.keys() {
        if !paths.contains(path) {
            changed.insert(path.clone());
        }
    }
    for path in paths {
        if !cache.paths.contains_key(path) || untracked.contains(path) {
            changed.insert(path.clone());
        }
    }
    if changed.iter().any(|path| is_ignore_rule(path)) {
        bail!("ignore policy changed; full inventory required");
    }
    let mut hashes = cache.paths.clone();
    hashes.retain(|path, _| paths.contains(path));
    for path in changed.clone() {
        if paths.contains(&path) {
            let hash = hash_file(repository, &path)?;
            if hashes.get(&path) == Some(&hash) {
                changed.remove(&path);
            }
            hashes.insert(path, hash);
        }
    }
    let mut changed_specs = BTreeSet::new();
    for (path, hash) in &spec_hashes {
        if cache.spec_hashes.get(path) != Some(hash) {
            changed_specs.insert(path.clone());
        }
    }
    for path in cache.spec_hashes.keys() {
        if !spec_hashes.contains_key(path) {
            changed_specs.insert(path.clone());
        }
    }
    let mut domains = verify_domains(
        repository,
        knowledge,
        &hashes,
        Some(&cache.domains),
        &changed.union(&changed_specs).cloned().collect(),
    )?;
    let old_names: BTreeSet<_> = cache
        .domains
        .iter()
        .filter(|domain| domain.domain != "architecture")
        .map(|domain| &domain.domain)
        .collect();
    let new_names: BTreeSet<_> = domains
        .iter()
        .filter(|domain| domain.domain != "architecture")
        .map(|domain| &domain.domain)
        .collect();
    if old_names != new_names {
        if let Some(architecture) = domains
            .iter_mut()
            .find(|domain| domain.domain == "architecture")
        {
            architecture.status = "stale".into();
            architecture.reason = "domain set changed".into();
        }
    }
    cache.head = head;
    cache.ignore_hash = ignore_hash;
    cache.paths = hashes;
    cache.untracked = untracked;
    cache.spec_hashes = spec_hashes;
    cache.domains = domains;
    cache.reuses += 1;
    if cache.reuses > FULL_AFTER_REUSES || now < cache.validated_at {
        bail!("cache validation interval is uncertain");
    }
    Ok(cache)
}

fn verify_domains(
    repository: &Path,
    knowledge: &Path,
    paths: &BTreeMap<String, String>,
    previous: Option<&[Domain]>,
    changed: &BTreeSet<String>,
) -> Result<Vec<Domain>> {
    let specs = knowledge.join("specs");
    if !specs.is_dir() {
        return Ok(Vec::new());
    }
    let mut domains = Vec::new();
    for entry in fs::read_dir(&specs)? {
        let entry = entry?;
        let path = entry.path();
        if path.extension().is_none_or(|extension| extension != "md")
            || path.file_name().is_some_and(|name| name == "index.md")
        {
            continue;
        }
        let domain = path.file_stem().unwrap().to_string_lossy().into_owned();
        let bytes = fs::read(&path)?;
        let mapping = parse_spec(&bytes);
        let roots = mapping
            .as_ref()
            .and_then(|value| strings(value, "source_roots"))
            .unwrap_or_default();
        let sources = mapping
            .as_ref()
            .and_then(|value| source_paths(value))
            .unwrap_or_default();
        let relevant = changed.contains(&format!("specs/{domain}.md"))
            || changed.contains("specs/index.md")
            || changed.iter().any(|changed_path| {
                roots.iter().any(|root| contains(root, changed_path))
                    || sources.iter().any(|source| source == changed_path)
                    || (domain == "architecture" && is_declaration(changed_path))
            });
        if !relevant {
            if let Some(saved) =
                previous.and_then(|list| list.iter().find(|saved| saved.domain == domain))
            {
                domains.push(saved.clone());
                continue;
            }
        }
        domains.push(verify_domain(repository, &domain, mapping, paths));
    }
    domains.sort_by(|left, right| left.domain.cmp(&right.domain));
    Ok(domains)
}

fn verify_domain(
    _repository: &Path,
    domain: &str,
    mapping: Option<serde_yaml::Value>,
    paths: &BTreeMap<String, String>,
) -> Domain {
    let mut result = Domain {
        domain: domain.to_string(),
        status: "stale".into(),
        reason: "malformed or incomplete specification provenance".into(),
        source_roots: Vec::new(),
        sources: Vec::new(),
    };
    let Some(mapping) = mapping else {
        return result;
    };
    let Some(roots) = strings(&mapping, "source_roots") else {
        return result;
    };
    let Some(covered) = strings(&mapping, "covered_paths") else {
        return result;
    };
    let Some(sources) = source_entries(&mapping) else {
        return result;
    };
    let Some(expected) = mapping
        .get("source_hash")
        .and_then(serde_yaml::Value::as_str)
    else {
        return result;
    };
    if roots.is_empty() || roots.iter().any(|root| !safe_relative(root)) {
        return result;
    }
    result.source_roots = roots.clone();
    result.sources = sources.iter().map(|(path, _)| path.clone()).collect();
    let actual_covered: Vec<String> = paths
        .keys()
        .filter(|path| roots.iter().any(|root| contains(root, path)))
        .cloned()
        .collect();
    if actual_covered != covered {
        result.reason = "stale covered_paths".into();
        return result;
    }
    if domain == "architecture"
        && paths.keys().any(|path| {
            is_definite_declaration(path) && !roots.iter().any(|root| contains(root, path))
        })
    {
        result.reason = "architecture declaration outside source_roots".into();
        return result;
    }
    let mut pairs = Vec::new();
    for (path, recorded) in sources {
        if !safe_relative(&path)
            || !roots.iter().any(|root| contains(root, &path))
            || paths.get(&path) != Some(&recorded)
        {
            result.reason = format!("stale source: {path}");
            return result;
        }
        pairs.push((path, recorded));
    }
    pairs.sort();
    let aggregate = pairs
        .into_iter()
        .map(|(path, hash)| format!("{path}{hash}"))
        .collect::<String>();
    if blob_hash(aggregate.as_bytes()) != expected {
        result.reason = "stale source_hash".into();
        return result;
    }
    result.status = "reuse".into();
    result.reason = "verified provenance".into();
    result
}

fn parse_spec(bytes: &[u8]) -> Option<serde_yaml::Value> {
    let text = std::str::from_utf8(bytes).ok()?;
    let body = text.strip_prefix("---\n")?;
    let (frontmatter, _) = body.split_once("\n---")?;
    serde_yaml::from_str(frontmatter).ok()
}

fn strings(value: &serde_yaml::Value, key: &str) -> Option<Vec<String>> {
    value
        .get(key)?
        .as_sequence()?
        .iter()
        .map(|item| item.as_str().map(str::to_string))
        .collect()
}

fn source_entries(value: &serde_yaml::Value) -> Option<Vec<(String, String)>> {
    value
        .get("sources")?
        .as_sequence()?
        .iter()
        .map(|item| {
            Some((
                item.get("path")?.as_str()?.to_string(),
                item.get("hash")?.as_str()?.to_string(),
            ))
        })
        .collect()
}

fn source_paths(value: &serde_yaml::Value) -> Option<Vec<String>> {
    Some(
        source_entries(value)?
            .into_iter()
            .map(|(path, _)| path)
            .collect(),
    )
}

fn contains(root: &str, path: &str) -> bool {
    path == root || path.starts_with(&format!("{root}/"))
}

fn safe_relative(path: &str) -> bool {
    !path.is_empty()
        && Path::new(path)
            .components()
            .all(|part| matches!(part, Component::Normal(_)))
}

fn classify_paths(
    paths: &BTreeMap<String, String>,
    domains: &[Domain],
) -> (Vec<String>, Vec<String>) {
    let mut overlapping = Vec::new();
    let mut unmatched = Vec::new();
    for path in paths.keys().filter(|path| is_source_candidate(path)) {
        let owners = domains
            .iter()
            .filter(|domain| {
                domain.domain != "architecture"
                    && domain.source_roots.iter().any(|root| contains(root, path))
            })
            .count();
        if owners > 1 {
            overlapping.push(path.clone());
        }
        if owners == 0 {
            unmatched.push(path.clone());
        }
    }
    (overlapping, unmatched)
}

fn unclassified_paths(
    paths: &BTreeMap<String, String>,
    domains: &[Domain],
    previous: Option<&BTreeMap<String, String>>,
) -> Vec<String> {
    paths
        .keys()
        .filter(|path| {
            previous.is_none_or(|old| old.get(*path) != paths.get(*path))
                && !domains.iter().any(|domain| {
                    domain.domain != "architecture"
                        && domain.source_roots.iter().any(|root| contains(root, path))
                })
        })
        .cloned()
        .collect()
}

fn architecture_additions_since_index(
    repository: &Path,
    knowledge: &Path,
    current_paths: &BTreeSet<String>,
) -> Result<BTreeSet<String>> {
    if !knowledge.join("specs/architecture.md").is_file() {
        return Ok(BTreeSet::new());
    }
    let index_path = knowledge.join("specs/index.md");
    if !index_path.exists() {
        return Ok(BTreeSet::new());
    }
    let index = fs::read(index_path)?;
    let Some(commit) = parse_spec(&index).and_then(|value| {
        value
            .get("source_commit")
            .and_then(serde_yaml::Value::as_str)
            .map(str::to_owned)
    }) else {
        return Ok(current_paths.clone());
    };
    let added = git_paths(
        repository,
        &[
            "diff",
            "--name-only",
            "--diff-filter=A",
            "-z",
            &commit,
            "HEAD",
        ],
    )
    .unwrap_or_else(|_| current_paths.clone());
    Ok(added.intersection(current_paths).cloned().collect())
}

fn missing_domains(paths: &BTreeMap<String, String>, domains: &[Domain]) -> Vec<String> {
    let (_, unmatched) = classify_paths(paths, domains);
    unmatched
        .into_iter()
        .filter_map(|path| candidate_domain(&path))
        .collect::<BTreeSet<_>>()
        .into_iter()
        .collect()
}

fn is_source_candidate(path: &str) -> bool {
    let name = path.rsplit('/').next().unwrap_or(path);
    let extension = name.rsplit_once('.').map(|(_, extension)| extension);
    matches!(
        extension,
        Some(
            "rs" | "py"
                | "ts"
                | "tsx"
                | "js"
                | "mjs"
                | "go"
                | "java"
                | "swift"
                | "kt"
                | "c"
                | "cc"
                | "cpp"
                | "h"
                | "sh"
        )
    ) || is_definite_declaration(path)
}

fn candidate_domain(path: &str) -> Option<String> {
    if !is_source_candidate(path) {
        return None;
    }
    let parts: Vec<_> = path.split('/').collect();
    if let Some(position) = parts.iter().position(|part| *part == "src") {
        if position == 0 && parts.len() > 2 {
            return Some(format!("src/{}", parts[1]));
        }
        return Some(parts[..position.max(1)].join("/"));
    }
    Path::new(path)
        .parent()
        .map(|parent| parent.to_string_lossy().into_owned())
        .filter(|parent| !parent.is_empty())
}

fn is_ignore_rule(path: &str) -> bool {
    path == ".gitignore" || path.ends_with("/.gitignore")
}

fn ignore_fingerprint(repository: &Path) -> Result<String> {
    let raw = git_text(repository, &["rev-parse", "--git-path", "info/exclude"])?;
    let location = PathBuf::from(raw);
    let path = if location.is_absolute() {
        location
    } else {
        repository.join(location)
    };
    let bytes = match fs::read(path) {
        Ok(bytes) => bytes,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Vec::new(),
        Err(error) => return Err(error.into()),
    };
    Ok(blob_hash(&bytes))
}

fn is_declaration(path: &str) -> bool {
    if is_definite_declaration(path) {
        return true;
    }
    let name = path.rsplit('/').next().unwrap_or(path);
    let config_extension = name.rsplit_once('.').map(|(_, extension)| extension);
    matches!(
        config_extension,
        Some("yaml" | "yml" | "toml" | "json" | "tf" | "tfvars" | "hcl" | "nix")
    )
}

fn is_definite_declaration(path: &str) -> bool {
    let name = path.rsplit('/').next().unwrap_or(path);
    let extension = name.rsplit_once('.').map(|(_, extension)| extension);
    matches!(
        name,
        "Cargo.toml"
            | "package.json"
            | "pyproject.toml"
            | "Dockerfile"
            | "docker-compose.yml"
            | "docker-compose.yaml"
            | "go.mod"
            | "Chart.yaml"
    ) || (matches!(
        extension,
        Some("yaml" | "yml" | "json" | "toml" | "tf" | "tfvars" | "hcl" | "nix")
    ) && (path.starts_with(".github/workflows/")
        || path.starts_with("deploy/")
        || path.starts_with("infra/")
        || path.starts_with("k8s/")
        || path.starts_with("helm/")
        || path.starts_with("terraform/")))
}

fn spec_hashes(knowledge: &Path) -> Result<BTreeMap<String, String>> {
    let mut hashes = BTreeMap::new();
    let dir = knowledge.join("specs");
    if dir.is_dir() {
        for entry in fs::read_dir(dir)? {
            let path = entry?.path();
            if path.extension().is_some_and(|ext| ext == "md") {
                let name = path.file_name().unwrap().to_string_lossy();
                hashes.insert(format!("specs/{name}"), blob_hash(&fs::read(&path)?));
            }
        }
    }
    Ok(hashes)
}

fn hash_file(repository: &Path, relative: &str) -> Result<String> {
    if !safe_relative(relative) {
        bail!("unsafe inventory path: {relative}");
    }
    let path = repository.join(relative);
    if !path.is_file() {
        bail!("inventory file disappeared: {}", path.display());
    }
    let actual = path.canonicalize()?;
    if !actual.starts_with(repository) {
        bail!("inventory path escapes repository: {relative}");
    }
    Ok(blob_hash(&fs::read(path)?))
}

fn blob_hash(bytes: &[u8]) -> String {
    let mut sha = Sha1::new();
    sha.update(format!("blob {}\0", bytes.len()));
    sha.update(bytes);
    format!("{:x}", sha.finalize())
}

fn git_bytes(repository: &Path, args: &[&str]) -> Result<Vec<u8>> {
    let output = Command::new("git")
        .args(args)
        .current_dir(repository)
        .output()?;
    if !output.status.success() {
        bail!(
            "git {} failed: {}",
            args.join(" "),
            String::from_utf8_lossy(&output.stderr)
        );
    }
    Ok(output.stdout)
}

fn git_text(repository: &Path, args: &[&str]) -> Result<String> {
    Ok(String::from_utf8(git_bytes(repository, args)?)?
        .trim()
        .to_string())
}

fn git_paths(repository: &Path, args: &[&str]) -> Result<BTreeSet<String>> {
    git_bytes(repository, args)?
        .split(|byte| *byte == 0)
        .filter(|bytes| !bytes.is_empty())
        .map(|bytes| {
            let path = String::from_utf8(bytes.to_vec())?;
            if !safe_relative(&path) {
                bail!("unsafe git path: {path}");
            }
            Ok(path)
        })
        .collect()
}

fn write_cache(path: &Path, cache: &Cache) -> Result<()> {
    let temp = path.with_extension(format!("{}.tmp", std::process::id()));
    let bytes = serde_json::to_vec(cache)?;
    let file = CacheFile {
        cache: serde_json::from_slice(&bytes)?,
        seal: blob_hash(&bytes),
    };
    fs::write(&temp, serde_json::to_vec(&file)?)?;
    fs::rename(temp, path)?;
    Ok(())
}
