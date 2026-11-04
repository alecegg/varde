from varde_dev.calibrate.rating.fit import fit
from varde_dev.calibrate.rating.select import next_pairs, stop_state


def test_selects_only_within_group_and_exhausts_pairs_before_repeat():
    ratings = {
        "a": {"group_id": "g", "rating": 0, "standard_error": 1},
        "b": {"group_id": "g", "rating": 0, "standard_error": 1},
        "c": {"group_id": "g", "rating": 0, "standard_error": 1},
        "z": {"group_id": "h", "rating": 0, "standard_error": 1},
    }
    groups = {"g": ["a", "b", "c"], "h": ["z"]}
    played = [("g", "a", "b"), ("g", "a", "c")]
    pairs = next_pairs(ratings, played, groups, k=1)
    assert pairs == [("g", "b", "c")]
    after = next_pairs(ratings, played + pairs, groups, k=1)
    assert after == [("g", "a", "b")]
    assert next_pairs(ratings, played, groups) == next_pairs(ratings, played, groups)


def test_close_pair_is_preferred_and_bootstrap_covers_each_item():
    ratings = {
        "a": {"group_id": "g", "rating": 2.0, "standard_error": 0.1},
        "b": {"group_id": "g", "rating": 0.0, "standard_error": 0.1},
        "c": {"group_id": "g", "rating": 0.0, "standard_error": 1.0},
        "d": {"group_id": "g", "rating": 0.0, "standard_error": 1.0},
    }
    assert next_pairs(ratings, [], {"g": ["a", "b", "c", "d"]}, k=1) == [
        ("g", "a", "b"),
        ("g", "c", "d"),
    ]
    played = [
        ("g", "a", "b"),
        ("g", "a", "c"),
        ("g", "a", "d"),
        ("g", "b", "c"),
        ("g", "b", "d"),
    ]
    assert next_pairs(ratings, played, {"g": ["a", "b", "c", "d"]}) == [("g", "c", "d")]


def test_noise_free_oracle_recovers_order_within_budget():
    for size in (8, 16):
        items = [f"i{index:02}" for index in range(size)]
        groups = {"g": items}
        played = []
        outcomes = []
        budget = size * ((size - 1).bit_length()) * 2
        while len(played) < budget:
            ratings = fit(outcomes, [("g", item) for item in items])
            pairs = next_pairs(ratings, played, groups)
            if not pairs:
                break
            for group, left, right in pairs[: budget - len(played)]:
                played.append((group, left, right))
                winner = max(left, right)
                outcomes.append((group, left, right, "x" if winner == left else "y"))
        fitted = fit(outcomes, [("g", item) for item in items])
        assert sorted(
            items, key=lambda item: fitted[item]["rating"], reverse=True
        ) == list(reversed(items))
        assert len(played) <= size * ((size - 1).bit_length()) * 2


def test_stop_state_reports_confidence_or_budget_and_group_intervals():
    items = [("g", name) for name in "ab"]
    ratings = fit([("g", "a", "b", "x")] * 30, items)
    confident = stop_state(
        ratings, [("g", "a", "b")] * 30, {"g": ["a", "b"]}, {"confidence": 0.9}
    )
    assert confident["reason"] == "confident"
    assert set(confident["groups"]["g"]) == {"a", "b"}
    budget = stop_state(fit([], items), [], {"g": ["a", "b"]}, {"budget": 0})
    assert budget["reason"] == "budget"
    assert "g" in budget["groups"]


def test_ties_use_canonical_pair_order_and_bootstrap_returns_full_round():
    ratings = {
        item: {"group_id": "g", "rating": 0.0, "standard_error": 1.0} for item in "abcd"
    }
    assert next_pairs(ratings, [], {"g": list("dcba")}, k=1) == [
        ("g", "a", "b"),
        ("g", "c", "d"),
    ]


