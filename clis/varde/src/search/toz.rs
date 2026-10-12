use super::unavailable;
use std::collections::{HashMap, HashSet};
use std::path::{Path, PathBuf};
use std::process::Command;
use toz_core::config::Config;
use toz_core::index::{index_file, is_stale};
use toz_core::search::{Hit, SearchOpts, ValueFilter, search};
use toz_core::store::Store;
use varde_contracts::{SearchHit, SearchQuery, SearchSource, SourceResult};

/// Most hits one toz search can return (porter and trigram candidates, fused).
const CANDIDATE_POOL: usize = 100;

#[derive(Clone, Copy, PartialEq, Eq)]
pub enum TozScope {
    /// Repository Markdown outside the working store.
    Docs,
    /// Markdown under the working store's `plans/` and `reviews/`.
    Plans,
    /// Every live capture except `index`.
    Output,
}

impl TozScope {
    fn name(self) -> &'static str {
        match self {
            TozScope::Docs => "docs",
            TozScope::Plans => "plans",
            TozScope::Output => "output",
        }
    }
}

/// Search over the repository's toz project store. `Docs` and `Plans` first
/// bring the store up to date with the files on disk; `Output` only reads.
pub struct TozSearch {
    scope: TozScope,
    cfg: Config,
    db_path: PathBuf,
    repo_root: PathBuf,
    working: PathBuf,
}

impl TozSearch {
    pub fn new(
        scope: TozScope,
        cfg: Config,
        db_path: PathBuf,
        repo_root: PathBuf,
        working: PathBuf,
    ) -> Self {
        Self {
            scope,
            cfg,
            db_path,
            repo_root,
            working,
        }
    }

    pub(super) fn plans_unindexed(&self) -> bool {
        let working = canonical(&self.working);
        if self.scope != TozScope::Plans
            || !has_plan_markdown(&working)
            || ensure_git_repository(&self.repo_root).is_err()
        {
            return false;
        }
        let Ok(store) = Store::open_readonly(&self.db_path) else {
            return true;
        };
        let Ok(rows) = store.list(usize::MAX, false) else {
            return false;
        };
        !rows.iter().any(|row| {
            row.kind == "index"
                && is_plan_source(&row.source, &working)
                && Path::new(&row.source).is_file()
        })
    }

    fn search_output(&self, query: &SearchQuery) -> SourceResult {
        if !self.db_path.is_file() {
            return unavailable(self.scope.name(), "no toz store yet");
        }
        let store = match Store::open_readonly(&self.db_path) {
            Ok(store) => store,
            Err(error) => return unavailable(self.scope.name(), format!("{error:#}")),
        };
        let opts = SearchOpts {
            limit: query.limit,
            kind: Some(ValueFilter {
                exclude: true,
                values: vec!["index".to_string()],
            }),
            ..SearchOpts::default()
        };
        self.finish(&store, query, &opts, None, |hit| SearchHit {
            source: self.scope.name().to_string(),
            title: hit.label.clone(),
            location: format!("{}#{}", hit.handle, hit.chunk),
            snippet: hit.snippet.clone(),
            score: score_of(&hit),
        })
    }

