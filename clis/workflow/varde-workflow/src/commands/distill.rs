//! Read-only draft skeleton for distilling a plan into durable knowledge.

use crate::cli::DistillArgs;
use crate::commands::error::{InternalError, report_error};
use crate::output::print_success;
use anyhow::{Context, Result, anyhow};
use serde_json::json;
use std::fs;
use std::path::{Path, PathBuf};
use varde_workflow_core::memory::MemoryPaths;

pub fn run(args: DistillArgs) -> Result<()> {
    let result = distill(&args.plan_dir);
    match result {
        Ok(draft) if args.json => print_success(draft.data),
        Ok(draft) => {
            print!("{}", draft.markdown);
            Ok(())
        }
        Err(error) => report_error(&InternalError(error.to_string()), args.json),
    }
}

#[derive(Debug)]
struct Draft {
    markdown: String,
    data: serde_json::Value,
}

fn distill(argument: &Path) -> Result<Draft> {
    let cwd = std::env::current_dir().context("could not resolve cwd")?;
    let memory = MemoryPaths::resolve(&cwd).map_err(|error| anyhow!(error.to_string()))?;
    let plan_dir = if argument.is_absolute() {
        argument.to_path_buf()
    } else {
        cwd.join(argument)
    };
    let plan_path = plan_dir.join("plan.md");
    let plan_bytes = fs::read(&plan_path).with_context(|| format!("{}", plan_path.display()))?;
    let (frontmatter, body) = varde_workflow_core::frontmatter::parse(&plan_bytes)
        .with_context(|| format!("invalid frontmatter in {}", plan_path.display()))?;
    let title = body
        .lines()
        .find_map(|line| line.strip_prefix("# "))
        .unwrap_or_else(|| {
            plan_dir
                .file_name()
                .and_then(|name| name.to_str())
                .unwrap_or("plan")
        });
    let status = frontmatter["status"].as_str().unwrap_or("unknown");
    let mut tasks = Vec::new();
    let tasks_dir = plan_dir.join("tasks");
    if tasks_dir.is_dir() {
        for entry in sorted_files(&tasks_dir)? {
            if entry.extension().and_then(|ext| ext.to_str()) != Some("md") {
                continue;
            }
            let bytes = fs::read(&entry)?;
            let (task_meta, task_body) = varde_workflow_core::frontmatter::parse(&bytes)
                .with_context(|| format!("invalid frontmatter in {}", entry.display()))?;
            let task_title = task_body
                .lines()
                .find_map(|line| line.strip_prefix("# "))
                .unwrap_or_else(|| {
                    entry
                        .file_stem()
                        .and_then(|name| name.to_str())
                        .unwrap_or("task")
                });
            tasks.push(format!(
                "- {task_title} ({})",
                task_meta["status"].as_str().unwrap_or("unknown")
            ));
        }
    }
    let review_path = plan_dir.join("review.md");
    let review = if review_path.is_file() {
        let bytes = fs::read(&review_path)?;
        let (meta, _) = varde_workflow_core::frontmatter::parse(&bytes)
            .with_context(|| format!("invalid frontmatter in {}", review_path.display()))?;
        Some((
            meta["verdict"].as_str().unwrap_or("unknown").to_owned(),
            meta["head"].as_str().unwrap_or("unknown").to_owned(),
        ))
    } else {
        None
    };
    let (files, bytes) = count_files(&plan_dir)?;
    let bundle = memory.working.path.join("distilled");
    let markdown = format!(
        "# {title}\n\nStatus: {status}\n\n## Problem\n\n{}\n\n## Solution\n\n{}\n\n## Decisions so far\n\n{}\n\n## Tasks\n\n{}\n\n## Review\n\n{}\n\n- reviewed_commit: {}\n- Plan files: {files}\n- Plan bytes: {bytes}\n- Distilled bundle: {}\n\n## Why\n\n## Lessons\n\n## Measurements\n\n",
        section(&body, "Problem"),
        section(&body, "Solution"),
        section(&body, "Decisions so far"),
        if tasks.is_empty() {
            "(none)".to_owned()
        } else {
            tasks.join("\n")
        },
        review
            .as_ref()
            .map(|(verdict, head)| format!("- Verdict: {verdict}\n- Head: {head}"))
            .unwrap_or_else(|| "- No review.md".to_owned()),
        frontmatter["reviewed_commit"].as_str().unwrap_or(""),
        bundle.display(),
    );
    let data = json!({
        "title": title, "status": status, "reviewed_commit": frontmatter["reviewed_commit"],
        "review": review.map(|(verdict, head)| json!({"verdict": verdict, "head": head})),
        "files": files, "bytes": bytes, "bundle_path": bundle, "markdown": markdown,
    });
    Ok(Draft { markdown, data })
}

