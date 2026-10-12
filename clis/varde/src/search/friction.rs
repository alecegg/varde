use super::unavailable;
use std::path::PathBuf;
use varde_contracts::{SearchHit, SearchQuery, SearchSource, SourceResult};
use varde_learn_core::{FrictionListRequest, PageRequest, Store};

const SOURCE: &str = "friction";

/// Friction text filter over an existing `varde-learn` store.
pub struct FrictionSearch {
    store_dir: PathBuf,
}

impl FrictionSearch {
    pub fn new(store_dir: PathBuf) -> Self {
        Self { store_dir }
    }
}

impl SearchSource for FrictionSearch {
    fn source(&self) -> &'static str {
        SOURCE
    }

    fn search(&self, query: &SearchQuery) -> SourceResult {
        // `Store::open` creates and migrates, so only open a store that exists.
        if !self.store_dir.join("learn.db").is_file() {
            return unavailable(SOURCE, "no friction store");
        }
        let request = FrictionListRequest {
            status: None,
            source: None,
            repo_root: None,
            global: false,
            text: Some(query.text.clone()),
            cwd: self.store_dir.clone(),
            page: PageRequest {
                offset: 0,
                limit: query.limit,
            },
        };
        let page = Store::open(&self.store_dir).and_then(|mut store| store.list_items(&request));
        match page {
            Ok(page) => SourceResult::Hits {
                source: SOURCE.to_string(),
                hits: page
                    .items
                    .into_iter()
                    .take(query.limit)
                    .map(|item| SearchHit {
                        source: SOURCE.to_string(),
                        title: item.title,
                        location: item.slug,
                        snippet: format!("{} ({})", item.status, item.source),
                        score: None,
                    })
                    .collect(),
            },
            Err(error) => unavailable(SOURCE, error.to_string()),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use varde_learn_core::{FrictionAddMode, FrictionAddRequest};

    fn query(text: &str, limit: usize) -> SearchQuery {
        SearchQuery {
            text: text.to_string(),
            limit,
        }
    }

    fn store_with(titles: &[&str]) -> tempfile::TempDir {
        let dir = tempfile::tempdir().unwrap();
        let mut store = Store::open(dir.path()).unwrap();
        for title in titles {
            store
                .add_friction(FrictionAddRequest {
                    mode: FrictionAddMode::Create {
                        source: "test".into(),
                        title: (*title).into(),
                        target: None,
                        global: true,
                    },
                    evidence: format!("evidence for {title}"),
                    cwd: dir.path().to_path_buf(),
                })
                .unwrap();
        }
        dir
    }

    #[test]
    fn finds_matching_items() {
        let dir = store_with(&["sandbox denies cache writes", "unrelated item"]);
        let result = FrictionSearch::new(dir.path().to_path_buf()).search(&query("sandbox", 10));
        let SourceResult::Hits { hits, .. } = result else {
            panic!("expected hits");
        };
        assert_eq!(hits.len(), 1);
        assert_eq!(hits[0].title, "sandbox denies cache writes");
    }

    #[test]
    fn limit_caps_hits() {
        let dir = store_with(&["sandbox one", "sandbox two", "sandbox three"]);
        let result = FrictionSearch::new(dir.path().to_path_buf()).search(&query("sandbox", 2));
        let SourceResult::Hits { hits, .. } = result else {
            panic!("expected hits");
        };
        assert_eq!(hits.len(), 2);
    }

    #[test]
    fn missing_store_is_unavailable_and_not_created() {
        let dir = tempfile::tempdir().unwrap();
        let store_dir = dir.path().join("learn");
        let result = FrictionSearch::new(store_dir.clone()).search(&query("x", 5));
        assert!(matches!(result, SourceResult::Unavailable { .. }));
        assert!(!store_dir.exists());
    }

    #[test]
    fn empty_dir_without_database_is_unavailable_and_gets_no_file() {
        let dir = tempfile::tempdir().unwrap();
        let result = FrictionSearch::new(dir.path().to_path_buf()).search(&query("x", 5));
        assert!(matches!(result, SourceResult::Unavailable { .. }));
        assert!(!dir.path().join("learn.db").exists());
    }
}