    fn search_files(&self, query: &SearchQuery) -> SourceResult {
        let name = self.scope.name();
        let repo_root = canonical(&self.repo_root);
        let working = canonical(&self.working);
        let files = match self.discover(&repo_root, &working) {
            Ok(files) => files,
            Err(reason) => return unavailable(name, reason),
        };
        let docs_sources: Option<HashSet<String>> = (self.scope == TozScope::Docs).then(|| {
            files
                .iter()
                .map(|file| canonical(file).to_string_lossy().into_owned())
                .collect()
        });
        let mut store = match Store::open(&self.db_path) {
            Ok(store) => store,
            Err(error) => return unavailable(name, format!("{error:#}")),
        };
        let working_prefix = prefix_of(&working);
        let source_prefix = if self.scope == TozScope::Docs {
            prefix_of(&repo_root)
        } else {
            working_prefix.clone()
        };
        let source_prefix_excludes =
            if self.scope == TozScope::Docs && working.starts_with(&repo_root) {
                vec![working_prefix]
            } else {
                Vec::new()
            };
        let missing = match self.refresh(
            &mut store,
            &files,
            &repo_root,
            &working,
            docs_sources.as_ref(),
        ) {
            Ok(missing) => missing,
            Err(reason) => return unavailable(name, reason),
        };
        // Hits from deleted files are dropped below, so fetch the whole pool
        // when any exist and still fill the limit.
        let fetch = if missing { CANDIDATE_POOL } else { query.limit };
        let opts = SearchOpts {
            limit: fetch,
            kind: Some(ValueFilter {
                exclude: false,
                values: vec!["index".to_string()],
            }),
            source_prefix: Some(ValueFilter {
                exclude: false,
                values: vec![source_prefix],
            }),
            source_prefix_excludes,
            ..SearchOpts::default()
        };
        self.finish(&store, query, &opts, docs_sources.as_ref(), |hit| {
            let path = Path::new(&hit.source);
            let shown = match self.scope {
                TozScope::Docs => path.strip_prefix(&repo_root).unwrap_or(path),
                _ => path,
            };
            let title = if hit.title.is_empty() {
                hit.label.clone()
            } else {
                hit.title.clone()
            };
            SearchHit {
                source: name.to_string(),
                title,
                location: format!("{}:{}", shown.display(), hit.line_start),
                snippet: hit.snippet.clone(),
                score: score_of(&hit),
            }
        })
    }

    /// Run the query, drop hits whose source file is gone, keep `query.limit`.
    fn finish(
        &self,
        store: &Store,
        query: &SearchQuery,
        opts: &SearchOpts,
        allowed_sources: Option<&HashSet<String>>,
        to_hit: impl Fn(Hit) -> SearchHit,
    ) -> SourceResult {
        let results = match search(store, std::slice::from_ref(&query.text), opts) {
            Ok(results) => results,
            Err(error) => return unavailable(self.scope.name(), format!("{error:#}")),
        };
        let hits = results
            .into_iter()
            .flat_map(|result| result.hits)
            .filter(|hit| {
                (self.scope == TozScope::Output || Path::new(&hit.source).is_file())
                    && match allowed_sources {
                        Some(sources) => sources.contains(&hit.source),
                        None => true,
                    }
            })
            .take(query.limit)
            .map(to_hit)
            .collect();
        SourceResult::Hits {
            source: self.scope.name().to_string(),
            hits,
        }
    }

    /// Index new or changed files in scope. Returns whether the store holds
    /// scoped `index` captures whose file no longer exists.
    fn refresh(
        &self,
        store: &mut Store,
        files: &[PathBuf],
        repo_root: &Path,
        working: &Path,
        docs_sources: Option<&HashSet<String>>,
    ) -> Result<bool, String> {
        let mut indexed = HashMap::new();
        let mut missing = false;
        for row in store
            .list(usize::MAX, false)
            .map_err(|error| format!("{error:#}"))?
        {
            if row.kind != "index" {
                continue;
            }
            if needs_candidate_overfetch(&row.source, self.scope, repo_root, working, docs_sources)
            {
                missing = true;
            }
            indexed.insert(row.source, (row.file_mtime, row.file_hash));
        }
        for file in files {
            let Ok(abs) = std::fs::canonicalize(file) else {
                continue;
            };
            let key = abs.to_string_lossy();
            let fresh = indexed
                .get(key.as_ref())
                .is_some_and(|(mtime, hash)| !is_stale(&key, *mtime, hash.as_deref()));
            if !fresh {
                // A file that cannot be read or indexed is simply not searchable.
                let _ = index_file(&self.cfg, store, &abs, None, None);
            }
        }
        Ok(missing)
    }

    fn discover(&self, repo_root: &Path, working: &Path) -> Result<Vec<PathBuf>, String> {
        match self.scope {
            TozScope::Plans => {
                ensure_git_repository(repo_root)?;
                Ok(["plans", "reviews"]
                    .iter()
                    .flat_map(|dir| markdown_under(&working.join(dir)))
                    .collect())
            }
            _ => Ok(tracked_and_new(repo_root)?
                .into_iter()
                .filter(|rel| is_doc(rel))
                .map(|rel| repo_root.join(rel))
                .filter(|path| !path.starts_with(working))
                .collect()),
        }
    }
}