fn section(body: &str, heading: &str) -> String {
    let marker = format!("## {heading}");
    let Some(start) = body.find(&marker) else {
        return "(not stated)".to_owned();
    };
    body[start + marker.len()..]
        .split("\n## ")
        .next()
        .unwrap_or("")
        .trim()
        .to_owned()
}

fn sorted_files(directory: &Path) -> Result<Vec<PathBuf>> {
    let mut paths = fs::read_dir(directory)?
        .map(|entry| entry.map(|entry| entry.path()))
        .collect::<std::io::Result<Vec<_>>>()?;
    paths.sort();
    Ok(paths)
}

fn count_files(directory: &Path) -> Result<(usize, u64)> {
    fn visit(path: &Path, files: &mut usize, bytes: &mut u64) -> Result<()> {
        for entry in fs::read_dir(path)? {
            let entry = entry?;
            let metadata = entry.metadata()?;
            if metadata.is_dir() {
                visit(&entry.path(), files, bytes)?;
            } else if metadata.is_file() {
                *files += 1;
                *bytes += metadata.len();
            }
        }
        Ok(())
    }
    let mut files = 0;
    let mut bytes = 0;
    visit(directory, &mut files, &mut bytes)?;
    Ok((files, bytes))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::time::SystemTime;

    static FIXTURES: AtomicUsize = AtomicUsize::new(0);

    fn fixture(review: bool) -> PathBuf {
        // A per-process counter keeps parallel tests off each other's directory.
        let temp = std::env::temp_dir().join(format!(
            "varde-distill-test-{}-{}",
            std::process::id(),
            FIXTURES.fetch_add(1, Ordering::Relaxed)
        ));
        let plan = temp.join("plan");
        fs::create_dir_all(plan.join("tasks")).unwrap();
        fs::write(plan.join("plan.md"), "---\ntype: plan\nstatus: completed\nreviewed_commit: abc123\n---\n# Example Plan\n\n## Problem\nNeed it.\n\n## Solution\nDo it.\n\n## Decisions so far\nDistill approach → a distilling agent drafts a concept.\n\n## Design\n### Distill step\nKeep decisions.\n\n## Acceptance criteria\n- done\n").unwrap();
        fs::write(
            plan.join("tasks/one.md"),
            "---\ntype: task\nstatus: completed\n---\n# Implement feature\n",
        )
        .unwrap();
        if review {
            fs::write(
                plan.join("review.md"),
                "---\nverdict: approved\nhead: def456\n---\n",
            )
            .unwrap();
        }
        temp
    }

    fn inventory(path: &Path) -> Vec<(PathBuf, u64, Option<SystemTime>)> {
        fn visit(root: &Path, path: &Path, out: &mut Vec<(PathBuf, u64, Option<SystemTime>)>) {
            for entry in fs::read_dir(path).unwrap() {
                let entry = entry.unwrap();
                let metadata = entry.metadata().unwrap();
                out.push((
                    entry.path().strip_prefix(root).unwrap().to_path_buf(),
                    metadata.len(),
                    metadata.modified().ok(),
                ));
                if metadata.is_dir() {
                    visit(root, &entry.path(), out);
                }
            }
        }
        let mut out = Vec::new();
        let metadata = fs::metadata(path).unwrap();
        out.push((PathBuf::new(), metadata.len(), metadata.modified().ok()));
        visit(path, path, &mut out);
        out.sort_by(|a, b| a.0.cmp(&b.0));
        out
    }

    #[test]
    fn completed_plan_has_skeleton_and_resolved_bundle_path_without_writes() {
        let temp = fixture(true);
        let plan_dir = temp.join("plan");
        let before = inventory(&plan_dir);
        let draft = distill(&plan_dir).unwrap();
        let after = inventory(&plan_dir);
        assert_eq!(before, after);
        assert!(draft.markdown.contains("# Example Plan"));
        assert!(
            draft
                .markdown
                .contains("Distill approach → a distilling agent drafts a concept")
        );
        assert!(draft.markdown.contains("Why\n\n## Lessons"));
        let bundle = draft.data["bundle_path"].as_str().unwrap();
        let resolved_working = MemoryPaths::resolve(&std::env::current_dir().unwrap())
            .unwrap()
            .working
            .path;
        assert!(bundle.ends_with("/distilled"));
        assert!(bundle.starts_with(resolved_working.to_str().unwrap()));
        fs::remove_dir_all(temp).unwrap();
    }

    #[test]
    fn fixtures_never_share_a_directory() {
        let first = fixture(false);
        let second = fixture(false);
        assert_ne!(first, second);
    }

    #[test]
    fn plan_without_review_is_included() {
        let temp = fixture(false);
        let draft = distill(&temp.join("plan")).unwrap();
        assert!(draft.markdown.contains("No review.md"));
        fs::remove_dir_all(temp).unwrap();
    }
}
