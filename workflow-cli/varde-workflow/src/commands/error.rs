//! Shared error reporting for command handlers.

use anyhow::Result;
use okf_core::crud::create::CreateError;
use okf_core::crud::delete::DeleteError;
use okf_core::crud::list::ListError;
use okf_core::crud::search::TextSearchError;
use okf_core::crud::show::ShowError;
use okf_core::crud::update::UpdateError;
use okf_core::crud::{ConceptIoError, FieldError};
use okf_core::lint::LintError;
use okf_core::maps::MapError;
use okf_core::registry::RegistryError;

/// Maps a handler error to a distinct process exit code, so scripts driving
/// this CLI can distinguish failure kinds (OCC conflict vs not-found vs a
/// validation error) by exit status instead of parsing message text.
///
/// Codes:
/// - `1`: unclassified/infrastructure failure (I/O, parse error, etc.) —
///   the default, and the fallback for every kind this scheme doesn't
///   distinguish.
/// - `2`: not found.
/// - `3`: OCC version conflict (`--expected-version` is stale).
/// - `4`: invalid input (invalid slug, validation failure).
/// - `5`: already exists (`concept create` only).
pub trait ExitCode {
    fn exit_code(&self) -> i32 {
        1
    }

    fn error_code(&self) -> &'static str {
        "internal"
    }
}

impl ExitCode for ConceptIoError {
    fn exit_code(&self) -> i32 {
        match self {
            ConceptIoError::NotFound { .. } => 2,
            ConceptIoError::Conflict { .. } => 3,
            ConceptIoError::InvalidSlug { .. } => 4,
            ConceptIoError::ReadFailed { .. } | ConceptIoError::WriteFailed { .. } => 1,
        }
    }

    fn error_code(&self) -> &'static str {
        match self {
            ConceptIoError::NotFound { .. } => "not_found",
            ConceptIoError::Conflict { .. } => "conflict",
            ConceptIoError::InvalidSlug { .. } => "invalid_input",
            ConceptIoError::ReadFailed { .. } | ConceptIoError::WriteFailed { .. } => "internal",
        }
    }
}

impl ExitCode for CreateError {
    fn exit_code(&self) -> i32 {
        match self {
            CreateError::Io(io) => io.exit_code(),
            CreateError::AlreadyExists { .. } => 5,
            CreateError::Metadata(_) => 4,
            CreateError::Concept(_) | CreateError::CreateDirFailed { .. } => 1,
        }
    }

    fn error_code(&self) -> &'static str {
        match self {
            CreateError::Io(io) => io.error_code(),
            CreateError::AlreadyExists { .. } => "already_exists",
            CreateError::Metadata(_) => "invalid_input",
            CreateError::Concept(_) | CreateError::CreateDirFailed { .. } => "internal",
        }
    }
}

impl ExitCode for UpdateError {
    fn exit_code(&self) -> i32 {
        match self {
            UpdateError::Io(io) => io.exit_code(),
            UpdateError::MissingType | UpdateError::Concept(_) => 4,
        }
    }

    fn error_code(&self) -> &'static str {
        match self {
            UpdateError::Io(io) => io.error_code(),
            UpdateError::MissingType | UpdateError::Concept(_) => "invalid_input",
        }
    }
}

impl ExitCode for DeleteError {
    fn exit_code(&self) -> i32 {
        match self {
            DeleteError::Io(io) => io.exit_code(),
            DeleteError::NotFound { .. } => 2,
            DeleteError::InvalidSlug { .. } => 4,
            DeleteError::DeleteFailed { .. } => 1,
        }
    }

    fn error_code(&self) -> &'static str {
        match self {
            DeleteError::Io(io) => io.error_code(),
            DeleteError::NotFound { .. } => "not_found",
            DeleteError::InvalidSlug { .. } => "invalid_input",
            DeleteError::DeleteFailed { .. } => "internal",
        }
    }
}

impl ExitCode for ListError {
    fn exit_code(&self) -> i32 {
        match self {
            ListError::Io(io) => io.exit_code(),
            ListError::ReadDirFailed { .. } | ListError::InvalidConcept { .. } => 1,
        }
    }

    fn error_code(&self) -> &'static str {
        match self {
            ListError::Io(io) => io.error_code(),
            ListError::ReadDirFailed { .. } | ListError::InvalidConcept { .. } => "internal",
        }
    }
}

impl ExitCode for ShowError {
    fn exit_code(&self) -> i32 {
        match self {
            ShowError::Io(io) => io.exit_code(),
            ShowError::Concept(_) => 1,
        }
    }

