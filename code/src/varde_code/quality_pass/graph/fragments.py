"""File and module fragmentation inputs and call-resolution confidence."""

_MICRO = 1_000_000


def _is_fragment(function, tfrag):
    return (
        function.get("file_private") is True
        and not function.get("exempt_role")
        and function.get("tokens") is not None
        and function["tokens"] <= tfrag
        and function.get("callers_in_module", 0) <= 1
    )


def _share_micros(coverage):
    resolved = coverage.get("resolved", 0)
    unresolved = coverage.get("ambiguous", 0) + coverage.get("opaque", 0)
    total = resolved + unresolved
    return (unresolved * _MICRO) // total if total else 0


def fragment_counts(facts, tfrag):
    """Count private small helpers by scope and compute per-file confidence.

    facts is a sequence of facts-1 per-file records. unresolved_share is stored
    in integer millionths; confidence uses an exact integer ratio.
    """
    file_count = 0
    module_count = 0
    per_file = {}
    for file_fact in sorted(facts, key=lambda item: item.get("path", "")):
        path = file_fact.get("path", "")
        for function in file_fact.get("functions", []):
            if not _is_fragment(function, tfrag):
                continue
            if function.get("fragment_scope") == "file":
                file_count += 1
            elif function.get("fragment_scope") == "module":
                module_count += 1

        coverage = file_fact.get("call_coverage", {})
        resolved = coverage.get("resolved", 0)
        unresolved = coverage.get("ambiguous", 0) + coverage.get("opaque", 0)
        total = resolved + unresolved
        per_file[path] = {
            "unresolved_share": _share_micros(coverage),
            "structure_confidence": (
                "low" if unresolved * 10 > total * 3 else "normal"
            ),
        }
    return {"file": file_count, "module": module_count, "per_file": per_file}
