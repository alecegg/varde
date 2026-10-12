//! Exact, read-only AST rewrite proposals.

mod apply;
pub mod cli;
mod preview;

pub use apply::{ApplyFileResult, ApplyOptions, ApplyResult, ApplyStatus, apply};
pub use cli::{Options, cli_command, run};
pub use preview::{
    Diagnostic, FileChange, MatchSpan, PreviewOptions, PreviewResult, Proposal, Relation,
    RewriteRule, preview,
};
