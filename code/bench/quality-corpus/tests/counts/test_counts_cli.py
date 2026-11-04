from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "counts"
sys.path.insert(0, str(SCRIPT))
import count_items  # noqa: E402, RUF100 - test script path must be on sys.path first

LANGS = ("python",)


def pair(directory: Path, category: str, language: str = "python") -> None:
    directory.mkdir(parents=True, exist_ok=True)
    if category == "b":
        for variant in count_items.VARIANTS:
            (directory / f"{variant}.py").write_text("pass\n")
        payload = {
            "pairs": [
                {
                    "pair_id": f"pair-{i}",
                    "left": "sensible.py",
                    "right": f"{variant}.py",
                }
                for i, variant in enumerate(count_items.VARIANTS)
                if variant != "sensible"
            ]
        }
    else:
        (directory / "good.py").write_text("pass\n")
        (directory / "bad.py").write_text("pass\n")
        payload = {
            "left": "good.py",
            "right": "bad.py",
            "language": language,
            "category": category,
        }
        (directory / "manifest.toml").write_text(
            f'category = "{category}"\nlanguage = "{language}"\n'
        )
    (directory / "pair.json").write_text(json.dumps(payload))


def restricted_b(directory: Path, task: str, language: str = "python") -> None:
    directory.mkdir(parents=True)
    suffix = count_items.SUFFIX[language]
    for variant in count_items.VARIANTS:
        (directory / f"{variant}{suffix}").write_text("pass\n")
    pairs = [
        {
            "pair_id": f"pair-{index}",
            "left": f"sensible{suffix}",
            "right": f"{variant}{suffix}",
        }
        for index, variant in enumerate(count_items.VARIANTS)
        if variant != "sensible"
    ]
    (directory / "pair.json").write_text(
        json.dumps({"task": task, "language": language, "pairs": pairs})
    )


def fixture(tmp_path: Path) -> list[Path]:
    root = tmp_path / "items"
    for i in range(6):
        pair(root / "python" / "b" / f"small-{i}", "b")
    for task in ("order-quote", "clinic-booking", "shift-pay", "rental-quote"):
        pair(root / "python" / "b" / task, "b")
    for category, n in (("a", 6), ("b'", 2), ("c", 6), ("d", 4), ("e", 4)):
        for i in range(n):
            pair(root / "python" / "misc" / f"{category}-{i}", category)
    return [root, tmp_path / "restricted"]


def test_complete_tree_exits_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    roots = fixture(tmp_path)
    monkeypatch.setattr(count_items, "LANGUAGES", ("python",))
    monkeypatch.setattr(count_items, "toolchain", lambda _lang: True)
    monkeypatch.setattr(count_items, "ROOT", tmp_path)
    monkeypatch.setattr(count_items, "ITEMS", roots[0])
    (tmp_path / "code/bench/quality-corpus/taskbank").mkdir(parents=True)
    tiers = {
        "tiers": {
            "small": [f"small-{i}" for i in range(6)],
            "rich": ["order-quote", "clinic-booking", "shift-pay", "rental-quote"],
        }
    }
    (tmp_path / "code/bench/quality-corpus/taskbank/tiers.json").write_text(
        json.dumps(tiers)
    )
    (tmp_path / "code/bench/quality-corpus/taskbank/bank.json").write_text(
        json.dumps(
            {
                "tasks": [
                    {"id": "small-1", "idiom_tags": ["ownership"]},
                    {"id": "small-2", "idiom_tags": ["error-handling"]},
                ]
            }
        )
    )
    monkeypatch.setenv("VARDE_GOLDEN_RESTRICTED", str(roots[1]))
    assert count_items.main(["--check"]) == 0
    assert "complete" in capsys.readouterr().out


