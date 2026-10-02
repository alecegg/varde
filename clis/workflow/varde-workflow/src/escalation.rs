//! Deferred-finding bookkeeping. Preparation is pure so recovery can verify its scope.

use crate::journal::{ExpectedSource, PendingWrite};
use anyhow::{Context, Result, bail};
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::path::{Path, PathBuf};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Snapshot {
    pub plan_dir: PathBuf,
    pub deferred_dir: PathBuf,
    pub date: String,
    pub files: BTreeMap<PathBuf, Option<String>>,
    pub inventories: BTreeMap<PathBuf, Vec<String>>,
}

#[derive(Debug, Serialize)]
pub struct FindingResult {
    pub action: &'static str,
    pub source: String,
    pub source_finding: String,
    pub deferred_id: String,
}

pub struct Prepared {
    pub findings: Vec<FindingResult>,
    pub writes: Vec<PendingWrite>,
}

fn category(name: &str) -> bool {
    let Some(stem) = name.strip_suffix(".md") else {
        return false;
    };
    let mut chars = stem.chars();
    chars.next().is_some_and(|c| c.is_ascii_uppercase())
        && chars.all(|c| c.is_ascii_uppercase() || c.is_ascii_digit() || c == '_')
}

pub fn is_category(name: &str) -> bool {
    category(name)
}

fn inventory(folder: &Path, plan: bool) -> Result<Vec<String>> {
    if !folder.exists() {
        return Ok(Vec::new());
    }
    let mut names = Vec::new();
    for entry in fs::read_dir(folder)? {
        let entry = entry?;
        let name = entry
            .file_name()
            .into_string()
            .map_err(|_| anyhow::anyhow!("non-UTF-8 review path"))?;
        let relevant = if plan {
            entry.path().join("review.md").is_file()
        } else {
            category(&name) && entry.path().is_file()
        };
        if relevant {
            if entry.file_type()?.is_symlink() {
                bail!(
                    "review inputs cannot be symlinks: {}",
                    entry.path().display()
                );
            }
            names.push(name);
        }
    }
    names.sort();
    Ok(names)
}

pub fn validate_dirs(working: &Path, plan: &Path, deferred: &Path) -> Result<()> {
    if !plan.is_absolute() || !deferred.is_absolute() {
        bail!("--plan-dir and --deferred-dir must be absolute");
    }
    if !plan.join("plan.md").is_file() {
        bail!("{} has no plan.md", plan.display());
    }
    let plans = varde_workflow_core::memory::canonical_or_lexical(&working.join("plans"));
    let plan = varde_workflow_core::memory::canonical_or_lexical(plan);
    let deferred = varde_workflow_core::memory::canonical_or_lexical(deferred);
    let working = varde_workflow_core::memory::canonical_or_lexical(working);
    if !plan.starts_with(&plans) || plan == plans {
        bail!("--plan-dir must be under the configured working/plans directory");
    }
    if !deferred.starts_with(&working) || deferred == working {
        bail!("--deferred-dir must be under configured working memory");
    }
    if plan.starts_with(&deferred) || deferred.starts_with(&plan) {
        bail!("source and deferred directories overlap");
    }
    if deferred.exists() && !deferred.is_dir() {
        bail!("{} is not a directory", deferred.display());
    }
    Ok(())
}

fn capture_file(
    snapshot: &mut Snapshot,
    sources: &mut Vec<ExpectedSource>,
    path: PathBuf,
) -> Result<()> {
    let bytes = match fs::read(&path) {
        Ok(bytes) => Some(bytes),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => None,
        Err(error) => return Err(error.into()),
    };
    let source = match &bytes {
        Some(bytes) => crate::journal::expected_source_from_bytes(&path, bytes)?,
        None => crate::journal::expected_source_at(&path)?,
    };
    if source
        .identity
        .as_ref()
        .is_some_and(|id| id.entry_type != "file")
    {
        bail!("review input is not a regular file: {}", path.display());
    }
    let text = bytes.map(String::from_utf8).transpose()?;
    snapshot.files.insert(path, text);
    sources.push(source);
    Ok(())
}

