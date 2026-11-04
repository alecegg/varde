from __future__ import annotations

import pytest
from varde_runner.node_host import GiveUp, Restart, RestartPolicy, next_action

POLICY = RestartPolicy()


@pytest.mark.parametrize(
    ("history", "now", "expected"),
    [
        ([10.0], 10.0, Restart(1.0)),
        ([10.0, 20.0], 20.0, Restart(2.0)),
        ([10.0, 20.0, 30.0], 30.0, Restart(4.0)),
        ([10.0, 20.0, 30.0, 40.0], 40.0, GiveUp(4)),
        # The first death left the 300 s window, so this is the third in window.
        ([0.0, 100.0, 200.0, 310.0], 310.0, Restart(4.0)),
        # A death exactly window_s old is outside the window.
        ([0.0, 300.0], 300.0, Restart(1.0)),
        ([0.0, 299.0], 299.0, Restart(2.0)),
        ([], 0.0, Restart(1.0)),
    ],
)
def test_next_action_table(history, now, expected) -> None:
    assert next_action(history, now, POLICY) == expected


def test_delays_clamp_to_last_when_max_exceeds_delays() -> None:
    policy = RestartPolicy(max_restarts=5, window_s=60.0, delays_s=(1.0, 2.0))
    assert next_action([1, 2, 3, 4], 4.0, policy) == Restart(2.0)
    assert next_action([1, 2, 3, 4, 5, 6], 6.0, policy) == GiveUp(6)
