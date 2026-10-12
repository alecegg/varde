use super::unavailable;
use serde_json::{Value, json};
use std::path::PathBuf;
use varde_contracts::{SearchHit, SearchQuery, SearchSource, SourceResult};

const SOURCE: &str = "code";

/// Code search over an existing `varde-code` index (`context_pack`).
/// It never builds an index.
pub struct CodeSearch {
    repo_root: PathBuf,
    db_path: PathBuf,
}

impl CodeSearch {
    pub fn new(repo_root: PathBuf, db_path: PathBuf) -> Self {
        Self { repo_root, db_path }
    }
}

impl SearchSource for CodeSearch {
    fn source(&self) -> &'static str {
        SOURCE
    }

    fn search(&self, query: &SearchQuery) -> SourceResult {
        let input = json!({
            "repoRoot": self.repo_root,
            "dbPath": self.db_path,
            "query": query.text,
            "fullResults": true,
        });
        let envelope = varde_code::query::run_mode("context_pack", &input.to_string());
        hits_from_envelope(&envelope, query.limit)
    }
}

/// Map a `context_pack` envelope: `not_found` is an empty result, any other
/// error code makes the source unavailable.
fn hits_from_envelope(envelope: &str, limit: usize) -> SourceResult {
    let Ok(value) = serde_json::from_str::<Value>(envelope) else {
        return unavailable(SOURCE, "unreadable code query result");
    };
    if value["ok"] != true {
        let code = value["data"]["error"]["code"].as_str().unwrap_or("error");
        return if code == "not_found" {
            SourceResult::Hits {
                source: SOURCE.to_string(),
                hits: Vec::new(),
            }
        } else {
            unavailable(SOURCE, code)
        };
    }
    let data = &value["data"];
    let files = data["files"]
        .as_array()
        .into_iter()
        .flatten()
        .filter_map(|file| {
            let path = file["path"].as_str()?;
            Some(hit(path, path, file["relevance"].as_str().unwrap_or("")))
        });
    let symbols = data["symbols"]
        .as_array()
        .into_iter()
        .flatten()
        .filter_map(|symbol| {
            let name = symbol["name"].as_str()?;
            let path = symbol["filePath"].as_str()?;
            let line = symbol["span"]["start_line"].as_u64().unwrap_or(0);
            let kind = symbol["kind"].as_str().unwrap_or("");
            Some(hit(name, &format!("{path}:{line}"), kind))
        });
    SourceResult::Hits {
        source: SOURCE.to_string(),
        hits: files.chain(symbols).take(limit).collect(),
    }
}

fn hit(title: &str, location: &str, snippet: &str) -> SearchHit {
    SearchHit {
        source: SOURCE.to_string(),
        title: title.to_string(),
        location: location.to_string(),
        snippet: snippet.to_string(),
        score: None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    struct Fixture {
        _dir: tempfile::TempDir,
        search: CodeSearch,
    }

    /// A small repo indexed at an explicit db path under the temp dir.
    fn indexed_repo() -> Fixture {
        let dir = tempfile::tempdir().unwrap();
        let repo = dir.path().join("repo");
        fs::create_dir_all(repo.join("src")).unwrap();
        fs::write(repo.join("src/lib.rs"), "pub fn needle_handler() {}\n").unwrap();
        fs::write(repo.join("src/other.rs"), "pub fn needle_helper() {}\n").unwrap();
        let db = dir.path().join("index.db");
        varde_code::build_index_at(repo.to_str().unwrap(), &db).unwrap();
        Fixture {
            search: CodeSearch::new(repo.canonicalize().unwrap(), db),
            _dir: dir,
        }
    }

    fn query(text: &str, limit: usize) -> SearchQuery {
        SearchQuery {
            text: text.to_string(),
            limit,
        }
    }

    #[test]
    fn finds_files_and_symbols() {
        let fixture = indexed_repo();
        let SourceResult::Hits { source, hits } =
            fixture.search.search(&query("needle_handler", 10))
        else {
            panic!("expected hits");
        };
        assert_eq!(source, "code");
        assert!(
            hits.iter().any(|h| h.location.ends_with("src/lib.rs")),
            "{hits:?}"
        );
        assert!(hits.iter().any(|h| h.title == "needle_handler"), "{hits:?}");
    }

    #[test]
    fn no_match_is_ok_with_no_hits() {
        let fixture = indexed_repo();
        assert_eq!(
            fixture.search.search(&query("zzz_absent_zzz", 10)),
            SourceResult::Hits {
                source: "code".into(),
                hits: Vec::new()
            }
        );
    }

    #[test]
    fn limit_caps_hits() {
        let fixture = indexed_repo();
        let SourceResult::Hits { hits, .. } = fixture.search.search(&query("needle", 1)) else {
            panic!("expected hits");
        };
        assert_eq!(hits.len(), 1);
    }

    #[test]
    fn missing_index_is_unavailable_and_not_built() {
        let dir = tempfile::tempdir().unwrap();
        let db = dir.path().join("index.db");
        let search = CodeSearch::new(dir.path().to_path_buf(), db.clone());
        assert_eq!(
            search.search(&query("x", 5)),
            SourceResult::Unavailable {
                source: "code".into(),
                reason: "index_missing".into()
            }
        );
        assert!(!db.exists());
    }

    #[test]
    fn other_error_codes_are_unavailable_with_the_code() {
        let envelope = r#"{"ok":false,"data":{"error":{"code":"db_error"}}}"#;
        assert_eq!(
            hits_from_envelope(envelope, 5),
            SourceResult::Unavailable {
                source: "code".into(),
                reason: "db_error".into()
            }
        );
    }
}