pub fn capture(plan: &Path, deferred: &Path) -> Result<(Snapshot, Vec<ExpectedSource>)> {
    let mut snapshot = Snapshot {
        plan_dir: plan.to_path_buf(),
        deferred_dir: deferred.to_path_buf(),
        date: today()?,
        files: BTreeMap::new(),
        inventories: BTreeMap::new(),
    };
    let mut sources = Vec::new();
    capture_file(&mut snapshot, &mut sources, plan.join("plan.md"))?;
    let reviews = inventory(plan, true)?;
    snapshot
        .inventories
        .insert(plan.to_path_buf(), reviews.clone());
    for review in reviews {
        let folder = plan.join(review);
        capture_file(&mut snapshot, &mut sources, folder.join("review.md"))?;
        let categories = inventory(&folder, false)?;
        snapshot
            .inventories
            .insert(folder.clone(), categories.clone());
        for name in categories {
            capture_file(&mut snapshot, &mut sources, folder.join(name))?;
        }
    }
    let categories = inventory(deferred, false)?;
    snapshot
        .inventories
        .insert(deferred.to_path_buf(), categories.clone());
    for name in categories {
        capture_file(&mut snapshot, &mut sources, deferred.join(name))?;
    }
    capture_file(&mut snapshot, &mut sources, deferred.join("review.md"))?;
    let prepared = prepare(&snapshot)?;
    // New destination categories need explicit absence preconditions too.
    for write in prepared.writes {
        if !snapshot.files.contains_key(&write.target) {
            capture_file(&mut snapshot, &mut sources, write.target)?;
        }
    }
    Ok((snapshot, sources))
}

pub fn validate_inventory(snapshot: &Snapshot, targets: &[PathBuf]) -> Result<()> {
    for (folder, recorded) in &snapshot.inventories {
        let mut current = inventory(folder, folder == &snapshot.plan_dir)?;
        let mut expected = recorded.clone();
        for target in targets {
            if target.parent() == Some(folder)
                && category(target.file_name().unwrap().to_str().unwrap())
            {
                let name = target.file_name().unwrap().to_str().unwrap().to_owned();
                if !expected.contains(&name) && target.exists() {
                    expected.push(name);
                }
            }
        }
        current.sort();
        expected.sort();
        if current != expected {
            bail!(
                "review inventory changed during escalation: {}",
                folder.display()
            );
        }
    }
    Ok(())
}

#[derive(Clone)]
struct Finding {
    path: PathBuf,
    start: usize,
    lines: Vec<String>,
    category: String,
    number: u64,
    id: String,
    title: String,
    fields: BTreeMap<String, (usize, String)>,
}

