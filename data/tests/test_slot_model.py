from datetime import UTC, datetime, timedelta

import pytest
from varde_data.slot_model import (
    SLOT_STATES,
    Slot,
    epoch_matches,
    is_stale,
    next_state,
)


def make_slot(**changes: object) -> Slot:
    values: dict[str, object] = {
        "slot_id": "plan-worker",
        "plan_id": "plan",
        "role": "builder",
        "lease_s": 60,
        "epoch": 3,
        "last_progress_at": "2026-10-26T12:00:00+00:00",
    }
    values.update(changes)
    return Slot(**values)  # type: ignore[arg-type]


def test_slot_states_and_epoch_matching() -> None:
    assert {"active", "parked", "handed_off", "dead"} == SLOT_STATES
    assert epoch_matches(make_slot(), 3)
    assert not epoch_matches(make_slot(), 2)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        ("active", "parked"),
        ("active", "handed_off"),
        ("active", "dead"),
        ("parked", "active"),
        ("parked", "dead"),
        ("handed_off", "active"),
        ("handed_off", "dead"),
    ],
)
def test_allowed_state_transitions(current: str, target: str) -> None:
    assert next_state(current, target) == target  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("current", "target"),
    [
        ("active", "active"),
        ("parked", "parked"),
        ("handed_off", "parked"),
        ("dead", "active"),
    ],
)
def test_invalid_state_transitions(current: str, target: str) -> None:
    with pytest.raises(ValueError, match="invalid slot state transition"):
        next_state(current, target)  # type: ignore[arg-type]


def test_staleness_boundary_is_inclusive() -> None:
    now = datetime(2026, 10, 26, 12, 1, tzinfo=UTC)
    assert not is_stale(make_slot(), now - timedelta(microseconds=1), 60)
    assert is_stale(make_slot(), now, 60)


def test_parked_slot_never_stale_and_new_slot_uses_updated_at() -> None:
    now = datetime(2026, 10, 26, 12, 5, tzinfo=UTC)
    parked = make_slot(state="parked")
    no_progress = make_slot(
        last_progress_at=None, updated_at="2026-10-26T12:00:00+00:00"
    )
    assert not is_stale(parked, now, 1)
    assert is_stale(no_progress, now, 60)
