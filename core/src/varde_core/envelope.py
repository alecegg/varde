"""Versioned machine output envelopes shared by Varde commands."""

ENVELOPE_VERSION = 1


def _envelope(ok: bool, outcome: str, data: object, meta: object) -> dict[str, object]:
    return {
        "schema_version": ENVELOPE_VERSION,
        "envelope_version": ENVELOPE_VERSION,
        "ok": ok,
        "outcome": outcome,
        "data": data,
        "meta": meta,
    }


def success(data: object, meta: object) -> dict[str, object]:
    return _envelope(True, "success", data, meta)


def negative_result(
    code: str, message: str, details: object, meta: object
) -> dict[str, object]:
    error = {"code": code, "message": message, "details": details}
    return _envelope(False, "negative-result", {"error": error}, meta)


def tool_error(code: str, message: str) -> dict[str, object]:
    error = {"code": code, "message": message}
    return _envelope(False, "tool-error", {"error": error}, {"truncated": False})
