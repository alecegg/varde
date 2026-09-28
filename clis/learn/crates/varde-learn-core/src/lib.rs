//! Shared types for the `varde-learn` CLI.

mod codex;
pub mod diagnose;
mod error;
mod import;
mod output;
mod process;
mod store;
mod trigger;

pub use error::LearnError;
pub use import::{
    FrictionImportEntry, FrictionImportFile, FrictionImportSummary, read_import_files,
};
pub use output::{
    Config, EvalOutcome, OutputHarness, OutputReport, OutputRequest, RunRecord, run_output,
};
pub use process::{ExitResult, RunOutcome, RunRequest, run_with_timeout};
pub use store::{
    AdoptionRecord, AdoptionRecordRequest, DEFAULT_PAGE_LIMIT, FrictionAddMode, FrictionAddRequest,
    FrictionExportItem, FrictionIncidentProvenance, FrictionItem, FrictionListRequest,
    FrictionOccurrence, FrictionRecurrence, FrictionRecurrenceReport, FrictionShow, FrictionStatus,
    FrictionStatusChange, HistoricalCaptureRequest, HistoricalCaptureResult, HistoricalItemMode,
    HistoricalOccurrenceRequest, HistoricalWitness, MAX_PAGE_LIMIT, PageRequest, Store, StorePage,
    resolve_store_dir,
};
pub use trigger::{Harness, Query, TriggerReport, TriggerRequest, run_trigger};
