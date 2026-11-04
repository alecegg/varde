"""Measure prompt hook latency on the inbox golden fixture shape."""

from __future__ import annotations

import json
import statistics
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path


def main() -> None:
    from varde_data.config import load_data_config
    from varde_data.open import open_data
    from varde_data.records.messages import NewMessage

    with tempfile.TemporaryDirectory() as directory:
        working = Path(directory)
        repo = open_data(working, load_data_config()).messages
        repo.append(
            NewMessage(
                "sender", "worker", "info", "hook delivery", ts="2026-10-22T12:00:00Z"
            )
        )
        from varde_workflow.binding import BindingStore

        binding = BindingStore(working)
        marker = binding.issue("worker", now=datetime(2026, 10, 22, 12, tzinfo=UTC))
        binding.redeem(
            marker,
            "session",
            "claude",
            str(working),
            now=datetime(2026, 10, 22, 12, tzinfo=UTC),
        )
        from varde.glue.inbox_hook import prompt_inbox

        payload = json.dumps({"session_id": "session", "prompt": ""}).encode()
        samples = []
        for _ in range(30):
            start = time.perf_counter()
            prompt_inbox("claude", payload, banner_enabled=False)
            samples.append((time.perf_counter() - start) * 1000)
        print(f"median_ms={statistics.median(samples):.3f} samples=30")


if __name__ == "__main__":
    main()
