"""Persist function complexity metrics derived from extracted entities."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence

from varde_code.complexity import function_complexities
from varde_code.index.certified import has_certified_complexity_profile
from varde_code.index.persist.entities import FileIds
from varde_code.model import ExtractOutput

_METRIC_VERSION = 3


def write_function_metrics(
    connection: sqlite3.Connection, outputs: Sequence[ExtractOutput], file_ids: FileIds
) -> None:
    """Persist the shared complexity engine's metrics and confidence evidence."""
    rows = []
    for output_index, output in enumerate(outputs):
        diagnostic_files = {
            item.file_id for item in output.diagnostics if item.file_id is not None
        }
        syntax_files = {
            item.file_id
            for item in output.diagnostics
            if item.file_id is not None and "syntax error" in item.message
        }
        for metric in function_complexities(output.entities):
            path = output.files[metric.file_id]
            certified_language = has_certified_complexity_profile(path)
            confidence = _confidence(
                metric.confidence.value,
                metric.file_id in diagnostic_files,
                certified_language,
            )
            reasons = [f"{item.kind}:{item.name}" for item in metric.confidence_reasons]
            if metric.file_id in syntax_files:
                reasons.append("syntax_diagnostic")
            elif metric.file_id in diagnostic_files:
                reasons.append("file_diagnostic")
            if not certified_language:
                reasons.append("unsupported_language_profile")
            span = metric.span
            rows.append(
                (
                    file_ids.get(output_index, metric.file_id),
                    f"{metric.owner_type}::{metric.name}"
                    if metric.owner_type
                    else metric.name,
                    metric.name,
                    metric.owner_type,
                    span.start_byte,
                    span.end_byte,
                    span.start_line,
                    span.start_col,
                    span.end_line,
                    span.end_col,
                    metric.cyclomatic,
                    metric.cognitive,
                    metric.max_nesting,
                    metric.line_span,
                    metric.byte_size,
                    confidence,
                    json.dumps(reasons, separators=(",", ":")),
                    _METRIC_VERSION,
                )
            )
    connection.executemany(
        "INSERT INTO function_metrics(file_id,identity,name,owner_type,start_byte,end_byte,"
        "start_line,start_col,end_line,end_col,cyclomatic,cognitive,max_nesting,line_span,byte_size,"
        "confidence,confidence_reasons,metric_version) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        rows,
    )


def _confidence(
    metric_confidence: str, has_diagnostic: bool, certified_language: bool
) -> str:
    if metric_confidence == "low" or has_diagnostic:
        return "low"
    return "high" if certified_language else "partial"
