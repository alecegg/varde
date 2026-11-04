"""Minimal validation for call-site records against the shipped schema."""

CALL_CLASSES = {
    "same_file",
    "imported",
    "member",
    "constructor",
    "higher_order",
    "dynamic",
}
MEASURED_STATUSES = {"resolved", "ambiguous", "opaque", "unresolved", "external"}
GROUND_TRUTH_SENTINELS = {"external", "unknown"}
REQUIRED_FIELDS = {
    "repo",
    "language",
    "file",
    "line",
    "call_class",
    "ground_truth",
    "measured_edge",
    "measured_status",
    "truth_source",
    "function_id",
    "module",
}


def validate_record(record: dict[str, object]) -> None:
    """Raise ``ValueError`` when a call-site record violates schema constraints."""
    missing = REQUIRED_FIELDS - record.keys()
    if missing:
        raise ValueError(
            f"call-site record is missing fields: {', '.join(sorted(missing))}"
        )
    for field in ("repo", "language", "file", "truth_source"):
        if not isinstance(record[field], str) or not record[field]:
            raise ValueError(f"call-site {field} must be a non-empty string")
    if (
        not isinstance(record["line"], int)
        or isinstance(record["line"], bool)
        or record["line"] < 1
    ):
        raise ValueError("call-site line must be a positive integer")
    if record["call_class"] not in CALL_CLASSES:
        raise ValueError("call-site call_class is invalid")
    if record["measured_status"] not in MEASURED_STATUSES:
        raise ValueError("call-site measured_status is invalid")
    truth = record["ground_truth"]
    if not isinstance(truth, str) or not truth:
        raise ValueError(
            "call-site ground_truth must be a target id, external, or unknown"
        )
    for field in (
        "call_name",
        "measured_edge",
        "measured_file",
        "measured_name",
        "function_id",
        "module",
        "ground_truth_module",
        "measured_module",
    ):
        value = record.get(field)
        if value is not None and not isinstance(value, str):
            raise ValueError(f"call-site {field} must be a string or null")
    measured_line = record.get("measured_line")
    if measured_line is not None and (
        not isinstance(measured_line, int)
        or isinstance(measured_line, bool)
        or measured_line < 1
    ):
        raise ValueError("call-site measured_line must be a positive integer or null")