@pytest.mark.parametrize(
    "category",
    ["a", "b", "b'", "c", "d", "anchors", "idiom-heavy tasks", "toolchain missing"],
)
def test_each_gap_exits_one_and_is_listed(
    category: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(count_items, "LANGUAGES", ("python",))
    monkeypatch.setattr(count_items, "ROOT", tmp_path)
    taskbank = tmp_path / "code/bench/quality-corpus/taskbank"
    taskbank.mkdir(parents=True)
    (taskbank / "tiers.json").write_text(
        json.dumps({"tiers": {"small": [], "rich": []}})
    )
    (taskbank / "bank.json").write_text(json.dumps({"tasks": []}))
    counts = {
        "python": {
            "a": 6,
            "b_small": 6,
            "b_rich": 0,
            "bprime": 2,
            "c": 6,
            "d": 4,
            "anchors": 4,
            "idiom": 2,
        }
    }
    fields = {
        "a": ("a", 0),
        "b": ("b_small", 0),
        "b'": ("bprime", 0),
        "c": ("c", 0),
        "d": ("d", 0),
        "anchors": ("anchors", 0),
        "idiom-heavy tasks": ("idiom", 0),
    }
    if category in fields:
        field, value = fields[category]
        counts["python"][field] = value
    monkeypatch.setattr(count_items, "scan", lambda *_args: counts)
    monkeypatch.setattr(
        count_items, "toolchain", lambda _lang: category != "toolchain missing"
    )
    assert count_items.main(["--check"]) == 1
    assert category in capsys.readouterr().out


def test_usage_is_exit_two() -> None:
    with pytest.raises(SystemExit) as error:
        count_items.main([])
    assert error.value.code == 2


def test_restricted_store_override_is_scanned(tmp_path: Path) -> None:
    public, restricted = fixture(tmp_path)
    pair(restricted / "python" / "misc" / "extra", "a")
    counts = count_items.scan(
        [public, restricted],
        {f"small-{i}" for i in range(6)},
        {"order-quote", "clinic-booking", "shift-pay", "rental-quote"},
        set(),
    )
    assert counts["python"]["a"] == 7


def test_restricted_layout_classifies_b_by_pair_shape_and_task(tmp_path: Path) -> None:
    root = tmp_path / "restricted"
    restricted_b(
        root / "test-restricted" / "digest" / "scoreboard-python", "scoreboard"
    )
    restricted_b(
        root / "test-restricted" / "digest" / "order-quote-python", "order-quote"
    )
    counts = count_items.scan([root], {"scoreboard"}, {"order-quote"}, {"scoreboard"})
    assert counts["python"]["b_small"] == 1
    assert counts["python"]["b_rich"] == 1
    assert counts["python"]["idiom"] == 1


def test_restricted_misc_layout_keeps_anchor_and_structured_categories(
    tmp_path: Path,
) -> None:
    root = tmp_path / "restricted" / "test-restricted" / "digest"
    anchor = root / "anchor-queue-go"
    anchor.mkdir(parents=True)
    (anchor / "excellent.go").write_text("pass\n")
    (anchor / "poor.go").write_text("pass\n")
    (anchor / "pair.json").write_text(
        json.dumps({"left": "excellent.go", "right": "poor.go"})
    )
    (anchor / "manifest.toml").write_text('category = "e"\nlanguage = "go"\n')
    sample = root / "structured-booking-go"
    sample.mkdir()
    (sample / "good.go").write_text("pass\n")
    (sample / "bad.go").write_text("pass\n")
    (sample / "pair.json").write_text(
        json.dumps({"left": "good.go", "right": "bad.go"})
    )
    counts = count_items.scan([root.parent.parent.parent], set(), set(), set())
    assert counts["go"]["anchors"] == 1
    assert counts["go"]["a"] == 1


def test_missing_tier_registry_returns_usage_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(count_items, "ROOT", tmp_path)
    assert count_items.main(["--report"]) == 2
    assert "cannot read valid tier registry" in capsys.readouterr().err


def test_report_renderer_is_markdown_table() -> None:
    counts = {
        "python": {
            "a": 6,
            "b_small": 6,
            "b_rich": 0,
            "bprime": 2,
            "c": 6,
            "d": 4,
            "anchors": 2,
            "idiom": 2,
        }
    }
    assert "python | 6/6 | 6/6 | 0/4 |" in count_items.render_report(
        counts, {"python": []}
    )


def test_missing_toolchain_is_an_incomplete_gap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(count_items, "available_commands", lambda _suffix: None)
    assert not count_items.toolchain("python")
    counts = {
        "python": {
            "a": 6,
            "b_small": 6,
            "b_rich": 0,
            "bprime": 2,
            "c": 6,
            "d": 4,
            "anchors": 4,
            "idiom": 2,
        }
    }
    monkeypatch.setattr(count_items, "toolchain", lambda _lang: False)
    assert "toolchain missing" in count_items.gaps(counts, tmp_path)["python"]