impl Finding {
    fn parse(path: &Path, start: usize, lines: Vec<String>) -> Result<Self> {
        let heading = lines[0]
            .strip_prefix("## [")
            .context("bad finding heading")?;
        let (id, title) = heading.split_once("] ").context("bad finding heading")?;
        let (cat, number) = id.rsplit_once('-').context("bad finding ID")?;
        if !category(&format!("{cat}.md"))
            || number.len() < 3
            || !number.chars().all(|c| c.is_ascii_digit())
            || title.trim().is_empty()
            || title.starts_with(char::is_whitespace)
        {
            bail!("{}:{}: bad finding heading", path.display(), start + 1);
        }
        if path.file_name().and_then(|n| n.to_str()) != Some(&format!("{cat}.md")) {
            bail!("{}:{}: {id} is not in {cat}.md", path.display(), start + 1);
        }
        let mut fields = BTreeMap::new();
        for (index, line) in lines.iter().enumerate().skip(1) {
            if line.starts_with("### ") {
                break;
            }
            if let Some((name, value)) = line.strip_prefix("**").and_then(|s| s.split_once(":**")) {
                if !name.chars().next().is_some_and(|c| c.is_ascii_alphabetic())
                    || !name.chars().all(|c| c.is_ascii_alphabetic() || c == ' ')
                {
                    continue;
                }
                if fields
                    .insert(name.to_string(), (index, value.trim().to_string()))
                    .is_some()
                {
                    bail!(
                        "{}:{}: duplicate {name} field",
                        path.display(),
                        start + index + 1
                    );
                }
            }
        }
        Ok(Self {
            path: path.to_path_buf(),
            start,
            category: cat.to_string(),
            number: number.parse()?,
            id: id.to_string(),
            title: title.to_string(),
            fields,
            lines,
        })
    }
    fn value(&self, name: &str) -> Option<&str> {
        self.fields.get(name).map(|(_, v)| v.as_str())
    }
    fn validate(&self, full: bool) -> Result<()> {
        let disposition = self.value("Disposition").unwrap_or("");
        let word = disposition.split(' ').next().unwrap_or("");
        if !["blank", "fix", "dismiss", "action-item", "escalated"].contains(&word)
            || (word == "blank" && disposition != "blank")
        {
            bail!(
                "{}: {} Disposition {disposition:?} is invalid",
                self.path.display(),
                self.id
            );
        }
        if !full {
            return Ok(());
        }
        for (name, allowed) in [
            (
                "Severity",
                &["critical", "high", "medium", "low", "info"][..],
            ),
            ("Label", &["auto-fix", "triage"][..]),
        ] {
            if !self.value(name).is_some_and(|v| allowed.contains(&v)) {
                bail!(
                    "{}: {} {name} {:?} is invalid",
                    self.path.display(),
                    self.id,
                    self.value(name)
                );
            }
        }
        if self.value("Location").is_none_or(str::is_empty) {
            bail!("{} has no Location", self.id);
        }
        let note = self.value("Escalated").unwrap_or("");
        let valid = ["spec-conflict", "scope-creep", "human-only"]
            .iter()
            .any(|prefix| {
                let Some(rest) = note.strip_prefix(prefix) else {
                    return false;
                };
                if !rest.starts_with(' ') {
                    return false;
                }
                let rest = rest.trim_start_matches(' ');
                let Some(rest) = rest.strip_prefix(['—', '–', '-']) else {
                    return false;
                };
                rest.starts_with(' ')
                    && !rest.trim_start_matches(' ').is_empty()
                    && !rest
                        .trim_start_matches(' ')
                        .starts_with(char::is_whitespace)
            });
        if !valid {
            bail!("{} Escalated note {note:?} is invalid", self.id);
        }
        for heading in ["### Summary", "### Solutions"] {
            if !self.lines.iter().any(|line| line.trim_end() == heading) {
                bail!("{} lacks {heading}", self.id);
            }
        }
        Ok(())
    }
    fn copy(&self, number: u64, source: &str) -> Vec<String> {
        let mut lines = self.lines.clone();
        while lines.last().is_some_and(|line| line.trim().is_empty()) {
            lines.pop();
        }
        lines[0] = format!("## [{}-{number:03}] {}", self.category, self.title);
        let last = self.fields.values().map(|(i, _)| *i).max().unwrap();
        lines.splice(
            last + 1..last + 1,
            [
                format!("**Source:** {source}"),
                format!("**Source finding:** {}", self.id),
            ],
        );
        lines
    }
}

