"""Shared diagnose models, harness dispatch, and provider-independent helpers."""

from __future__ import annotations

from importlib import import_module

_EXPORTS = {
    "ContextUsage": (".context_usage", "ContextUsage"),
    "ContextUsageHarness": (".context_usage", "ContextUsageHarness"),
    "context_usage": (".context_usage", "context_usage"),
    "ListHarness": (".list", "ListHarness"),
    "ListRequest": (".list", "ListRequest"),
    "ListedSession": (".list", "ListedSession"),
    "ListedWorker": (".list", "ListedWorker"),
    "SessionList": (".list", "SessionList"),
    "list_sessions": (".list", "list_sessions"),
    "HARNESS_ADAPTERS": (".model", "HARNESS_ADAPTERS"),
    "ChildSession": (".model", "ChildSession"),
    "Coverage": (".model", "Coverage"),
    "CurrentOverlap": (".model", "CurrentOverlap"),
    "DiagnosticHarness": (".model", "DiagnosticHarness"),
    "EvidenceRecord": (".model", "EvidenceRecord"),
    "HarnessAdapter": (".model", "HarnessAdapter"),
    "Inspection": (".model", "Inspection"),
    "InspectionSnapshot": (".model", "InspectionSnapshot"),
    "NormalizedRecordBudget": (".model", "NormalizedRecordBudget"),
    "RecordAnchor": (".model", "RecordAnchor"),
    "SessionMetadata": (".model", "SessionMetadata"),
    "SourceCompanion": (".model", "SourceCompanion"),
    "SourceSnapshot": (".model", "SourceSnapshot"),
    "ToolObservation": (".model", "ToolObservation"),
    "harness_adapter": (".model", "harness_adapter"),
    "register_harness": (".model", "register_harness"),
    "CandidateSession": ("..session_link", "CandidateSession"),
    "ParentSession": ("..session_link", "ParentSession"),
    "SessionSource": ("..session_link", "SessionSource"),
    "WorkerLink": ("..session_link", "WorkerLink"),
    "link_workers": ("..session_link", "link_workers"),
}

__all__ = [
    "HARNESS_ADAPTERS",
    "CandidateSession",
    "ChildSession",
    "ContextUsage",
    "ContextUsageHarness",
    "Coverage",
    "CurrentOverlap",
    "DiagnosticHarness",
    "EvidenceRecord",
    "HarnessAdapter",
    "Inspection",
    "InspectionSnapshot",
    "ListHarness",
    "ListRequest",
    "ListedSession",
    "ListedWorker",
    "NormalizedRecordBudget",
    "ParentSession",
    "RecordAnchor",
    "SessionList",
    "SessionMetadata",
    "SessionSource",
    "SourceCompanion",
    "SourceSnapshot",
    "ToolObservation",
    "WorkerLink",
    "context_usage",
    "harness_adapter",
    "link_workers",
    "list_sessions",
    "register_harness",
]


def __getattr__(name: str):
    try:
        module_name, _attribute = _EXPORTS[name]
    except KeyError as error:
        raise AttributeError(
            f"module {__name__!r} has no attribute {name!r}"
        ) from error
    module = import_module(module_name, __name__)
    for exported_name, (exported_module, exported_attribute) in _EXPORTS.items():
        if exported_module == module_name:
            globals()[exported_name] = getattr(module, exported_attribute)
    return globals()[name]
