"""The pinned snapshots and the fixture calibration behave as the gate suite expects."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import file_scores, score_repo
from gate_calibration import (
    CALIBRATION_ID,
    CALIBRATION_PATH,
    GATED_LANGUAGES,
    KNOWN_STATES,
    PANEL_VALIDATED,
    language_gating_available,
    language_gating_state,
    load_gate_test_calibration,
)
from gate_snapshots import LANGUAGES, SNAPSHOTS
from varde_code.quality_pass.pass_ import read_facts, read_measures
from varde_code.quality_score.calibration import load_calibration

MICRO = 1_000_000
NEAR_X_TOLERANCE = 3 * MICRO
PLACEHOLDER = (
    Path(__file__).parents[2]
    / "src/varde_code/quality_score/calibration/placeholder.toml"
)


def test_snapshots_cover_the_three_languages_with_tsx():
    assert LANGUAGES == ("python", "typescript", "csharp")
    assert "tsx" in SNAPSHOTS["typescript"].roles
    assert SNAPSHOTS["typescript"].path("tsx").endswith(".tsx")
    for snapshot in SNAPSHOTS.values():
        for role in ("debt", "clean", "near_x", "exempt", "floor_exempt"):
            assert snapshot.path(role) in snapshot.files


def test_every_snapshot_scores_and_roles_sit_on_the_right_side_of_the_thresholds(
    snapshot, isolated_env, gate_calibration
):
    scope = score_repo(isolated_env, snapshot.files, gate_calibration)
    scored = file_scores(scope)
    thresholds = gate_calibration.languages[snapshot.language]
    x, y = thresholds.threshold_x, thresholds.parameters["Y"]

    assert scope.score is not None
    assert set(scored) == set(snapshot.files)
    assert all(f.excluded is None and not f.not_applicable for f in scope.files)
    assert scored[snapshot.path("debt")].gate_score < y
    assert scored[snapshot.path("clean")].gate_score > x
    near = scored[snapshot.path("near_x")].gate_score
    assert abs(near - x) <= NEAR_X_TOLERANCE
    assert scored[snapshot.path("floor_exempt")].exempt_from_floor
    exempt = scored[snapshot.path("exempt")]
    assert exempt.exempt_from_floor or all(fn.exempt_role for fn in exempt.functions)


def test_tsx_file_scores_under_the_fixture_calibration(isolated_env, gate_calibration):
    snapshot = SNAPSHOTS["typescript"]
    scope = score_repo(isolated_env, snapshot.files, gate_calibration)
    tsx = file_scores(scope)[snapshot.path("tsx")]

    assert tsx.language == "tsx"
    assert tsx.tokens > 0
    assert not tsx.not_applicable


def test_tsx_is_unscored_when_the_calibration_has_no_tsx_language(
    isolated_env,
):
    snapshot = SNAPSHOTS["typescript"]
    scope = score_repo(isolated_env, snapshot.files, load_calibration(PLACEHOLDER))
    tsx = file_scores(scope)[snapshot.path("tsx")]

    assert tsx.not_applicable


def test_direct_call_edge_has_the_recorded_resolver_verdict(
    snapshot, isolated_env, gate_calibration
):
    score_repo(isolated_env, snapshot.files, gate_calibration)
    coverage = {m["path"]: m["call_coverage"] for m in read_measures(isolated_env)}[
        snapshot.edge_caller
    ]

    assert coverage[snapshot.edge_verdict] == 1
    assert sum(coverage.values()) == 1


def test_generated_marker_and_long_comment_variants_still_score(
    snapshot, isolated_env, gate_calibration
):
    files = dict(snapshot.files)
    debt = snapshot.path("debt")
    mid = snapshot.path("near_x")
    files[debt] = snapshot.with_generated_marker(files[debt])
    files[mid] = snapshot.with_long_comment(files[mid])
    scored = file_scores(score_repo(isolated_env, files, gate_calibration))

    assert scored[debt].debt > 0
    assert (
        scored[debt].gate_score
        < gate_calibration.languages[snapshot.language].parameters["Y"]
    )
    assert scored[mid].tokens > 0


def test_syntax_error_variant_is_reported_by_the_parser(
    snapshot, isolated_env, gate_calibration
):
    files = dict(snapshot.files)
    files[snapshot.path("clean")] = snapshot.syntax_error
    score_repo(isolated_env, files, gate_calibration)
    facts = {f["path"]: f for f in read_facts(isolated_env)}

    assert "parse contains errors" in facts[snapshot.path("clean")]["diagnostics"]


@pytest.mark.parametrize("tiny", [True, False])
def test_filler_generators_make_distinct_scored_files(
    snapshot, tiny, isolated_env, gate_calibration
):
    filler = snapshot.filler_files(3, tiny=tiny)
    scope = score_repo(isolated_env, filler, gate_calibration)

    assert len(filler) == 3
    assert all(path.endswith("." + snapshot.ext) for path in filler)
    assert len(set(filler.values())) == 3
    assert {f.path for f in scope.files} == set(filler)
    assert all(f.tokens > 0 for f in scope.files)
    large = [f for f in scope.files if f.tokens > 150]
    assert bool(large) is (not tiny)


def test_fixture_calibration_loads_and_marks_languages_panel_validated():
    calibration = load_gate_test_calibration()

    assert calibration.id == CALIBRATION_ID == "gate-test-cal"
    assert calibration.validated is True
    for language in (*GATED_LANGUAGES, "tsx"):
        assert language_gating_state(calibration, language) == PANEL_VALIDATED
        assert language_gating_available(calibration, language)


def test_placeholder_calibration_is_report_only_for_every_language():
    calibration = load_calibration(PLACEHOLDER)

    for language in calibration.languages:
        assert not language_gating_available(calibration, language)


def test_unknown_language_or_state_raises(tmp_path):
    calibration = load_gate_test_calibration()
    with pytest.raises(KeyError):
        language_gating_state(calibration, "cobol")

    broken = tmp_path / "broken.toml"
    broken.write_text(
        CALIBRATION_PATH.read_text(encoding="utf-8").replace(
            'state = "panel-validated"', 'state = "maybe"', 1
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unknown language validation state 'maybe'"):
        language_gating_state(load_calibration(broken), "python")

    assert {"panel-validated", "report-only"} == KNOWN_STATES
