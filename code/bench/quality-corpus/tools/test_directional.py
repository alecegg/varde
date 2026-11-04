# ruff: noqa: S101
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import directional as dr


def fn(tokens, **kw):
    return {"tokens": tokens, "cognitive": 0, "fan_in": 2, "fan_out": 3, **kw}


def test_token_share_is_token_weighted():
    rows = [fn(30, cognitive=9), fn(10)]
    assert dr.token_share(rows, dr.predicate("cognitive", 5)) == pytest.approx(0.75)
    assert dr.token_share([], dr.predicate("cognitive", 5)) is None


def test_below_and_forwarder_predicates():
    tiny = fn(8, fan_in=1, fan_out=1)
    big_caller = fn(8, fan_in=3, fan_out=1)
    assert dr.predicate("tokens_short", 10)(tiny)
    assert dr.predicate("indirection", 10)(tiny)
    assert not dr.predicate("indirection", 10)(big_caller)
    assert not dr.predicate("indirection", 10)(fn(8, fan_in=1, fan_out=1, cognitive=1))


def test_best_threshold_maximises_sensitivity_at_ninety_specificity():
    good = {f"g{i}": [fn(10), fn(10, cognitive=3)] for i in range(10)}
    worse = {"deep": {"a": [fn(10), fn(10, cognitive=8)], "b": [fn(10)]}}
    best = dr.best_for(good, worse, "cognitive", "share")
    assert best["accepted"] >= 0.9
    assert best["sens"] == pytest.approx(0.5)
    assert dr.item_value(worse["deep"]["a"], "cognitive", "max", None) == 8


def test_max_form_only_for_higher_is_worse_signals():
    assert dr.forms_of("cognitive") == ("share", "max")
    assert dr.forms_of("indirection") == ("share",)


def test_curated_keeps_agreed_and_low_exceedance_proxies():
    heavy = [fn(500, cognitive=40)]
    light = [fn(20)]
    good = {"agreed:p": heavy, "proxy:a": light, "proxy:b": heavy, "proxy:c": light}
    kept = dr.curated_good(good)
    assert set(kept) == {"agreed:p", "proxy:a", "proxy:c"}


def test_lopo_tests_held_out_problem_with_train_cut():
    good = {f"agreed:{p}": [fn(10)] for p in "abc"}
    worse = {"deep": {p: [fn(10, cognitive=20)] for p in "abc"}}
    out = dr.lopo(good, worse, ["a", "b", "c"], keep_proxies=False)
    assert out["cognitive"]["sens"] == 1.0
    assert out["cognitive"]["held_out_accepted"] == 1.0


def test_uncaught_flags_types_without_a_caught_matched_signal():
    grid = {"add_params": {"params": 0.25, "tokens_long": 0.75}}
    info = dr.uncaught(grid)["add_params"]
    assert info["caught"] is False
    assert info["any_best"] == ("tokens_long", 0.75)
