//! Contracts between Varde modules: traits plus plain data, no implementations.
//!
//! Every trait is `Send + Sync` because the hook call runs on a worker thread.

use std::path::{Path, PathBuf};

/// Error from a capability call. `code` is the envelope `data.error.code`
/// when the implementation reported one.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ContractError {
    pub code: Option<String>,
    pub message: String,
}

/// Session-start repo map text for a repo root.
pub trait RepoMap: Send + Sync {
    /// Text map of `repo_root`, including project knowledge.
    fn repo_map_text(&self, repo_root: &Path) -> Result<String, ContractError>;
}

/// Transitive dependents of a file.
pub trait ImpactQuery: Send + Sync {
    /// Canonical paths of files that depend on `file` (transitively), or
    /// `None` when unknown.
    fn dependents(&self, repo_root: &Path, file: &Path) -> Option<Vec<PathBuf>>;
}

/// What to capture.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CaptureInput<'a> {
    Text(&'a str),
    Items(&'a [String]),
}

/// Capture output out of the agent context.
pub trait OutputCapture: Send + Sync {
    /// Capture `input` under `source` and `label`; returns the preview
    /// containing the handle, or `None` when capture is unavailable.
    fn capture(&self, input: CaptureInput<'_>, source: &str, label: &str) -> Option<String>;
}

/// A text search over one source, capped at `limit` hits.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SearchQuery {
    pub text: String,
    pub limit: usize,
}

/// One match from a source, in that source's own terms.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SearchHit {
    pub source: String,
    pub title: String,
    pub location: String,
    pub snippet: String,
    /// The engine's own relevance score, when it reports one. Scores from
    /// different sources are not comparable.
    pub score: Option<i64>,
}

/// What one source returned: its hits (possibly none), or why it could not
/// be searched.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SourceResult {
    Hits {
        source: String,
        hits: Vec<SearchHit>,
    },
    Unavailable {
        source: String,
        reason: String,
    },
}

/// A searchable store. Hits come back in the store's own ranking.
pub trait SearchSource: Send + Sync {
    /// Stable source name, as used by `varde search --in`.
    fn source(&self) -> &'static str;

    /// Search the store; never more than `query.limit` hits.
    fn search(&self, query: &SearchQuery) -> SourceResult;
}

/// Capabilities the app crate passes to each module's `run(args, io)`.
/// An absent capability behaves like a missing binary does today.
#[derive(Clone, Copy, Default)]
pub struct Io<'a> {
    pub repo_map: Option<&'a dyn RepoMap>,
    pub impact: Option<&'a dyn ImpactQuery>,
    pub capture: Option<&'a dyn OutputCapture>,
}

#[cfg(test)]
mod tests {
    use super::*;

    struct Fake;
    impl RepoMap for Fake {
        fn repo_map_text(&self, repo_root: &Path) -> Result<String, ContractError> {
            if repo_root.as_os_str().is_empty() {
                return Err(ContractError {
                    code: Some("invalid_repo_root".into()),
                    message: "empty".into(),
                });
            }
            Ok("map".into())
        }
    }
    impl ImpactQuery for Fake {
        fn dependents(&self, _: &Path, file: &Path) -> Option<Vec<PathBuf>> {
            (file == Path::new("a.rs")).then(|| vec![PathBuf::from("b.rs")])
        }
    }
    impl OutputCapture for Fake {
        fn capture(&self, input: CaptureInput<'_>, source: &str, label: &str) -> Option<String> {
            match input {
                CaptureInput::Text(t) => Some(format!("[h1] {source}/{label}: {t}")),
                CaptureInput::Items(i) => Some(format!("[h2] {source}/{label}: {}", i.len())),
            }
        }
    }

    fn assert_send_sync<T: Send + Sync + ?Sized>() {}

    struct Echo;
    impl SearchSource for Echo {
        fn source(&self) -> &'static str {
            "echo"
        }
        fn search(&self, query: &SearchQuery) -> SourceResult {
            SourceResult::Hits {
                source: self.source().into(),
                hits: vec![SearchHit {
                    source: self.source().into(),
                    title: query.text.clone(),
                    location: String::new(),
                    snippet: String::new(),
                    score: None,
                }],
            }
        }
    }

    #[test]
    fn search_source_is_send_sync_and_object_safe() {
        assert_send_sync::<dyn SearchSource>();
        let source: &dyn SearchSource = &Echo;
        let query = SearchQuery {
            text: "q".into(),
            limit: 1,
        };
        assert!(matches!(
            source.search(&query),
            SourceResult::Hits { hits, .. } if hits[0].title == "q"
        ));
    }

    #[test]
    fn traits_are_send_sync_and_object_safe() {
        assert_send_sync::<dyn RepoMap>();
        assert_send_sync::<dyn ImpactQuery>();
        assert_send_sync::<dyn OutputCapture>();
    }

    #[test]
    fn default_io_has_no_capabilities() {
        let io = Io::default();
        assert!(io.repo_map.is_none() && io.impact.is_none() && io.capture.is_none());
    }

    #[test]
    fn io_routes_to_implementations() {
        let fake = Fake;
        let io = Io {
            repo_map: Some(&fake),
            impact: Some(&fake),
            capture: Some(&fake),
        };
        assert_eq!(
            io.repo_map.unwrap().repo_map_text(Path::new("/r")),
            Ok("map".to_string())
        );
        let err = io
            .repo_map
            .unwrap()
            .repo_map_text(Path::new(""))
            .unwrap_err();
        assert_eq!(err.code.as_deref(), Some("invalid_repo_root"));
        assert_eq!(
            io.impact
                .unwrap()
                .dependents(Path::new("/r"), Path::new("a.rs")),
            Some(vec![PathBuf::from("b.rs")])
        );
        assert_eq!(
            io.impact
                .unwrap()
                .dependents(Path::new("/r"), Path::new("z.rs")),
            None
        );
        let c = io.capture.unwrap();
        assert_eq!(
            c.capture(CaptureInput::Text("x"), "s", "l"),
            Some("[h1] s/l: x".into())
        );
        assert_eq!(
            c.capture(CaptureInput::Items(&["a".into(), "b".into()]), "s", "l"),
            Some("[h2] s/l: 2".into())
        );
    }
}
