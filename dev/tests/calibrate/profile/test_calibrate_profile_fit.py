import math
import random

from varde_dev.calibrate.profile.fit import fit_profile


def _synthetic():
    components = {
        f"item-{index:02d}": {
            "cognitive": float(index),
            "size": float((index * 7) % 13),
            "depth": 2.0,
        }
        for index in range(30)
    }
    labels = []
    generator = random.Random(573)  # noqa: S311 - Seeded randomness makes test data reproducible.
    for left in range(30):
        for right in range(left + 1, 30):
            x, y = f"item-{left:02d}", f"item-{right:02d}"
            difference = 0.2 * (components[x]["cognitive"] - components[y]["cognitive"])
            difference -= 0.5 * (components[x]["size"] - components[y]["size"])
            probability = 1.0 / (1.0 + math.exp(-difference))
            choice = x if generator.random() < probability else y
            labels.append(("group", x, y, "x" if choice == x else "y"))
    return components, labels


def test_fit_recovers_weight_signs_and_reports_constant_component():
    components, labels = _synthetic()
    result = fit_profile(labels, components)
    weights = result["weights"]
    assert weights["cognitive"]["weight"] > 0
    assert weights["size"]["weight"] < 0
    assert 0.5 < weights["cognitive"]["weight"] < 3.0
    assert -2.8 < weights["size"]["weight"] < -0.8
    assert weights["depth"]["weight"] == 0
    assert "depth" in result["constant_components"]
    assert result["under_determined"] is False


def test_fit_is_order_independent_and_regularized_for_separation():
    components, labels = _synthetic()
    baseline = fit_profile(labels, components)
    shuffled_labels = labels[:]
    shuffled_items = list(components.items())
    random.Random(781).shuffle(shuffled_labels)  # noqa: S311 - Seeded shuffle makes this test deterministic.
    random.Random(24).shuffle(shuffled_items)  # noqa: S311 - Seeded shuffle makes this test deterministic.
    shuffled = fit_profile(shuffled_labels, dict(shuffled_items))
    assert shuffled == baseline

    separating = [("g", "high", "low", "x")] * 300
    result = fit_profile(
        separating,
        {"high": {"signal": 1.0}, "low": {"signal": 0.0}},
    )
    assert abs(result["weights"]["signal"]["weight"]) < 20


def test_under_determined_and_dislikes_are_rating_ordered_with_drivers():
    components = {
        "a": {"size": 0.0},
        "b": {"size": 1.0},
        "c": {"size": 2.0},
    }
    labels = [("g", "a", "b", "x"), ("g", "b", "c", "x")]
    result = fit_profile(labels, components)
    assert result["under_determined"] is True
    dislikes = result["dislikes_most"]["by_group"]["g"]
    assert [item["item_id"] for item in dislikes] == ["c", "b", "a"]
    assert dislikes[0]["driving_components"]


def test_order_shown_choices_are_converted_to_item_ids():
    from varde_dev.calibrate.profile.fit import canonicalize_labels

    labels = [
        {
            "rater_id": "person",
            "unit_id": "u",
            "choice": "A",
            "order_shown": ["b", "a"],
        }
    ]
    units = [{"id": "u", "pair_group_id": "g", "item_ids": ["a", "b"]}]
    assert canonicalize_labels(labels, units, "person") == [("g", "a", "b", "y")]
