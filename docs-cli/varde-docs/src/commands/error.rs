//! Shared error reporting for command handlers.

use anyhow::Result;
use okf_core::crud::create::CreateError;
use okf_core::crud::delete::DeleteError;
use okf_core::crud::list::ListError;
use okf_core::crud::show::ShowError;
use okf_core::crud::search::TextSearchError;
use okf_core::crud::update::UpdateError;
use okf_core::crud::{ConceptIoError, FieldError};
use okf_core::lint::LintError;
use okf_core::registry::RegistryError;
use serde_json::json;

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
}

impl ExitCode for CreateError {
    fn exit_code(&self) -> i32 {
        match self {
            CreateError::Io(io) => io.exit_code(),
            CreateError::AlreadyExists { .. } => 5,
            CreateError::Concept(_) | CreateError::CreateDirFailed { .. } => 1,
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
}

impl ExitCode for DeleteError {
    fn exit_code(&self) -> i32 {
        match self {
            DeleteError::NotFound { .. } => 2,
            DeleteError::InvalidSlug { .. } => 4,
            DeleteError::DeleteFailed { .. } => 1,
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
}

impl ExitCode for ShowError {
    fn exit_code(&self) -> i32 {
        match self {
            ShowError::Io(io) => io.exit_code(),
            ShowError::Concept(_) => 1,
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
}

impl ExitCode for RegistryError {}

impl ExitCode for TextSearchError {}

impl ExitCode for LintError {}

/// A CLI-side input-validation error (malformed flags, conflicting
/// arguments) — printed through the same [`report_error`] path as core
/// errors so the `--json` `{"error": "..."}` envelope applies uniformly,
/// instead of `bail!`/`anyhow!` bypassing it via `main`'s `?` and printing
/// anyhow's plain, non-JSON `Error: <msg>` default.
#[derive(Debug)]
pub struct CliError(pub String);

impl std::fmt::Display for CliError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.0)
    }
}

impl ExitCode for CliError {}

/// Print an error to stderr and exit with a code determined by
/// [`ExitCode::exit_code`].
///
/// In `--json` mode the error is printed as a single JSON object
/// `{ "error": "<message>" }` on stderr; otherwise as plain
/// `error: <message>`. Never returns — the process exits after stderr is
/// flushed.
pub fn report_error(err: &(impl std::fmt::Display + ExitCode), json: bool) -> Result<()> {
    if json {
        eprintln!("{}", json!({ "error": err.to_string() }));
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
        let err = ConceptIoError::NotFound {
            slug: "x".into(),
        };
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
