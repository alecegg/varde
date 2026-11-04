import json
from collections import Counter
from pathlib import Path

from tools.splits import lock_hash

ROOT = Path(__file__).resolve().parents[2]
BANK = ROOT / "taskbank" / "bank.json"
AUXILIARY = ROOT / "taskbank" / "aux-tasks.json"
LOCK = ROOT / "tools" / "splits.lock"
TIERS = ROOT / "taskbank" / "tiers.json"


def read_json(path: Path) -> dict:
    return json.loads(path.read_text())


def test_bank_defines_pairable_cases_and_complete_language_subsets() -> None:
    bank = read_json(BANK)
    tasks = bank["tasks"]
    by_id = {task["id"]: task for task in tasks}
    languages = bank["languages"]

    assert len(tasks) == 10
    assert len(by_id) == 10
    assert list(by_id)[:2] == ["price-order", "shipping-quote"]
    usage = Counter(
        task_id for subset in bank["language_subsets"].values() for task_id in subset
    )
    assert set(bank["language_subsets"]) == set(languages)
    assert all(
        len(subset) == 6 and len(set(subset)) == 6
        for subset in bank["language_subsets"].values()
    )
    assert set(usage) == set(by_id)
    assert min(usage.values()) >= 4

    meaningful_idiom_tags = {
        "ceremony",
        "decorators",
        "error-handling",
        "LINQ",
        "ownership-lifetimes",
        "templates",
    }
    idiom_heavy = {
        task["id"]
        for task in tasks
        if meaningful_idiom_tags.intersection(task["idiom_tags"])
    }
    assert len(idiom_heavy) >= 4
    assert all(
        len(idiom_heavy.intersection(subset)) >= 2
        for subset in bank["language_subsets"].values()
    )
    for task in tasks:
        assert task["pair_group"] == task["id"]
        assert task["behaviour"].strip() == task["behaviour"]
        assert "\n" not in task["behaviour"]
        assert task["input_domain"]
        assert isinstance(task["over_comfort_monolith"], bool)
        assert len(task["cases"]) >= 10
        assert all("input" in case and "expected" in case for case in task["cases"])


def test_reviewed_edge_cases_have_hand_checked_outputs() -> None:
    tasks = {task["id"]: task for task in read_json(BANK)["tasks"]}

    def assert_case(task_id: str, input_value: object, expected: object) -> None:
        cases = tasks[task_id]["cases"]
        assert {"input": input_value, "expected": expected} in cases

    assert_case(
        "invoice-aging",
        [{"id": "A", "days_overdue": 1, "balance": 100}],
        {
            "invoices": [{"id": "A", "bucket": "1-30", "fee": 2}],
            "totals": {"current": 0, "1-30": 100, "31-60": 0, "61-90": 0, "over-90": 0},
        },
    )
    assert_case(
        "invoice-aging",
        [{"id": "B", "days_overdue": -2, "balance": 40}],
        {
            "invoices": [{"id": "B", "bucket": "current", "fee": 0}],
            "totals": {"current": 40, "1-30": 0, "31-60": 0, "61-90": 0, "over-90": 0},
        },
    )
    assert_case(
        "retry-policy",
        {"attempts": 2, "initial": 1, "multiplier": 0.5, "maximum": 10},
        {"error": "invalid_policy"},
    )
    assert_case(
        "csv-summary",
        [{"product": "", "quantity": 1, "unit_price": 2}],
        {"error": "invalid_row"},
    )
    assert_case(
        "text-template",
        {"template": "{{name}} {name}", "values": {"name": "Ada"}},
        "{{name}} Ada",
    )
    assert_case(
        "inventory-adjustment",
        {"stock": {"A": 1}, "movements": {"UNKNOWN": -1}},
        {"error": "insufficient_stock"},
    )
    assert_case(
        "inventory-adjustment",
        {"stock": {"Z": 2, "C": 1}, "movements": {"C": 2}},
        [{"item": "C", "quantity": 3}, {"item": "Z", "quantity": 2}],
    )
    assert_case(
        "reservation-calendar",
        {
            "slots": [{"id": "A", "start": 540, "end": 600}],
            "reserved": [{"start": 570, "end": 630}],
        },
        [],
    )
    assert_case(
        "scoreboard",
        {
            "teams": ["A", "B", "C"],
            "matches": [
                {"home": "A", "away": "B", "home_score": 0, "away_score": 2},
                {"home": "B", "away": "C", "home_score": 1, "away_score": 1},
                {"home": "C", "away": "A", "home_score": 3, "away_score": 0},
            ],
        },
        [
            {
                "team": "C",
                "played": 2,
                "wins": 1,
                "draws": 1,
                "losses": 0,
                "points": 4,
                "scored": 4,
                "conceded": 1,
                "difference": 3,
            },
            {
                "team": "B",
                "played": 2,
                "wins": 1,
                "draws": 1,
                "losses": 0,
                "points": 4,
                "scored": 3,
                "conceded": 1,
                "difference": 2,
            },
            {
                "team": "A",
                "played": 2,
                "wins": 0,
                "draws": 0,
                "losses": 2,
                "points": 0,
                "scored": 0,
                "conceded": 5,
                "difference": -5,
            },
        ],
    )


def test_split_lock_covers_bank_auxiliary_and_rich_tasks() -> None:
    bank = read_json(BANK)
    auxiliary = read_json(AUXILIARY)["tasks"]
    aux_ids = {task["id"] for task in auxiliary}
    assert len(auxiliary) == 8
    assert len(aux_ids) == 8
    assert sum(task["category"] == "a" for task in auxiliary) == 6
    assert sum(task["category"] == "anchor" for task in auxiliary) == 2
    for task in auxiliary:
        assert task["pair_group"] == task["id"]
        assert task["behaviour"] and "\n" not in task["behaviour"]
        assert task["cases"]
        assert all("input" in case and "expected" in case for case in task["cases"])

    rich_ids = set(read_json(TIERS)["tiers"]["rich"])
    expected_ids = {task["id"] for task in bank["tasks"]} | aux_ids | rich_ids
    payload = read_json(LOCK)
    assert set(payload["assignments"]) == expected_ids
    assert payload["sha256"] == lock_hash(payload["assignments"])
    assert payload["assignments"]["clinic-booking"] == "dev"
    assert (
        payload["assignments"]["clinic-booking"]
        == payload["assignments"]["order-quote"]
    )