    fn error_code(&self) -> &'static str {
        match self {
            ShowError::Io(io) => io.error_code(),
            ShowError::Concept(_) => "internal",
        }
    }
}

impl ExitCode for FieldError {
    fn exit_code(&self) -> i32 {
        match self {
            FieldError::Io(io) => io.exit_code(),
            FieldError::MissingType
            | FieldError::InvalidStatus { .. }
            | FieldError::InvalidType
            | FieldError::ReservedStructuredField { .. }
            | FieldError::InvalidConcept { .. } => 4,
        }
    }

    fn error_code(&self) -> &'static str {
        match self {
            FieldError::Io(io) => io.error_code(),
            _ => "invalid_input",
        }
    }
}

impl ExitCode for RegistryError {}

impl ExitCode for TextSearchError {}

impl ExitCode for LintError {}

impl ExitCode for MapError {}

/// A CLI-side input-validation error (malformed flags, conflicting
/// arguments) — printed through the same [`report_error`] path as core
/// errors so the versioned JSON error envelope applies uniformly,
/// instead of `bail!`/`anyhow!` bypassing it via `main`'s `?` and printing
/// anyhow's plain, non-JSON `Error: <msg>` default.
#[derive(Debug)]
pub struct CliError(pub String);

impl std::fmt::Display for CliError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.0)
    }
}

impl ExitCode for CliError {
    fn error_code(&self) -> &'static str {
        "invalid_input"
    }
}

#[derive(Debug)]
pub struct InternalError(pub String);

impl std::fmt::Display for InternalError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.0)
    }
}

impl ExitCode for InternalError {}

/// Print an error to stderr and exit with a code determined by
/// [`ExitCode::exit_code`].
///
/// In `--json` mode the error is printed under `data.error` in the shared
/// envelope. Text mode prints `error: <message>`. Never returns because the
/// process exits after stderr is flushed.
pub fn report_error(err: &(impl std::fmt::Display + ExitCode), json: bool) -> Result<()> {
    if json {
        crate::output::print_error(err.error_code(), err.to_string());
    } else {
        eprintln!("error: {err}");
    }
    std::process::exit(err.exit_code());
}

/// Route a handler's `Result` through the `--json`/text rendering split and
/// [`report_error`], so each handler supplies only its two payload
/// renderers instead of hand-repeating the
/// `match { Ok => if json {..} else {..}, Err => report_error }` scaffold.
pub fn finish<T>(
    result: Result<T, impl std::fmt::Display + ExitCode>,
    json: bool,
    render_json: impl FnOnce(&T) -> Result<()>,
    render_text: impl FnOnce(&T) -> Result<()>,
) -> Result<()> {
    match result {
        Ok(value) => {
            if json {
                render_json(&value)
            } else {
                render_text(&value)
            }
        }
        Err(err) => report_error(&err, json),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn not_found_maps_to_2() {
        let err = ConceptIoError::NotFound { slug: "x".into() };
        assert_eq!(err.exit_code(), 2);
    }

    #[test]
    fn conflict_maps_to_3() {
        let err = ConceptIoError::Conflict {
            slug: "x".into(),
            expected: "a".into(),
            actual: "b".into(),
        };
        assert_eq!(err.exit_code(), 3);
    }

    #[test]
    fn invalid_slug_maps_to_4() {
        let err = ConceptIoError::InvalidSlug { slug: "x".into() };
        assert_eq!(err.exit_code(), 4);
    }

    #[test]
    fn create_already_exists_maps_to_5() {
        let err = CreateError::AlreadyExists { slug: "x".into() };
        assert_eq!(err.exit_code(), 5);
    }

    #[test]
    fn create_metadata_maps_to_4() {
        let err =
            CreateError::Metadata(okf_core::concept::ConceptMetadataError::MissingDescription);
        assert_eq!(err.exit_code(), 4);
        assert_eq!(err.error_code(), "invalid_input");
    }

    #[test]
    fn create_wrapped_conflict_delegates_to_inner_code() {
        let err = CreateError::Io(ConceptIoError::Conflict {
            slug: "x".into(),
            expected: "a".into(),
            actual: "b".into(),
        });
        assert_eq!(err.exit_code(), 3);
    }

    #[test]
    fn delete_not_found_maps_to_2() {
        let err = DeleteError::NotFound { slug: "x".into() };
        assert_eq!(err.exit_code(), 2);
    }

    #[test]
    fn registry_error_defaults_to_1() {
        let err = RegistryError::ReadDirFailed {
            path: "x".into(),
            source: std::io::Error::other("boom"),
        };
        assert_eq!(err.exit_code(), 1);
    }
}
