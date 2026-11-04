"""Files-specific status metadata for legacy message watermarks."""

from __future__ import annotations

import io
import json
from pathlib import Path

from varde_data.repos.messages import parse_messages


def below_watermark(inbox: Path) -> set[str]:
    """Return IDs at or before their reader watermark."""
    try:
        raw = (inbox / "messages.jsonl").read_bytes()
    except FileNotFoundError:
        return set()
    messages = parse_messages(raw)
    watermarks: dict[str, int] = {}
    for message in messages.records:
        try:
            watermarks[message.to] = int(
                json.loads((inbox / "index" / f"{message.to}.json").read_text()).get(
                    "watermark", 0
                )
            )
        except OSError, ValueError, TypeError, AttributeError:
            watermarks[message.to] = 0
    result = set()
    offset = 0
    message_index = 0
    for line in io.BytesIO(raw):
        if not line.endswith(b"\n"):
            break
        end = offset + len(line)
        try:
            row = json.loads(line)
        except ValueError, UnicodeDecodeError:
            offset = end
            continue
        if (
            not isinstance(row, dict)
            or not all(
                isinstance(row.get(field), str)
                for field in ("ts", "from", "to", "kind", "text")
            )
            or (row.get("notes") is not None and not isinstance(row["notes"], str))
            or (row.get("id") is not None and not isinstance(row["id"], str))
        ):
            offset = end
            continue
        message = messages.records[message_index]
        message_index += 1
        message_id = message.id
        watermark = watermarks.get(str(row.get("to", "")), 0)
        if message_id and watermark and end <= watermark:
            result.add(message_id)
        offset = end
    return result
