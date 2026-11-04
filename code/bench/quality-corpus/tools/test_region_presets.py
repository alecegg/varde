# ruff: noqa: S101
import sys
import tomllib
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import baseline_dominance as bd
import baseline_region as br
import region_presets as rp
from varde_code.quality_score.calibration import load_calibration

CAL_1 = rp.PLACEHOLDER.parent / "cal-1.toml"
PLACEHOLDER = tomllib.loads(rp.PLACEHOLDER.read_text())
CORPUS = {m: [0] * 50 + [3 * i for i in range(1, 51)] for m in br.FITTED}
V1 = ("python", "typescript", "csharp")


def synthetic(language: str, agreed: bool) -> rp.LanguageInputs:
    records = bd.reference_records("agreed", language)
    examples = []
    if agreed:
        for problem in sorted((bd.REFERENCE_ROOT / "agreed").iterdir()):
            directory = problem / language
            if directory.is_dir():
                measured = rp.bm.raw_measure_directory(directory, language)
                examples.append(
                    [{m: r.get(m) for m in rp.MEASURES} for r in measured["functions"]]
                )
    return rp.LanguageInputs(CORPUS, 10, examples, records if agreed else [], records)


@pytest.fixture(scope="module")
def inputs():
    return {
        "python": synthetic("python", True),
        "typescript": synthetic("typescript", False),
        "csharp": synthetic("csharp", False),
    }


@pytest.fixture(scope="module")
def built(inputs):
    return rp.build(inputs)


def test_committed_cal_1_loads_with_report_only_v1_languages():
    cal = load_calibration(CAL_1)
    assert cal.id == "cal-2"
    assert not cal.validated
    for entry in cal.languages.values():
        assert entry.state == "report-only"
        assert entry.validation["reason"]
        assert entry.validation["provenance"]
    assert "dominance" in cal.global_strengths


def test_committed_cal_1_gates_are_ordered_and_v1_languages_have_p0():
    cal = load_calibration(CAL_1)
    for language in V1:
        params = cal.languages[language].parameters
        assert params["X"] > params["Y"] > 0
        assert "p0" in params
        # cap = Y * 12.5 / 38, within one hundredth (values are in micro-units)
        assert abs(params["cap"] * 380 - params["Y"] * 125) <= 380 * 10_000


def test_committed_cal_1_keeps_tuned_strengths_and_copies_other_languages():
    cal = load_calibration(CAL_1)
    base = load_calibration(rp.PLACEHOLDER)
    for name in ("A", "wL", "w", "structure"):
        assert cal.global_strengths[name] == base.global_strengths[name]
    for language in ("java", "go", "rust", "cpp"):
        shipped = cal.languages[language].parameters
        assert shipped == base.languages[language].parameters | {
            key: shipped[key] for key in rp.SHADOW_KEYS
        }
    assert cal.limits == base.limits | {"measures": cal.limits["measures"]}


def test_language_thresholds_equal_t11_output_on_their_inputs(built, inputs):
    cal = tomllib.loads(built.text)
    for language in V1:
        item = inputs[language]
        base = PLACEHOLDER["language"][language]
        default = rp.default_region(base, item.corpus)
        expected = br.calibrate(default, list(item.examples), item.corpus)
        for key, value in expected.items():
            assert cal["language"][language][key] == value


def test_k0_preset_equals_corpus_quantile_defaults(inputs):
    base = PLACEHOLDER["language"]["typescript"]
    item = inputs["typescript"]
    region = rp.language_region(base, item)
    assert region == rp.default_region(base, item.corpus)
    for measure, key in br.FITTED.items():
        assert region[key] == br.nearest_rank(CORPUS[measure], rp.DEFAULT_PERCENTILE)


def test_gates_keep_installed_ratios_and_order():
    x, y, cap = rp.gate_tenths(76.24)
    assert (x, y) == (762, 467)
    assert cap == 467 * 125 // 38
    assert x > y > 0
    with pytest.raises(ValueError):
        rp.gate_tenths(0.0)


def test_x_is_floored_so_the_line_itself_stays_accepted():
    assert rp.tenths(87.4) == 874
    assert rp.tenths(87.49999) == 874


def test_agreed_python_samples_score_at_or_above_x(built):
    assert built.agreed_scores
    x = built.x_tenths["python"]
    assert all(rp.tenths(score) >= x for score in built.agreed_scores)


def test_rebuild_is_byte_identical(built, inputs):
    assert rp.build(inputs).text == built.text


def test_built_text_loads_through_the_unchanged_loader(built, tmp_path):
    path = tmp_path / "cal.toml"
    path.write_text(built.text)
    cal = load_calibration(path)
    assert set(cal.languages) == set(PLACEHOLDER["language"])
    assert cal.languages["java"].parameters["X"] == 62_000_000


def test_candidate_path_filters_tests_and_other_languages():
    assert rp.candidate_path("src/app/service.ts", "typescript")
    assert not rp.candidate_path("src/app/service.test.ts", "typescript")
    assert not rp.candidate_path("src/Tests/Service.cs", "csharp")
    assert not rp.candidate_path("src/service.py", "csharp")
    assert not rp.candidate_path("node_modules/pkg/index.ts", "typescript")
