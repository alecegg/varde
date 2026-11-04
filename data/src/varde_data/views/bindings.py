"""Pure binding presentation helpers."""

from collections.abc import Iterable, Mapping


def annotate_stale_bindings(
    bindings: list[dict[str, object]], archived_paseo_ids: Iterable[str]
) -> list[dict[str, object]]:
    """Copy binding rows and mark those belonging to archived Paseo agents."""
    archived = set(archived_paseo_ids)
    result = []
    for record in bindings:
        wake_context = record.get("wake_context")
        paseo_id = None
        if isinstance(wake_context, Mapping):
            paseo_id = wake_context.get("paseo_id", wake_context.get("paseo_agent_id"))
        result.append(
            {**record, "stale": isinstance(paseo_id, str) and paseo_id in archived}
        )
    return result
