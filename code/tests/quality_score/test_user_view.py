import math

import pytest
from varde_code.quality_score.breakdown import COMPONENTS
from varde_code.quality_score.user_text import render_text
from varde_code.quality_score.user_view import NO_CODE_NOTICE, user_view, with_debug

WHITELIST = {
    "score",
    "calibration",
    "categories",
    "tests_passed",
    "notice",
    "refactor",
    "monolith",
    "delegation",
    "fragmentation",
}
CATEGORY_KEYS = {"name", "points_lost", "hint"}
MICRO = 1_000_000


def _payload(numerator, denominator=1, tokens=100):
    return {
        "calibration": "placeholder; not validated",
        "score": {"numerator": numerator, "denominator": denominator},
        "tokens": tokens,
        "debt": 999_999_937,
    }


def _entry(points_lost=0, name="names"):
    return {
        "name": name,
        "debt": 999_999_937,
        "points_lost": points_lost,
        "worst_offenders": [{"debt": 5}],
        "hint": "do better",
    }


def _numbers(value):
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _numbers(item)
    elif isinstance(value, list):
        for item in value:
            yield from _numbers(item)


def test_clamps_just_above_100_and_negative_zero():
    assert user_view(_payload(int(100.04 * MICRO)), [])["score"] == 100.0
    result = user_view(_payload(-0.0), [])["score"]
    assert result == 0.0
    assert math.copysign(1, result) == 1


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_non_finite_raises(bad):
    with pytest.raises(ValueError):
        user_view(_payload(bad), [])
    with pytest.raises(ValueError):
        user_view(_payload(50 * MICRO), [_entry(bad)])


@pytest.mark.parametrize("bad", [150 * MICRO, -5 * MICRO])
def test_out_of_range_raises(bad):
    with pytest.raises(ValueError):
        user_view(_payload(bad), [])


@pytest.mark.parametrize(
    "payload",
    [
        {**_payload(100 * MICRO), "tokens": 0},
        {**_payload(100 * MICRO), "score": None},
    ],
)
def test_no_scorable_code_is_null_with_notice(payload):
    view = user_view(payload, [])
    assert view["score"] is None
    assert view["notice"] == NO_CODE_NOTICE


def test_half_up_rounding_to_one_decimal():
    assert user_view(_payload(50_050_000), [])["score"] == 50.1
    assert user_view(_payload(50_049_999), [])["score"] == 50.0
    assert user_view(_payload(0), [])["score"] == 0.0
    assert user_view(_payload(100 * MICRO), [])["score"] == 100.0


def test_output_is_whitelisted_and_in_range():
    view = user_view(_payload(73_456_789, 2), [_entry(12_345_678), _entry(0, "x")])
    assert set(view) <= WHITELIST
    assert [set(c) for c in view["categories"]] == [CATEGORY_KEYS]
    assert view["categories"][0]["points_lost"] == 12.3
    assert all(0 <= n <= 100 for n in _numbers(view))
    assert "999999937" not in repr(view)


def test_with_debug_adds_raw_fields():
    raw = _payload(50 * MICRO)
    assert with_debug(user_view(raw, []), raw)["debug"] == raw


def _target(**overrides):
    base = {
        "id": "src/a.py::Owner.run#1",
        "path": "src/a.py",
        "line": 140,
        "share": 523_000,
        "now": 11,
        "target": 10,
        "tokens": 140,
        "complexity": 11,
        "issues": [],
    }
    return {**base, **overrides}


def _guided(name, **overrides):
    return {**_entry(5_000_000, name), "fix_targets": [_target(**overrides)]}


def test_category_gets_goal_and_worst_function_with_action():
    view = user_view(_payload(80 * MICRO), [_guided("cognitive")])
    category = view["categories"][0]
    assert (
        category["goal"] == "keep cognitive complexity at or below 10 in each function"
    )
    assert category["worst"] == [
        {
            "function": "Owner.run",
            "file": "src/a.py",
            "line": 140,
            "loss_share": 52,
            "now": 11,
            "target": 10,
            "action": category["worst"][0]["action"],
        }
    ]
    assert "`Owner.run`" in category["worst"][0]["action"]


def test_long_side_action_names_tokens_and_complexity():
    view = user_view(_payload(80 * MICRO), [_guided("long_side", now=140, target=96)])
    action = view["categories"][0]["worst"][0]["action"]
    assert action.startswith("split `Owner.run` (140 tokens, complexity 11)")
    assert "at most 96 tokens" in action


def test_names_action_lists_issues_and_params_action_gives_limit():
    names = user_view(
        _payload(80 * MICRO),
        [_guided("names", now=2, target=0, issues=["abbreviation", "vague"])],
    )
    assert "(abbreviation, vague)" in names["categories"][0]["worst"][0]["action"]
    params = user_view(_payload(80 * MICRO), [_guided("params", now=6, target=3)])
    assert (
        "from 6 to at most 3 parameters"
        in params["categories"][0]["worst"][0]["action"]
    )


