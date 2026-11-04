import pytest
from varde_design.css_rules import check_css
from varde_design.motion_rules import (
    duration_ms,
    is_layout_prop,
    overshoots,
    split_commas,
    transition_durations,
)
from varde_design.settings import Settings

CORE = Settings(profile="opinion")  # S10 is an opinion rule


def s10(css: str, settings: Settings = CORE) -> list[tuple[str, str]]:
    return [
        (f.message, f.severity)
        for f in check_css(css, "a.css", settings)
        if f.id == "S10"
    ]


def test_duration_ms_units() -> None:
    assert duration_ms("200ms") == 200 and duration_ms("0.3s") == pytest.approx(300)
    assert duration_ms(".5S") == pytest.approx(500) and duration_ms("ease") is None


def test_transition_durations_use_first_time_per_segment() -> None:
    value = "opacity 200ms ease 1s, transform 0.4s cubic-bezier(0.1, 0.2, 0.3, 0.4)"
    assert transition_durations(value) == [200, pytest.approx(400)]
    assert (
        split_commas("a, b(1, 2), c") == ["a", "b(1, 2)", "c"]
        and split_commas("") == []
    )


def test_transition_all_fails_in_both_forms() -> None:
    assert s10("a { transition: all 100ms }") == [
        ("transition: all; list the properties explicitly", "fail")
    ]
    assert [s for _, s in s10("a { transition-property: all }")] == ["fail"]
    assert s10("a { transition: opacity 100ms, transform 100ms }") == []


def test_duration_boundary_uses_max_motion_ms() -> None:
    assert s10("a { transition: opacity 300ms }") == []
    assert s10("a { transition: opacity 301ms }") == [
        ("Transition of 301ms exceeds 300ms", "warn")
    ]
    assert s10("a { transition: opacity 301ms }", Settings(max_motion_ms=400)) == []
    assert s10("a { transition: opacity 0.5s }")[0][1] == "warn"


def test_layout_property_animated_warns_and_transform_is_clean() -> None:
    assert s10("a { transition: width 100ms }") == [
        ("Transition animates layout property width", "warn")
    ]
    assert [s for _, s in s10("a { transition-property: margin-left, opacity }")] == [
        "warn"
    ]
    assert s10("a { transition: transform 100ms, opacity 100ms }") == []
    assert is_layout_prop("margin-left") and not is_layout_prop("max-widthx")


@pytest.mark.parametrize(
    ("value", "count"),
    [
        ("cubic-bezier(0.34, 1.56, 0.64, 1)", 1),
        ("cubic-bezier(0.2, -0.06, 0.2, 1)", 1),
        ("cubic-bezier(0.2, 1.05, 0.2, -0.05)", 0),
        ("cubic-bezier(0.16, 1, 0.3, 1)", 0),
        ("cubic-bezier(a, b)", 0),
    ],
)
def test_overshoots_boundary(value: str, count: int) -> None:
    assert len(overshoots(value)) == count


def test_overshoot_easing_fails_in_transition_and_animation() -> None:
    bad = "cubic-bezier(0.34, 1.56, 0.64, 1)"
    assert s10(f"a {{ transition: opacity 100ms {bad} }}") == [
        (f"Overshoot easing {bad}", "fail")
    ]
    assert [s for _, s in s10(f"a {{ animation: pop 1s {bad} }}")] == ["fail"]
    assert s10("a { color: red; width: 1px }") == []


def test_hero_height_in_vh_warns_but_dvh_and_non_hero_are_clean() -> None:
    assert s10(".hero { min-height: 100vh }") == [
        ("Hero min-height in vh; use dvh or svh", "warn")
    ]
    assert s10(".hero { height: 100dvh }") == []
    assert s10(".card { height: 100vh }") == []
