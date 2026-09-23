//! Git-derived `created`/`updated` timestamps for Concept files — a
//! read-time lookup, never stored in or read from frontmatter.
//!
//! The timestamps come from the Concept file's git history: `created` is
//! the first commit's committer date, `updated` the most recent one's,
//! both rendered as strict RFC 3339 strings
//! (`git log --follow --format=%cI`). `--follow` tracks the file across
//! renames so a slug rename doesn't regress `created` to the rename commit.
//!
//! Best-effort by design: a bundle need not be version-controlled per the
//! OKF spec, so every failure mode — not inside a git repository, an
//! untracked/never-committed file, a missing `git` binary, an invalid
//! slug — degrades to `(None, None)` rather than an error. This metadata
//! must never break `concept show`.

use crate::crud::concept_path_or;
use std::path::Path;
use std::process::Command;

/// Look up `(created, updated)` RFC 3339 timestamps for a Concept file's
/// git history, newest-first via a single `git log --format=%cI` call:
/// the first line is `updated`, the last is `created` (equal when the
/// file has a single commit). See the module docs for the graceful
/// `(None, None)` failure contract.
pub fn git_created_updated(bundle: &Path, slug: &str) -> (Option<String>, Option<String>) {
    // Defense in depth: a traversal slug must never reach the subprocess.
    let Ok(path) = concept_path_or(bundle, slug) else {
        return (None, None);
    };
    let relative_path = path.strip_prefix(bundle).unwrap_or(&path);
    let output = match Command::new("git")
        .arg("-C")
        .arg(bundle)
        .arg("log")
        .arg("--follow")
        .arg("--format=%cI")
        .arg("--")
        .arg(relative_path)
        .output()
    {
        Ok(output) => output,
        // `git` not on PATH — best-effort metadata, not an error.
        Err(_) => return (None, None),
    };
    if !output.status.success() {
        // Outside a git repository (exit 128) or another git failure — a
        // bundle need not be version-controlled; no timestamps.
        return (None, None);
    }
    let stdout = String::from_utf8_lossy(&output.stdout);
    let mut lines = stdout.lines();
    let updated = lines.next();
    let created = stdout.lines().last();
    (created.map(str::to_string), updated.map(str::to_string))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::test_support::tempdir;
    use std::path::Path;
    use std::process::Command;

    fn git(dir: &Path, args: &[&str]) {
        let status = Command::new("git").arg("-C").arg(dir).args(args).status();
        assert!(status.is_ok_and(|s| s.success()), "git {args:?} failed");
    }

    /// Write `content` to `file` and commit it with a controlled committer
    /// date, so the expected timestamp is an independent literal rather
    /// than a recomputation of the code under test.
    fn commit(dir: &Path, file: &str, content: &str, date: &str) {
        std::fs::write(dir.join(file), content).unwrap();
        git(dir, &["add", file]);
        let status = Command::new("git")
            .arg("-C")
            .arg(dir)
            .env("GIT_COMMITTER_DATE", date)
            .env("GIT_AUTHOR_DATE", date)
            .args(["commit", "-qm", "c"])
            .status();
        assert!(status.is_ok_and(|s| s.success()), "commit failed");
    }

    fn init_repo(dir: &Path) {
        git(dir, &["init", "-q"]);
        git(dir, &["config", "user.email", "test@example.com"]);
        git(dir, &["config", "user.name", "test"]);
    }

    #[test]
    fn committed_twice_created_is_first_updated_is_most_recent() {
        let dir = tempdir("okf-core-timestamps-history");
        init_repo(&dir);
        commit(&dir, "doc.md", "v1", "2020-01-01T00:00:00Z");
        commit(&dir, "doc.md", "v2", "2021-06-15T12:30:45+02:00");

        let (created, updated) = git_created_updated(&dir, "doc");
        assert_eq!(created.as_deref(), Some("2020-01-01T00:00:00Z"));
        assert_eq!(updated.as_deref(), Some("2021-06-15T12:30:45+02:00"));
    }

    #[test]
    fn single_commit_created_equals_updated() {
        let dir = tempdir("okf-core-timestamps-single");
        init_repo(&dir);
        commit(&dir, "doc.md", "v1", "2020-01-01T00:00:00Z");

        let (created, updated) = git_created_updated(&dir, "doc");
        assert_eq!(created, updated);
        assert_eq!(created.as_deref(), Some("2020-01-01T00:00:00Z"));
    }

    #[test]
    fn bundle_outside_git_repo_is_none_none() {
        let dir = tempdir("okf-core-timestamps-norepo");
        std::fs::write(dir.join("doc.md"), "---\ntype: decision\n---\n").unwrap();
        // No `git init` — the bundle is a plain directory.

        assert_eq!(git_created_updated(&dir, "doc"), (None, None));
    }

    #[test]
    fn untracked_file_in_repo_is_none_none() {
        let dir = tempdir("okf-core-timestamps-untracked");
        init_repo(&dir);
        // Written but never `git add`ed/committed.
        std::fs::write(dir.join("doc.md"), "---\ntype: decision\n---\n").unwrap();

        assert_eq!(git_created_updated(&dir, "doc"), (None, None));
    }

    #[test]
    fn rename_preserves_original_created_date() {
        // Regression test for --follow: renaming the tracked file must not
        // regress `created` to the rename commit's date.
        let dir = tempdir("okf-core-timestamps-rename");
        init_repo(&dir);
        commit(&dir, "old.md", "v1", "2020-01-01T00:00:00Z");

        git(&dir, &["mv", "old.md", "new.md"]);
        let status = Command::new("git")
            .arg("-C")
            .arg(&dir)
            .env("GIT_COMMITTER_DATE", "2021-06-15T12:30:45+02:00")
            .env("GIT_AUTHOR_DATE", "2021-06-15T12:30:45+02:00")
            .args(["commit", "-qm", "rename"])
            .status();
        assert!(status.is_ok_and(|s| s.success()), "rename commit failed");

        let (created, updated) = git_created_updated(&dir, "new");
        assert_eq!(
            created.as_deref(),
            Some("2020-01-01T00:00:00Z"),
            "created must reflect the file's true first appearance, not the rename"
        );
        assert_eq!(updated.as_deref(), Some("2021-06-15T12:30:45+02:00"));
    }

    #[test]
    fn traversal_slug_is_none_none_and_never_reaches_git() {
        let dir = tempdir("okf-core-timestamps-traversal");
        init_repo(&dir);
        commit(&dir, "doc.md", "v1", "2020-01-01T00:00:00Z");

        // `../` slug: must not spawn git with an escaped path.
        assert_eq!(git_created_updated(&dir, "../doc"), (None, None));
    }

    #[test]
    fn relative_bundle_uses_concept_path_relative_to_git_directory() {
        let bundle = std::path::PathBuf::from(format!(
            "target/okf-core-timestamps-relative-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        std::fs::create_dir_all(&bundle).unwrap();
        init_repo(&bundle);
        commit(&bundle, "doc.md", "v1", "2020-01-01T00:00:00Z");

        assert_eq!(
            git_created_updated(&bundle, "doc"),
            (
                Some("2020-01-01T00:00:00Z".to_string()),
                Some("2020-01-01T00:00:00Z".to_string())
            )
        );

        std::fs::remove_dir_all(bundle).unwrap();
    }
}
