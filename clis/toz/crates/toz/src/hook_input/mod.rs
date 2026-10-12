//! Per-behavior transforms for hook tool results, wired once in `commands.rs`.
//!
//! One file per behavior, so the behavior tasks fill in stubs without
//! touching the wiring: `cwd_noise` (strip the harness cwd-reset line),
//! `scoped` (pass already-bounded output through), `readonly` (the 16 KiB
//! read threshold for read-only shell commands), `compound` (per-command
//! preview headings) and `redact` (shared-engine redaction with notices).
//!
//! Every function here fails open: today's stubs return the input unchanged
//! or a neutral answer, and the real implementations keep that contract.

pub mod compound;
pub mod cwd_noise;
pub mod readonly;
pub mod redact;
pub mod scoped;