fn needs_candidate_overfetch(
    source: &str,
    scope: TozScope,
    repo_root: &Path,
    working: &Path,
    docs_sources: Option<&HashSet<String>>,
) -> bool {
    let in_scope = match scope {
        TozScope::Docs => {
            docs_sources.is_some_and(|sources| sources.contains(source))
                || is_repository_doc_source(source, repo_root, working)
        }
        TozScope::Plans => is_plan_source(source, working),
        TozScope::Output => false,
    };
    in_scope && !Path::new(source).is_file()
}

fn is_repository_doc_source(source: &str, repo_root: &Path, working: &Path) -> bool {
    let path = Path::new(source);
    !path.starts_with(working)
        && path
            .strip_prefix(repo_root)
            .ok()
            .is_some_and(|relative| is_doc(&relative.to_string_lossy()))
}

fn is_plan_source(source: &str, working: &Path) -> bool {
    source.ends_with(".md")
        && ["plans", "reviews"]
            .iter()
            .any(|dir| source.starts_with(&prefix_of(&working.join(dir))))
}

fn ensure_git_repository(repo_root: &Path) -> Result<(), String> {
    let output = Command::new("git")
        .args(["rev-parse", "--show-toplevel"])
        .current_dir(repo_root)
        .output()
        .map_err(|error| format!("git unavailable: {error}"))?;
    if output.status.success() {
        Ok(())
    } else {
        Err("not a git repository".to_string())
    }
}

impl SearchSource for TozSearch {
    fn source(&self) -> &'static str {
        self.scope.name()
    }

    fn search(&self, query: &SearchQuery) -> SourceResult {
        match self.scope {
            TozScope::Output => self.search_output(query),
            _ => self.search_files(query),
        }
    }
}

fn canonical(path: &Path) -> PathBuf {
    std::fs::canonicalize(path).unwrap_or_else(|_| path.to_path_buf())
}

/// `dir` as a path prefix that cannot match a sibling such as `dir-old/`.
fn prefix_of(dir: &Path) -> String {
    format!("{}{}", dir.display(), std::path::MAIN_SEPARATOR)
}

fn score_of(hit: &Hit) -> Option<i64> {
    Some((hit.score * 1_000_000.0).round() as i64)
}

/// Files git tracks or would track (untracked, not ignored), so new files
/// are found on every search and ignored trees such as `target/` never are.
fn tracked_and_new(repo_root: &Path) -> Result<Vec<String>, String> {
    let output = Command::new("git")
        .args([
            "ls-files",
            "-z",
            "--cached",
            "--others",
            "--exclude-standard",
        ])
        .current_dir(repo_root)
        .output()
        .map_err(|error| format!("git unavailable: {error}"))?;
    if !output.status.success() {
        return Err("not a git repository".to_string());
    }
    Ok(String::from_utf8_lossy(&output.stdout)
        .split('\0')
        .filter(|rel| !rel.is_empty())
        .map(str::to_string)
        .collect())
}

/// `README.md`/`AGENTS.md` at the root or one directory down, `docs/**/*.md`,
/// and `clis/**/README.md`.
fn is_doc(rel: &str) -> bool {
    let parts: Vec<&str> = rel.split('/').collect();
    let name = parts[parts.len() - 1];
    let guide = name == "README.md" || name == "AGENTS.md";
    (guide && parts.len() <= 2)
        || (parts[0] == "docs" && name.ends_with(".md"))
        || (parts[0] == "clis" && name == "README.md")
}

fn markdown_under(dir: &Path) -> Vec<PathBuf> {
    let mut found = Vec::new();
    let mut pending = vec![dir.to_path_buf()];
    while let Some(current) = pending.pop() {
        let Ok(entries) = std::fs::read_dir(&current) else {
            continue;
        };
        for entry in entries.flatten() {
            let path = entry.path();
            match entry.file_type() {
                Ok(kind) if kind.is_dir() => pending.push(path),
                Ok(kind) if kind.is_file() && path.extension().is_some_and(|e| e == "md") => {
                    found.push(path)
                }
                _ => {}
            }
        }
    }
    found
}

