/// Errors surfaced by `varde-learn-core` operations.
#[derive(Debug, thiserror::Error)]
pub enum LearnError {
    /// The requested command has not been implemented yet.
    #[error("not implemented: {0}")]
    NotImplemented(String),
    /// A usage, environment, or eval-run error that exits with status 2,
    /// mirroring `die()` in `skills/eval-tools/run-evals.sh`.
    #[error("{0}")]
    Usage(String),
    /// A configured store directory could not be read or parsed.
    #[error("invalid global learn store configuration at {path}: {message}")]
    StoreConfig {
        path: std::path::PathBuf,
        message: String,
    },
    /// Friction add arguments or referenced item are invalid.
    #[error("invalid friction store operation: {message}")]
    StoreInvalid { message: String },
    /// The requested friction item ID or slug does not exist.
    #[error("friction item `{identifier}` was not found")]
    StoreItemNotFound { identifier: String },
    /// The store path is inside a Git repository and must be moved elsewhere.
    #[error(
        "refusing friction store at {path}: it is inside Git repository {repo_root}; set VARDE_LEARN_STORE or run `varde-workflow paths set --learn <dir>` to choose a global store directory"
    )]
    StoreInsideGit {
        path: std::path::PathBuf,
        repo_root: std::path::PathBuf,
    },
    /// The requested schema was created by a newer varde-learn version.
    #[error(
        "friction store schema version {found} is newer than supported version {supported}; upgrade varde-learn"
    )]
    StoreSchemaTooNew { found: i64, supported: i64 },
    /// The schema version metadata is malformed.
    #[error("invalid friction store schema version `{value}`")]
    StoreSchemaVersion { value: String },
    /// Git repository detection failed, so store safety could not be verified.
    #[error("could not verify whether friction store path {path} is inside Git: {message}")]
    StoreGitCheck {
        path: std::path::PathBuf,
        message: String,
    },
    /// Store filesystem access failed.
    #[error("could not {operation} friction store at {path}: {source}")]
    StoreIo {
        operation: &'static str,
        path: std::path::PathBuf,
        #[source]
        source: std::io::Error,
    },
    /// SQLite store initialization or access failed.
    #[error("could not initialize friction store at {path}: {source}")]
    StoreDatabase {
        path: std::path::PathBuf,
        #[source]
        source: rusqlite::Error,
    },
    /// A typed error from the read-only diagnosis intake.
    #[error("{message}")]
    Diagnose { code: &'static str, message: String },
}

impl LearnError {
    /// Stable machine-readable error identifier for the CLI envelope.
    pub fn code(&self) -> &'static str {
        match self {
            Self::NotImplemented(_) => "not_implemented",
            Self::Usage(_) => "usage_error",
            Self::StoreConfig { .. } => "store_config_error",
            Self::StoreInvalid { .. } => "store_invalid",
            Self::StoreItemNotFound { .. } => "store_item_not_found",
            Self::StoreInsideGit { .. } => "store_inside_git",
            Self::StoreSchemaTooNew { .. } => "store_schema_too_new",
            Self::StoreSchemaVersion { .. } => "store_schema_invalid",
            Self::StoreGitCheck { .. } => "store_git_check_failed",
            Self::StoreIo { .. } => "store_io_error",
            Self::StoreDatabase { .. } => "store_database_error",
            Self::Diagnose { code, .. } => code,
        }
    }
}
