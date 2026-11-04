from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).parents[1] / "scripts" / "live_role_inbox_helpers.py"
_SPEC = importlib.util.spec_from_file_location("live_role_inbox_helpers", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)


def test_unread_snapshot_is_stable_and_deduplicated() -> None:
    assert _MODULE.unread_snapshot({"b": ["m2", "m1", "m2"], "a": []}) == {
        "b": ("m1", "m2"),
        "a": (),
    }


def test_same_unread_set_ignores_order() -> None:
    assert _MODULE.same_unread_set(["m2", "m1"], ["m1", "m2"])
    assert not _MODULE.same_unread_set(["m1"], ["m1", "m2"])


def test_one_claim_requires_exactly_one_holder() -> None:
    assert _MODULE.one_claim([None, {"id": "item-1"}, None]) == {"id": "item-1"}
    with pytest.raises(AssertionError, match="expected one claim"):
        _MODULE.one_claim([None, None])
    with pytest.raises(AssertionError, match="expected one claim"):
        _MODULE.one_claim([{"id": "item-1"}, {"id": "item-1"}])


def test_restart_check_rejects_store_mode_mismatch() -> None:
    _MODULE.assert_clean_restart("runner started\n")
    with pytest.raises(AssertionError, match="interrupted store mode flip"):
        _MODULE.assert_clean_restart("Error: interrupted store mode flip")
    with pytest.raises(AssertionError, match="schema version"):
        _MODULE.assert_clean_restart("invalid queue schema version")


def test_tree_digest_tracks_file_contents_and_symlinks(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "data").write_text("before", encoding="utf-8")
    (source / "alias").symlink_to("data")
    original = _MODULE.tree_digest(source)
    (source / "data").write_text("after", encoding="utf-8")
    assert _MODULE.tree_digest(source) != original


def test_tree_digest_can_ignore_atomic_replace_temporaries(tmp_path: Path) -> None:
    source = tmp_path / "working"
    relay = source / ".cache" / "inbox" / "relay"
    relay.mkdir(parents=True)
    ignored = frozenset({".cache/inbox/relay/.state.json.*"})
    original = _MODULE.tree_digest(source, ignored)

    (relay / ".state.json.123.tmp").write_text("temporary")

    assert _MODULE.tree_digest(source, ignored) == original