fn has_plan_markdown(working: &Path) -> bool {
    ["plans", "reviews"]
        .iter()
        .any(|dir| has_markdown_under(&working.join(dir)))
}

fn has_markdown_under(dir: &Path) -> bool {
    let mut pending = vec![dir.to_path_buf()];
    while let Some(current) = pending.pop() {
        let Ok(entries) = std::fs::read_dir(&current) else {
            continue;
        };
        for entry in entries.flatten() {
            let path = entry.path();
            match entry.file_type() {
                Ok(kind) if kind.is_dir() => pending.push(path),
                Ok(kind) if kind.is_file() && path.extension().is_some_and(|e| e == "md") => {
                    return true;
                }
                _ => {}
            }
        }
    }
    false
}

#[cfg(test)]
mod review_regressions {
    use super::*;

    #[test]
    fn only_missing_in_scope_files_trigger_candidate_overfetch() {
        let temp = tempfile::tempdir().unwrap();
        let repo_root = temp.path().join("repo");
        let working = temp.path().join("working");
        let docs_sources = HashSet::new();
        let deleted_doc = repo_root.join("README.md");
        let external_doc = temp.path().join("elsewhere/notes.md");
        let deleted_plan = working.join("plans/old.md");
        let non_file = temp.path().join("stdin-capture");

        assert!(needs_candidate_overfetch(
            &deleted_doc.to_string_lossy(),
            TozScope::Docs,
            &repo_root,
            &working,
            Some(&docs_sources),
        ));
        assert!(!needs_candidate_overfetch(
            &external_doc.to_string_lossy(),
            TozScope::Docs,
            &repo_root,
            &working,
            Some(&docs_sources),
        ));
        assert!(needs_candidate_overfetch(
            &deleted_plan.to_string_lossy(),
            TozScope::Plans,
            &repo_root,
            &working,
            None,
        ));
        for scope in [TozScope::Docs, TozScope::Plans] {
            assert!(!needs_candidate_overfetch(
                &non_file.to_string_lossy(),
                scope,
                &repo_root,
                &working,
                Some(&docs_sources),
            ));
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use toz_core::capture::{self, CaptureInput};

    struct Fixture {
        _dir: tempfile::TempDir,
        repo: PathBuf,
        working: PathBuf,
        db: PathBuf,
    }

    impl Fixture {
        fn new() -> Self {
            let dir = tempfile::tempdir().unwrap();
            let root = std::fs::canonicalize(dir.path()).unwrap();
            let repo = root.join("repo");
            let working = root.join("work");
            std::fs::create_dir_all(&repo).unwrap();
            std::fs::create_dir_all(working.join("plans")).unwrap();
            let status = Command::new("git")
                .args(["init", "-q"])
                .current_dir(&repo)
                .status()
                .unwrap();
            assert!(status.success());
            Self {
                db: root.join("toz").join("toz.db"),
                _dir: dir,
                repo,
                working,
            }
        }

        fn write(&self, rel: &str, body: &str) -> PathBuf {
            let path = self.repo.join(rel);
            std::fs::create_dir_all(path.parent().unwrap()).unwrap();
            std::fs::write(&path, body).unwrap();
            path
        }

        fn plan(&self, rel: &str, body: &str) -> PathBuf {
            let path = self.working.join("plans").join(rel);
            std::fs::write(&path, body).unwrap();
            path
        }

        fn scope(&self, scope: TozScope) -> TozSearch {
            TozSearch::new(
                scope,
                Config::default(),
                self.db.clone(),
                self.repo.clone(),
                self.working.clone(),
            )
        }

        fn capture(&self, kind: &str, source: &str, body: &str) {
            let mut store = Store::open(&self.db).unwrap();
            let mut input = CaptureInput::new(body.as_bytes(), source, kind);
            input.force = true;
            capture::run(&Config::default(), &mut store, input, &[]).unwrap();
        }

        fn ids(&self) -> Vec<i64> {
            let store = Store::open(&self.db).unwrap();
            let mut ids: Vec<i64> = store
                .list(usize::MAX, false)
                .unwrap()
                .iter()
                .map(|row| row.id)
                .collect();
            ids.sort();
            ids
        }
    }

    fn query(text: &str, limit: usize) -> SearchQuery {
        SearchQuery {
            text: text.to_string(),
            limit,
        }
    }

    fn hits(result: SourceResult) -> Vec<SearchHit> {
        match result {
            SourceResult::Hits { hits, .. } => hits,
            other => panic!("expected hits, got {other:?}"),
        }
    }

    #[test]
    fn docs_and_plans_hits_are_labeled_and_separate() {
        let f = Fixture::new();
        f.write("README.md", "# Readme\n\nzebra overview\n");
        f.plan("one.md", "# Plan\n\nzebra rollout\n");
        let docs = hits(f.scope(TozScope::Docs).search(&query("zebra", 5)));
        assert_eq!(docs.len(), 1);
        assert_eq!(docs[0].source, "docs");
        assert!(docs[0].location.starts_with("README.md:"), "{docs:?}");
        let plans = hits(f.scope(TozScope::Plans).search(&query("zebra", 5)));
        assert_eq!(plans.len(), 1);
        assert_eq!(plans[0].source, "plans");
        assert!(plans[0].location.contains("one.md"), "{plans:?}");
    }

    #[test]
    fn output_covers_capture_kinds_but_not_index() {
        let f = Fixture::new();
        f.write("README.md", "zebra in docs\n");
        f.scope(TozScope::Docs).search(&query("zebra", 5));
        f.capture("capture", "tool", "zebra from capture\n");
        f.capture("fetch", "https://example.test", "zebra fetched page\n");
        f.capture("run", "cargo test", "zebra run output\n");
        let found = hits(f.scope(TozScope::Output).search(&query("zebra", 10)));
        assert_eq!(found.len(), 3, "{found:?}");
        assert!(found.iter().all(|hit| hit.source == "output"));
        assert!(found.iter().all(|hit| !hit.snippet.contains("in docs")));
    }

    #[test]
    fn output_without_a_store_is_unavailable_and_creates_none() {
        let f = Fixture::new();
        let result = f.scope(TozScope::Output).search(&query("zebra", 5));
        assert!(matches!(result, SourceResult::Unavailable { .. }));
        assert!(!f.db.exists());
    }

    #[test]
    fn docs_and_plans_honor_limit_independently() {
        let f = Fixture::new();
        for name in ["a", "b", "c"] {
            f.write(&format!("docs/{name}.md"), "zebra notes\n");
            f.plan(&format!("{name}.md"), "zebra notes\n");
        }
        assert_eq!(
            hits(f.scope(TozScope::Docs).search(&query("zebra", 2))).len(),
            2
        );
        assert_eq!(
            hits(f.scope(TozScope::Plans).search(&query("zebra", 2))).len(),
            2
        );
        assert_eq!(
            hits(f.scope(TozScope::Docs).search(&query("zebra", 9))).len(),
            3
        );
    }

    #[test]
    fn ignored_paths_are_not_indexed() {
        let f = Fixture::new();
        f.write(".gitignore", "target/\n");
        f.write("target/README.md", "zebra build output\n");
        f.write("README.md", "zebra readme\n");
        let found = hits(f.scope(TozScope::Docs).search(&query("zebra", 5)));
        assert_eq!(found.len(), 1);
        let store = Store::open(&f.db).unwrap();
        for row in store.list(usize::MAX, false).unwrap() {
            assert!(!row.source.contains("/target/"), "{}", row.source);
        }
    }

    #[test]
    fn deleted_source_files_stop_returning_hits_and_limit_still_fills() {
        let f = Fixture::new();
        let paths: Vec<PathBuf> = (0..4)
            .map(|i| f.write(&format!("docs/{i}.md"), "zebra notes\n"))
            .collect();
        assert_eq!(
            hits(f.scope(TozScope::Docs).search(&query("zebra", 2))).len(),
            2
        );
        std::fs::remove_file(&paths[0]).unwrap();
        std::fs::remove_file(&paths[1]).unwrap();
        let after = hits(f.scope(TozScope::Docs).search(&query("zebra", 2)));
        assert_eq!(after.len(), 2, "{after:?}");
        assert!(after.iter().all(|hit| !hit.location.contains("docs/0.md")));
        assert!(after.iter().all(|hit| !hit.location.contains("docs/1.md")));
        std::fs::remove_file(&paths[2]).unwrap();
        std::fs::remove_file(&paths[3]).unwrap();
        assert!(hits(f.scope(TozScope::Docs).search(&query("zebra", 2))).is_empty());
    }

    #[test]
    fn unchanged_files_are_not_reindexed_and_changed_files_are() {
        let f = Fixture::new();
        let readme = f.write("README.md", "zebra first\n");
        f.scope(TozScope::Docs).search(&query("zebra", 5));
        let before = f.ids();
        f.scope(TozScope::Docs).search(&query("zebra", 5));
        assert_eq!(f.ids(), before);
        std::fs::write(&readme, "zebra second edition\n").unwrap();
        let found = hits(f.scope(TozScope::Docs).search(&query("second", 5)));
        assert_eq!(found.len(), 1);
        assert_ne!(f.ids(), before);
    }

    #[test]
    fn new_files_are_found_on_the_next_search() {
        let f = Fixture::new();
        f.write("README.md", "zebra readme\n");
        assert_eq!(
            hits(f.scope(TozScope::Docs).search(&query("zebra", 5))).len(),
            1
        );
        f.write("docs/new.md", "zebra newcomer\n");
        assert_eq!(
            hits(f.scope(TozScope::Docs).search(&query("zebra", 5))).len(),
            2
        );
    }

    #[test]
    fn non_repository_makes_docs_unavailable() {
        let dir = tempfile::tempdir().unwrap();
        let search = TozSearch::new(
            TozScope::Docs,
            Config::default(),
            dir.path().join("toz.db"),
            dir.path().to_path_buf(),
            dir.path().join("work"),
        );
        let result = search.search(&query("zebra", 5));
        assert!(
            matches!(result, SourceResult::Unavailable { .. }),
            "{result:?}"
        );
    }

    #[test]
    fn is_doc_matches_the_documented_patterns() {
        for yes in [
            "README.md",
            "AGENTS.md",
            "skills/README.md",
            "docs/a/b.md",
            "clis/code/crates/x/README.md",
        ] {
            assert!(is_doc(yes), "{yes}");
        }
        for no in [
            "src/main.rs",
            "a/b/README.md",
            "skills/x/AGENTS.md",
            "notes.md",
        ] {
            assert!(!is_doc(no), "{no}");
        }
    }

    /// Timing on this repository and the real working store. Run with
    /// `VARDE_TEST_WORKING=<working dir> cargo test -p varde --lib
    /// search::toz::tests::no_change_refresh -- --ignored --nocapture`.
    #[test]
    #[ignore]
    fn no_change_refresh_is_fast_on_this_repository() {
        let working = PathBuf::from(std::env::var("VARDE_TEST_WORKING").unwrap());
        let repo = Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
        let dir = tempfile::tempdir().unwrap();
        let build = |scope| {
            TozSearch::new(
                scope,
                Config::default(),
                dir.path().join("toz.db"),
                repo.clone(),
                working.clone(),
            )
        };
        let q = query("varde", 5);
        let timed = |scope| {
            let started = std::time::Instant::now();
            let found = build(scope).search(&q);
            assert!(matches!(found, SourceResult::Hits { .. }), "{found:?}");
            started.elapsed()
        };
        let first_plans = timed(TozScope::Plans);
        let first_docs = timed(TozScope::Docs);
        let again_plans = timed(TozScope::Plans);
        let again_docs = timed(TozScope::Docs);
        println!("first run: plans {first_plans:?}, docs {first_docs:?}");
        println!("no change: plans {again_plans:?}, docs {again_docs:?}");
        assert!((again_plans + again_docs).as_millis() <= 300);
    }
}
