"""Tiny notes domain used to prove the repository contract harness."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from varde_data.errors import Invalid, NotFound
from varde_data.locking import atomic_write, file_lock
from varde_data.version import Version


@dataclass(frozen=True)
class Note:
    key: str
    text: str


class NotesReader(Protocol):
    def get(self, key: str) -> Note: ...

    def list(self) -> tuple[list[Note], list[str]]: ...

    def version(self) -> Version: ...


class NotesRepository(NotesReader, Protocol):
    def put(self, key: str, text: str) -> Note: ...


def _validate(key: str, text: str) -> None:
    if not isinstance(key, str) or not key.strip():
        raise Invalid("note key must be non-empty text")  # noqa: TRY003, RUF100
    if not isinstance(text, str) or not text.strip():
        raise Invalid("note text must be non-empty text")  # noqa: TRY003, RUF100


class MemoryNotes:
    def __init__(self) -> None:
        self._notes: dict[str, str] = {}
        self._revision = 0

    def put(self, key: str, text: str) -> Note:
        _validate(key, text)
        self._notes[key] = text
        self._revision += 1
        return Note(key, text)

    def get(self, key: str) -> Note:
        try:
            return Note(key, self._notes[key])
        except KeyError as exc:
            raise NotFound(f"note {key!r} not found") from exc  # noqa: TRY003, RUF100

    def list(self) -> tuple[list[Note], list[str]]:
        return [Note(key, self._notes[key]) for key in sorted(self._notes)], []

    def version(self) -> Version:
        return Version(self._revision)


class FilesNotes:
    def __init__(self, root: Path) -> None:
        self.root = root / "notes"
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, key: str, text: str) -> Note:
        _validate(key, text)
        path = self.root / f"{hashlib.sha256(key.encode()).hexdigest()}.json"
        payload = json.dumps({"key": key, "text": text}, ensure_ascii=False).encode()
        with file_lock(self.root / ".lock", timeout=30):
            atomic_write(path, payload, mode=0o644)
        return Note(key, text)

    def get(self, key: str) -> Note:
        path = self.root / f"{hashlib.sha256(key.encode()).hexdigest()}.json"
        try:
            note = self._read_note(path)
        except FileNotFoundError as exc:
            raise NotFound(f"note {key!r} not found") from exc  # noqa: TRY003, RUF100
        if note.key != key:
            raise NotFound(f"note {key!r} not found")  # noqa: TRY003, RUF100
        return note

    def list(self) -> tuple[list[Note], list[str]]:
        notes: list[Note] = []
        skipped: list[str] = []
        for path in sorted(self.root.glob("*.json")):
            try:
                notes.append(self._read_note(path))
            except OSError, UnicodeError, json.JSONDecodeError, Invalid:
                skipped.append(path.name)
        return notes, skipped

    def version(self) -> Version:
        digest = hashlib.sha256()
        for path in sorted(self.root.glob("*.json")):
            digest.update(path.name.encode())
            try:
                digest.update(path.read_bytes())
            except OSError:
                digest.update(b"<unreadable>")
        return Version(digest.hexdigest())

    @staticmethod
    def _read_note(path: Path) -> Note:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or not isinstance(raw.get("key"), str):
            raise Invalid("invalid note record")  # noqa: TRY003, RUF100
        if not isinstance(raw.get("text"), str):
            raise Invalid("invalid note record")  # noqa: TRY003, RUF100
        _validate(raw["key"], raw["text"])
        return Note(raw["key"], raw["text"])