fn blocks(path: &Path, text: &str) -> Result<Vec<Finding>> {
    let lines = text.lines().map(str::to_owned).collect::<Vec<_>>();
    let mut starts = Vec::new();
    let mut fence: Option<&str> = None;
    for (index, line) in lines.iter().enumerate() {
        let stripped = line.trim_start();
        if let Some(mark) = fence {
            if stripped.starts_with(mark) {
                fence = None;
            }
        } else if stripped.starts_with("```") {
            fence = Some("```");
        } else if stripped.starts_with("~~~") {
            fence = Some("~~~");
        } else if line.starts_with("## ") {
            starts.push(index);
        }
    }
    if fence.is_some() {
        bail!("{}: unclosed code fence", path.display());
    }
    let mut findings = Vec::new();
    let mut ids = BTreeSet::new();
    for (position, start) in starts.iter().copied().enumerate() {
        let end = starts.get(position + 1).copied().unwrap_or(lines.len());
        if lines[start].starts_with("## [") {
            let finding = Finding::parse(path, start, lines[start..end].to_vec())?;
            if !ids.insert(finding.id.clone()) {
                bail!("{}: duplicate IDs {}", path.display(), finding.id);
            }
            findings.push(finding);
        } else if !findings.is_empty() {
            bail!(
                "{}:{}: unexpected level-two heading {:?}",
                path.display(),
                start + 1,
                lines[start]
            );
        }
    }
    Ok(findings)
}

fn frontmatter(path: &Path, text: &str) -> Result<(Vec<String>, Vec<String>)> {
    let lines = text.lines().map(str::to_owned).collect::<Vec<_>>();
    if lines.first().map(String::as_str) != Some("---") {
        bail!("{}: missing frontmatter", path.display());
    }
    let end = lines
        .iter()
        .enumerate()
        .skip(1)
        .find(|(_, line)| *line == "---")
        .map(|(i, _)| i)
        .with_context(|| format!("{}: missing frontmatter", path.display()))?;
    Ok((lines[1..end].to_vec(), lines[end + 1..].to_vec()))
}
fn front_value<'a>(front: &'a [String], key: &str) -> Option<&'a str> {
    front
        .iter()
        .find_map(|line| line.strip_prefix(&format!("{key}:")).map(str::trim))
}

fn update_review(path: &Path, text: &str, counts: &BTreeMap<String, usize>) -> Result<String> {
    let (mut front, mut body) = frontmatter(path, text)?;
    if front_value(&front, "type") != Some("review") {
        bail!("{}: frontmatter type is not review", path.display());
    }
    let index = front
        .iter()
        .position(|line| line.starts_with("categories:"))
        .context("frontmatter has no categories")?;
    let inline = front[index].split_once(':').unwrap().1.trim();
    if !inline.is_empty() {
        let value = inline
            .strip_prefix('[')
            .and_then(|s| s.strip_suffix(']'))
            .context("unreadable categories value")?;
        let mut existing = value
            .split(',')
            .map(str::trim)
            .filter(|s| !s.is_empty())
            .map(str::to_owned)
            .collect::<Vec<_>>();
        for cat in counts.keys() {
            if !existing.contains(cat) {
                existing.push(cat.clone());
            }
        }
        front[index] = format!("categories: [{}]", existing.join(", "));
    } else {
        let mut end = index + 1;
        while end < front.len()
            && front[end].starts_with(char::is_whitespace)
            && front[end].trim_start().starts_with("- ")
        {
            end += 1;
        }
        let existing = front[index + 1..end]
            .iter()
            .map(|line| line.split_once('-').unwrap().1.trim())
            .collect::<BTreeSet<_>>();
        let added = counts
            .keys()
            .filter(|cat| !existing.contains(cat.as_str()))
            .map(|cat| format!("  - {cat}"))
            .collect::<Vec<_>>();
        front.splice(end..end, added);
    }
    for line in &mut front {
        if line.trim() == "triage_status: complete" {
            *line = "triage_status: partial".into();
        }
    }
    let section = body
        .iter()
        .position(|line| line == "## Categories")
        .context("no ## Categories section")?;
    let first = body
        .iter()
        .enumerate()
        .skip(section + 1)
        .find(|(_, l)| l.starts_with('|'))
        .map(|(i, _)| i)
        .context("## Categories has no table")?;
    let mut end = first;
    while end < body.len() && body[end].starts_with('|') {
        end += 1;
    }
    if end - first < 2 {
        bail!("## Categories has no table");
    }
    let mut seen = BTreeSet::new();
    for line in &mut body[first + 2..end] {
        let cells = line
            .trim()
            .trim_matches('|')
            .split('|')
            .map(str::trim)
            .collect::<Vec<_>>();
        if cells.len() != 3 {
            bail!("bad Categories row");
        }
        if let Some(count) = counts.get(cells[0]) {
            seen.insert(cells[0].to_owned());
            *line = format!("| {} | {} | {count} |", cells[0], cells[1]);
        }
    }
    body.splice(
        end..end,
        counts
            .iter()
            .filter(|(cat, _)| !seen.contains(*cat))
            .map(|(cat, count)| format!("| {cat} | complete | {count} |")),
    );
    Ok(format!(
        "---\n{}\n---\n{}\n",
        front.join("\n"),
        body.join("\n")
    ))
}

