use super::unavailable;
use std::path::PathBuf;
use varde_contracts::{SearchHit, SearchQuery, SearchSource, SourceResult};
use varde_workflow_core::crud::search::search_text_matching;

const SOURCE: &str = "knowledge";

/// Concept text search over one knowledge bundle.
pub struct KnowledgeSearch {
    bundle: PathBuf,
}

impl KnowledgeSearch {
    pub fn new(bundle: PathBuf) -> Self {
        Self { bundle }
    }
}

impl SearchSource for KnowledgeSearch {
    fn source(&self) -> &'static str {
        SOURCE
    }

    fn search(&self, query: &SearchQuery) -> SourceResult {
        if !self.bundle.is_dir() {
            return unavailable(SOURCE, "knowledge bundle not found");
        }
        match search_text_matching(
            std::slice::from_ref(&self.bundle),
            &query.text,
            &[],
            query.limit,
        ) {
            Ok(results) => SourceResult::Hits {
                source: SOURCE.to_string(),
                hits: results
                    .into_iter()
                    .map(|result| SearchHit {
                        source: SOURCE.to_string(),
                        title: result.slug.clone(),
                        location: result.slug,
                        snippet: result.preview,
                        score: Some(result.score),
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
    use std::fs;

    fn bundle() -> tempfile::TempDir {
        let dir = tempfile::tempdir().unwrap();
        for (name, body) in [
            ("alpha", "Rust ownership notes."),
            ("beta", "Rust borrowing."),
            ("gamma", "Unrelated."),
        ] {
            fs::write(
                dir.path().join(format!("{name}.md")),
                format!("---\ntype: decision\ntitle: {name}\n---\n# {name}\n{body}\n"),
            )
            .unwrap();
        }
        dir
    }

    fn query(text: &str, limit: usize) -> SearchQuery {
        SearchQuery {
            text: text.to_string(),
            limit,
        }
    }

    #[test]
    fn finds_matching_concepts() {
        let dir = bundle();
        let result = KnowledgeSearch::new(dir.path().to_path_buf()).search(&query("ownership", 10));
        let SourceResult::Hits { hits, .. } = result else {
            panic!("expected hits");
        };
        assert_eq!(hits.len(), 1);
        assert_eq!(hits[0].location, "alpha");
        assert!(hits[0].snippet.contains("ownership"));
    }

    #[test]
    fn limit_caps_hits() {
        let dir = bundle();
        let result = KnowledgeSearch::new(dir.path().to_path_buf()).search(&query("rust", 1));
        let SourceResult::Hits { hits, .. } = result else {
            panic!("expected hits");
        };
        assert_eq!(hits.len(), 1);
    }

    #[test]
    fn missing_bundle_is_unavailable() {
        let dir = tempfile::tempdir().unwrap();
        let search = KnowledgeSearch::new(dir.path().join("absent"));
        assert!(matches!(
            search.search(&query("x", 5)),
            SourceResult::Unavailable { .. }
        ));
    }
}