def test_group_at_budget_waits_for_open_group_and_never_crosses_groups():
    groups = {"g1": ["a", "b"], "g2": ["c", "d"]}
    ratings = fit(
        [], [(group, item) for group, items in groups.items() for item in items]
    )
    played = [("g1", "a", "b")]
    state = stop_state(ratings, played, groups, {"budget": 1})
    assert state["stop"] is False
    assert state["groups_status"] == {"g1": "budget", "g2": "open"}
    assert state["reason"] is None
    pairs = next_pairs(ratings, played, groups)
    assert pairs == [("g2", "c", "d")]
    assert all(
        group in groups and left in groups[group] and right in groups[group]
        for group, left, right in pairs
    )


def test_budget_default_and_confidence_precedence():
    groups = {"g": list("abcd")}
    items = [("g", item) for item in groups["g"]]
    ratings = fit([], items)
    still_open = stop_state(ratings, [("g", "a", "b")] * 7, groups, {})
    assert still_open["groups_status"]["g"] == "open"
    budget = stop_state(ratings, [("g", "a", "b")] * 8, groups, {})
    assert budget["groups_status"]["g"] == "budget"
    assert budget["reason"] == "budget"
    confident = {
        "a": {"rating": 5.0, "standard_error": 0.1},
        "b": {"rating": -5.0, "standard_error": 0.1},
    }
    both = stop_state(confident, [("g", "a", "b")] * 100, {"g": ["a", "b"]}, {})
    assert both["groups_status"]["g"] == "confident"
    assert both["reason"] == "confident"
    mixed = stop_state(
        {
            "a": {"rating": 5.0, "standard_error": 0.1},
            "b": {"rating": -5.0, "standard_error": 0.1},
            "c": {"rating": 0.0, "standard_error": 1.0},
            "d": {"rating": 0.0, "standard_error": 1.0},
        },
        [("certain", "a", "b"), ("spent", "c", "d")],
        {"certain": ["a", "b"], "spent": ["c", "d"]},
        {"budget": 1},
    )
    assert mixed["groups_status"] == {"certain": "confident", "spent": "budget"}
    assert mixed["reason"] == "budget"


def test_overlapping_intervals_keep_group_open():
    ratings = {
        "a": {"rating": 0.1, "standard_error": 1.0},
        "b": {"rating": 0.0, "standard_error": 1.0},
    }
    state = stop_state(ratings, [], {"g": ["a", "b"]}, {})
    assert state["groups_status"]["g"] == "open"
    assert state["reason"] is None


def test_unplayed_pairs_in_any_group_precede_repeats_everywhere():
    groups = {"g1": list("abc"), "g2": list("de")}
    ratings = {
        item: {"rating": 0.0, "standard_error": 1.0}
        for items in groups.values()
        for item in items
    }
    played = [("g1", "a", "b"), ("g2", "d", "e")]
    assert next_pairs(ratings, played, groups) == [("g1", "a", "c")]


def test_noise_free_chains_stop_confident_before_complete_graph():
    for names in (
        list("abcd"),
        [f"i{index:02}" for index in range(8)],
        [f"i{index:02}" for index in range(16)],
    ):
        group = "g"
        items = [(group, item) for item in names]
        groups = {group: names}
        played = []
        outcomes = []
        state = stop_state(fit([], items), played, groups, {})
        while state["reason"] is None:
            ratings = fit(outcomes, items)
            pairs = next_pairs(ratings, played, groups)
            assert pairs
            for _, left, right in pairs:
                winner = max(left, right)
                outcome = "x" if winner == left else "y"
                played.append((group, left, right, outcome))
                outcomes.append((group, left, right, outcome))
            state = stop_state(fit(outcomes, items), played, groups, {})
            assert len(played) <= len(names) * ((len(names) - 1).bit_length()) * 2
        fitted = fit(outcomes, items)
        assert sorted(
            names, key=lambda item: fitted[item]["rating"], reverse=True
        ) == list(reversed(names))
        assert state["reason"] == "confident"
        assert len(played) < len(names) * (len(names) - 1) // 2