pub fn prepare(snapshot: &Snapshot) -> Result<Prepared> {
    let pid = snapshot
        .plan_dir
        .components()
        .rev()
        .take_while(|c| c.as_os_str() != "plans")
        .collect::<Vec<_>>()
        .into_iter()
        .rev()
        .map(|c| c.as_os_str().to_string_lossy().into_owned())
        .collect::<Vec<_>>()
        .join("/");
    let mut candidates = Vec::new();
    let mut deferred = BTreeMap::<String, (Vec<Finding>, Vec<Vec<String>>)>::new();
    let mut copies = BTreeMap::new();
    for (path, text) in &snapshot.files {
        let Some(text) = text else { continue };
        if path.parent() == Some(snapshot.deferred_dir.as_path())
            && category(path.file_name().unwrap().to_str().unwrap())
        {
            let findings = blocks(path, text)?;
            for f in &findings {
                if let (Some(source), Some(id)) = (f.value("Source"), f.value("Source finding"))
                    && !source.is_empty()
                    && !id.is_empty()
                {
                    copies.insert((source.to_owned(), id.to_owned()), f.id.clone());
                }
            }
            deferred.insert(
                path.file_stem().unwrap().to_str().unwrap().to_owned(),
                (findings, Vec::new()),
            );
        }
    }
    let review_path = snapshot.deferred_dir.join("review.md");
    let review_text = snapshot.files.get(&review_path).and_then(Option::as_deref);
    if let Some(text) = review_text {
        frontmatter(&review_path, text)?;
    }
    for review in snapshot
        .inventories
        .get(&snapshot.plan_dir)
        .context("missing plan inventory")?
    {
        let folder = snapshot.plan_dir.join(review);
        let text = snapshot
            .files
            .get(&folder.join("review.md"))
            .and_then(Option::as_deref)
            .context("missing nested review")?;
        let (front, _) = frontmatter(&folder.join("review.md"), text)?;
        let branch = front_value(&front, "branch").map(str::to_owned);
        for name in snapshot
            .inventories
            .get(&folder)
            .context("missing review inventory")?
        {
            let path = folder.join(name);
            let text = snapshot
                .files
                .get(&path)
                .and_then(Option::as_deref)
                .context("missing source category")?;
            for finding in blocks(&path, text)? {
                finding.validate(false)?;
                if finding.value("Disposition") == Some("blank")
                    && finding.fields.contains_key("Escalated")
                {
                    finding.validate(true)?;
                    candidates.push((finding, format!("{pid}/{review}"), branch.clone()));
                }
            }
        }
    }
    let mut results = Vec::new();
    let mut source_marks = BTreeMap::<PathBuf, Vec<Finding>>::new();
    for (finding, source, _) in &candidates {
        let key = (source.clone(), finding.id.clone());
        let (action, id) = if let Some(id) = copies.get(&key) {
            ("skipped", id.clone())
        } else {
            let (existing, added) = deferred.entry(finding.category.clone()).or_default();
            let number = existing
                .iter()
                .map(|f| f.number)
                .max()
                .unwrap_or(0)
                .checked_add(added.len() as u64 + 1)
                .context("finding ID overflow")?;
            added.push(finding.copy(number, source));
            let id = format!("{}-{number:03}", finding.category);
            copies.insert(key, id.clone());
            ("escalated", id)
        };
        results.push(FindingResult {
            action,
            source: source.clone(),
            source_finding: finding.id.clone(),
            deferred_id: id,
        });
        source_marks
            .entry(finding.path.clone())
            .or_default()
            .push(finding.clone());
    }
    let mut writes = Vec::new();
    let mut counts = BTreeMap::new();
    for (cat, (existing, added)) in deferred {
        if added.is_empty() {
            continue;
        }
        let target = snapshot.deferred_dir.join(format!("{cat}.md"));
        let mut text = snapshot
            .files
            .get(&target)
            .and_then(Option::as_deref)
            .map(|s| s.trim_end_matches('\n').to_owned())
            .unwrap_or_else(|| format!("# {cat}"));
        for block in &added {
            text.push_str(&format!("\n\n{}", block.join("\n")));
        }
        text.push('\n');
        writes.push(PendingWrite {
            target,
            content: text.into_bytes(),
        });
        counts.insert(cat, existing.len() + added.len());
    }
    if !counts.is_empty() {
        let text = if let Some(text) = review_text {
            update_review(&review_path, text, &counts)?
        } else {
            let branch = candidates
                .iter()
                .find_map(|(_, _, b)| b.as_deref())
                .unwrap_or("unknown");
            format!(
                "---\ntitle: Deferred review findings\ntype: review\ndate: {}\nbranch: {branch}\ntarget: standing deferred findings\nstatus: complete\ncategories:\n{}\ntriage_status: pending\n---\n\n# Deferred review findings\n\n## Categories\n\n| Category | Status | Findings |\n|---|---|---:|\n{}\n",
                snapshot.date,
                counts
                    .keys()
                    .map(|cat| format!("  - {cat}"))
                    .collect::<Vec<_>>()
                    .join("\n"),
                counts
                    .iter()
                    .map(|(cat, count)| format!("| {cat} | complete | {count} |"))
                    .collect::<Vec<_>>()
                    .join("\n")
            )
        };
        writes.push(PendingWrite {
            target: review_path,
            content: text.into_bytes(),
        });
    }
    // Copies precede source updates, including when resuming a legacy partial copy.
    for (target, findings) in source_marks {
        let mut lines = snapshot.files[&target]
            .as_ref()
            .unwrap()
            .lines()
            .map(str::to_owned)
            .collect::<Vec<_>>();
        for finding in findings {
            let index = finding.start + finding.fields["Disposition"].0;
            if lines[index].trim() != "**Disposition:** blank" {
                bail!("{} changed during the run", finding.id);
            }
            lines[index] = "**Disposition:** escalated".into();
        }
        writes.push(PendingWrite {
            target,
            content: format!("{}\n", lines.join("\n")).into_bytes(),
        });
    }
    Ok(Prepared {
        findings: results,
        writes,
    })
}

fn today() -> Result<String> {
    let output = std::process::Command::new("date")
        .arg("+%Y-%m-%d")
        .output()
        .context("date is required to preserve local review dates")?;
    let date = String::from_utf8(output.stdout)?.trim().to_owned();
    let valid = date.len() == 10
        && date.bytes().enumerate().all(|(i, byte)| {
            if i == 4 || i == 7 {
                byte == b'-'
            } else {
                byte.is_ascii_digit()
            }
        });
    if !output.status.success() || !valid {
        bail!("date did not return a valid local calendar date");
    }
    Ok(date)
}