def test_file_level_category_names_the_file_without_now_or_target():
    target = _target(id="src/a.py", line=None, now=None, target=None)
    entry = {**_entry(5_000_000, "fragmentation"), "fix_targets": [target]}
    worst = user_view(_payload(80 * MICRO), [entry])["categories"][0]["worst"][0]
    assert worst == {
        "function": "src/a.py",
        "file": "src/a.py",
        "loss_share": 52,
        "action": "inline tiny single-caller helpers in `src/a.py`",
    }


def test_no_fix_targets_leaves_category_keys_unchanged():
    view = user_view(_payload(80 * MICRO), [_entry(5_000_000)])
    assert set(view["categories"][0]) == CATEGORY_KEYS


def test_guidance_has_no_raw_scoring_units():
    view = user_view(_payload(80 * MICRO), [_guided("cognitive")])
    category = view["categories"][0]
    assert set(category) == CATEGORY_KEYS | {"goal", "worst"}
    assert all(0 <= item["loss_share"] <= 100 for item in category["worst"])
    assert "523000" not in repr(view)


def test_text_render_lists_goal_and_actions_per_category():
    view = user_view(_payload(80 * MICRO), [_guided("cognitive")])
    text = render_text(view)
    assert text.splitlines()[0] == (
        "Score: 80.0 / 100 (placeholder; not validated / report-only)"
    )
    assert "cognitive: -5.0 points. keep cognitive complexity at or below 10" in text
    assert "[src/a.py:140, 52% of loss]" in text


def test_text_render_of_no_code_is_the_notice():
    view = user_view({**_payload(100 * MICRO), "tokens": 0}, [])
    assert render_text(view) == NO_CODE_NOTICE + "\n"


def test_within_limit_target_says_no_function_is_over_the_limit():
    entry = _guided("cognitive", now=5, target=10, within_limit=True, spread=4)
    action = user_view(_payload(80 * MICRO), [entry])["categories"][0]["worst"][0][
        "action"
    ]
    assert action == (
        "no function is over the limit; the loss is spread across 4 functions "
        "(largest: `Owner.run`, 5 cognitive complexity, limit 10)"
    )


def test_within_limit_names_target_does_not_raise():
    entry = _guided("names", now=0, target=0, issues=[], within_limit=True, spread=2)
    worst = user_view(_payload(80 * MICRO), [entry])["categories"][0]["worst"][0]
    assert "no function is over the limit" in worst["action"]


@pytest.mark.parametrize("name", COMPONENTS)
def test_every_scorer_category_renders_beyond_and_within_limit(name):
    file_level = name in {
        "fragmentation",
        "file_size",
        "import_fan_out",
        "file_overhead",
        "module_fragmentation",
    }
    if file_level:
        target = _target(line=None, now=None, target=None)
        entries = [{**_entry(5_000_000, name), "fix_targets": [target]}]
    else:
        entries = [
            _guided(name),
            _guided(name, within_limit=True, spread=3),
        ]
    for entry in entries:
        view = user_view(_payload(80 * MICRO), [entry])
        assert view["categories"][0]["worst"][0]["action"]


def test_monolith_and_refactor_fields_are_carried_and_rendered():
    monolith = {
        "function": "run",
        "file": "a.py",
        "line": 1,
        "share_percent": 90,
        "action": "split it",
    }
    refactor = {"needs_refactor": False, "worse_than_percent": 5, "message": "good"}
    view = user_view(_payload(80 * MICRO), [], monolith=monolith, refactor=refactor)
    assert set(view) <= WHITELIST
    assert view["monolith"] == monolith
    assert "Advisory (score unchanged): split it" in render_text(view)
    assert "monolith" not in user_view(_payload(80 * MICRO), [])


def test_file_advisories_are_optional_carried_and_rendered():
    delegation = {"file": "a.py", "share_percent": 40, "action": "inline wrappers"}
    fragmentation = {"file": "a.py", "median_tokens": 12, "action": "merge tiny"}
    view = user_view(
        _payload(80 * MICRO),
        [],
        file_advisories={"delegation": delegation, "fragmentation": fragmentation},
    )
    assert set(view) <= WHITELIST
    assert view["delegation"] == delegation
    text = render_text(view)
    assert "Advisory (score unchanged): inline wrappers" in text
    assert "Advisory (score unchanged): merge tiny" in text
    bare = user_view(_payload(80 * MICRO), [])
    assert "delegation" not in bare
    assert "fragmentation" not in bare


def test_text_marks_unvalidated_score_report_only_and_keeps_n_with_percentages():
    view = user_view(
        _payload(87_400_000),
        [],
        refactor={
            "message": "worse than 40% of your reference (n=30): at or above p10 (61.0)"
        },
    )
    text = render_text(view)
    assert "not validated / report-only" in text
    for line in text.splitlines():
        if (
            "good enough" in line
            or "high quality" in line
            or "% of your reference" in line
        ):
            assert "n=" in line
