"""Cache keys hash the bytes the pass parsed, never the fast index's FNV hash."""

from __future__ import annotations

import hashlib
import json

from pass_support import build_index, facts_by_path, prepare_env, write_repo
from varde_code.quality_pass.pass_ import run_quality_pass
from varde_code.quality_pass.pass_.keys import (
    content_digest,
    facts_key,
    language_profile_version,
)


def test_content_digest_is_blake2b_of_the_bytes_parsed():
    raw = b"def f():\n    return 1\n"
    expected = "blake2b-" + hashlib.blake2b(raw, digest_size=32).hexdigest()

    assert content_digest(raw) == expected
    assert content_digest(b"def f():\n    return 2\n") != expected


def test_facts_key_parts_are_content_and_versions():
    key = facts_key("blake2b-abc", "python", "extractor-9")

    assert json.loads(key) == [
        "blake2b-abc",
        "extractor-9",
        language_profile_version("python"),
    ]
    assert language_profile_version("python") != language_profile_version("go")
    assert language_profile_version("python") != "quality-profile-python-1"


def test_stored_content_hash_is_blake2b_of_the_file_bytes(tmp_path, monkeypatch):
    root = prepare_env(monkeypatch, tmp_path)
    write_repo(root, {"src/app.py": "def run():\n    return 1\n"})
    build_index(root)
    run_quality_pass(root, workers=1)

    raw = (root / "src/app.py").read_bytes()
    expected = "blake2b-" + hashlib.blake2b(raw, digest_size=32).hexdigest()

    assert facts_by_path(root)["src/app.py"]["content_hash"] == expected
