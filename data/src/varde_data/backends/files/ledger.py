"""Append-only files backend for analyzed sessions and sweep digests."""

import json
import os
from datetime import date
from pathlib import Path
from typing import Any

from varde_data.learn_store_mode import files_writer
from varde_data.records.ledger import Digest, LedgerRow
from varde_data.testing import MemoryLedger


class FilesLedger(MemoryLedger):
    def mark(
        self,
        harness: str,
        session: str,
        when: str,
        summary: str,
        metrics: dict[str, Any] | None = None,
        friction_added: list[str] | None = None,
    ) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        with files_writer(self.root, "ledger"):
            self._append_row(harness, session, when, summary, metrics, friction_added)

    def _append_row(
        self,
        harness: str,
        session: str,
        when: str,
        summary: str,
        metrics: dict[str, Any] | None,
        friction_added: list[str] | None,
    ) -> None:
        row = {
            "session": session,
            "harness": harness,
            "analyzed_at": when,
            "summary": summary,
            "metrics": metrics or {},
            "friction_added": friction_added or [],
        }
        line = (json.dumps(row, separators=(",", ":")) + "\n").encode()
        descriptor = os.open(
            self.root / "analyzed.jsonl", os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600
        )
        try:
            path = self.root / "analyzed.jsonl"
            if path.stat().st_size:
                with path.open("rb") as existing:
                    existing.seek(-1, os.SEEK_END)
                    if existing.read(1) != b"\n":
                        os.write(descriptor, b"\n")
            written = os.write(descriptor, line)
            if written != len(line):
                raise OSError("short write while appending analyzed session")
        finally:
            os.close(descriptor)

    def analyzed(self) -> list[LedgerRow]:
        path = self.root / "analyzed.jsonl"
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError, UnicodeDecodeError:
            return []
        latest: dict[tuple[str, str], LedgerRow] = {}
        for line in lines:
            try:
                value = json.loads(line)
            except json.JSONDecodeError, ValueError:
                continue
            if not isinstance(value, dict) or not all(
                isinstance(value.get(key), str) and value[key]
                for key in ("session", "harness", "analyzed_at")
            ):
                continue
            latest[(value["harness"], value["session"])] = LedgerRow(
                value["session"],
                value["harness"],
                value["analyzed_at"],
                value.get("summary"),
                value.get("metrics"),
                value.get("friction_added"),
            )
        return list(latest.values())

    def seen(self, harness: str) -> set[str]:
        return {row.session for row in self.analyzed() if row.harness == harness}

    def write_digest(
        self, run_date: date, text: str, candidates: list[dict[str, Any]]
    ) -> None:
        path = self.root / "digests" / f"{run_date.isoformat()}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        with files_writer(self.root, "ledger"):
            self._write_digest_file(path, run_date, text, candidates)

    def _write_digest_file(
        self,
        path: Path,
        run_date: date,
        text: str,
        candidates: list[dict[str, Any]],
    ) -> None:
        path.write_text(
            json.dumps(
                {"date": run_date.isoformat(), "text": text, "candidates": candidates},
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    def read_digest(self, run_date: date) -> Digest | None:
        path = self.root / "digests" / f"{run_date.isoformat()}.json"
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except OSError, UnicodeError, json.JSONDecodeError:
            return None
        if not isinstance(value, dict) or not isinstance(value.get("text"), str):
            return None
        return Digest(run_date.isoformat(), value["text"], value.get("candidates", []))
