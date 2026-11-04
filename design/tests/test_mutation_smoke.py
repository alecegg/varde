"""Mutation harness smoke: deterministic generation, every defect family fires."""

# ruff: noqa: S311  (seeded sampling for reproducibility, not cryptography)

import importlib.util
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

CORPUS = Path(__file__).resolve().parents[1] / "corpus"
sys.path.insert(0, str(CORPUS))
import design_mutations  # noqa: E402
import mutate  # noqa: E402

SEED = 7
DEFECTS = [f for f in design_mutations.FAMILIES if f.kind == "defect"]
RENDER_OK = importlib.util.find_spec("playwright") is not None


def _bases() -> dict[str, str]:
    bases = mutate.load_bases(
        mutate.json.loads((CORPUS / "manifest.json").read_text()), None
    )
    return {
        k: v
        for k, v in bases.items()
        if k.startswith("synthetic/pages/") or k.endswith("/clean.html")
    }


def _eligible(bases: dict[str, str]) -> dict[str, set[str]]:
    rules = {f.rule for f in design_mutations.FAMILIES}
    return {
        rule: {
            name
            for name in bases
            if rule == "*" or name.endswith(("/clean.html", "pages/good-docs.html"))
        }
        for rule in rules
    }


def test_generation_is_deterministic():
    bases = _bases()
    eligible = _eligible(bases)
    first = mutate.generate(design_mutations.FAMILIES, bases, eligible, 2, SEED)
    second = mutate.generate(design_mutations.FAMILIES, bases, eligible, 2, SEED)
    other = mutate.generate(design_mutations.FAMILIES, bases, eligible, 2, SEED + 1)
    assert mutate.digest(first) == mutate.digest(second)
    assert mutate.digest(first) != mutate.digest(other)


def test_contrast_ratios_are_on_the_right_side():
    import random

    rng = random.Random(1)
    for low, high in ((3.0, 4.4), (1.8, 2.9), (4.55, 4.8), (3.05, 3.3)):
        color = design_mutations.gray_hex(low, high, rng)
        assert color is not None
        assert low <= design_mutations.ratio_on_white(int(color[1:3], 16)) <= high


def _run_defect(
    family: design_mutations.Family, bases: dict[str, str], tmp_path: Path
) -> bool:
    """True when the mutation fires its rule on at least one of three bases."""
    mutants = mutate.generate((family,), bases, _eligible(bases), 3, SEED)
    for i, mutant in enumerate(mutants):
        path = tmp_path / f"{family.name}-{i}.html"
        path.write_text(mutant.html, encoding="utf-8")
        hits = mutate.rules_hit(
            mutate.check_html(path, static_only=not family.rendered)
        )
        if hits.get(family.rule):
            return True
    return False


def test_every_defect_family_fires_its_rule(tmp_path):
    families = [f for f in DEFECTS if RENDER_OK or not f.rendered]
    bases = _bases()
    with ThreadPoolExecutor(4) as pool:
        fired = list(pool.map(lambda f: _run_defect(f, bases, tmp_path), families))
    missed = [f.name for f, ok in zip(families, fired, strict=True) if not ok]
    assert not missed, f"no base fired for: {missed}"
