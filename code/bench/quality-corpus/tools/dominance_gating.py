"""Bench candidates that gate the dominance term by the function's own badness.

P+D2 (p0=2, dominance k=2) multiplies a function's debt by
``k * max(0, 2*share - 1)``, share = function tokens / file tokens, so a small
tidy single function is penalised as hard as a real monolith. These candidates
multiply that term by a gate in [0, 1] derived from the function itself or the
file. Pure functions over a ``Prepared`` record; no model call.

Pre-registered candidates (fixed before the first run; p0=2 for all):

* G1 hard gate: share term only when tokens > Phi or cognitive > c0.
* G2 ramp: gate = min(1, max(0, tokens/Phi - 1, cognitive/c0 - 1)), i.e. 0 at
  the comfort limit and 1 at twice the limit (proportional to the excess).
* G3 size fade: gate = min(1, file tokens / N), N = 25th percentile of the good
  files' token counts.
* G4 own-cost rank: gate = share of good-set functions whose own gated debt is
  at or below this function's (undiluted cost rank).
* G5 G2 x G3.
* G6 G2 with k=4 (compensates for the attenuation).
"""

from __future__ import annotations

import bisect
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
import score_variants as sv
import scorer_candidates as sc
from varde_code.quality_score.calibration import Calibration
from varde_code.quality_score.scoring import score_scope


@dataclass(frozen=True)
class Fn:
    tokens: int
    cognitive: int
    debt: int  # weighted, gated own debt in micro-units


@dataclass(frozen=True)
class Prepared:
    file_tokens: int
    base_debt: int
    functions: tuple[Fn, ...]


@dataclass(frozen=True)
class Context:
    """File-independent numbers a gate may read."""

    phi: float
    c0: float
    size_n: float
    good_debts: Sequence[int]  # sorted own debts of the good set's functions


Gate = Callable[[Fn, int, Context], float]


def prepare(record: Mapping[str, Any], base: Calibration, p0: int = 2) -> Prepared:
    gated = sv.gated_record(record, "gated")
    file = score_scope([gated], sc.with_p0(base, p0)).files[0]
    low = bool(file.low_structure_confidence)
    spec = sc.Spec("prep")
    debts = sc.function_debts(file.functions, base.global_strengths, spec, low)
    meta = {f.get("id"): f for f in gated["functions"]}
    fns = tuple(
        Fn(
            meta[fid].get("tokens") or 0,
            meta[fid].get("cognitive") or 0,
            debt,
        )
        for fid, debt in debts.items()
        if fid in meta
    )
    base_debt = sc.gate_debt(dict(file.components), low)
    return Prepared(file.tokens, base_debt, fns)


def share_excess(tokens: int, file_tokens: int) -> float:
    return max(0.0, 2 * tokens / max(1, file_tokens) - 1)


def comfort_excess(fn: Fn, ctx: Context) -> float:
    return max(0.0, fn.tokens / ctx.phi - 1, fn.cognitive / ctx.c0 - 1)


def gate_none(fn: Fn, file_tokens: int, ctx: Context) -> float:
    return 1.0


def gate_hard(fn: Fn, file_tokens: int, ctx: Context) -> float:
    return float(fn.tokens > ctx.phi or fn.cognitive > ctx.c0)


def gate_ramp(fn: Fn, file_tokens: int, ctx: Context) -> float:
    return min(1.0, comfort_excess(fn, ctx))


def gate_size(fn: Fn, file_tokens: int, ctx: Context) -> float:
    return min(1.0, file_tokens / ctx.size_n)


def gate_rank(fn: Fn, file_tokens: int, ctx: Context) -> float:
    return bisect.bisect_right(ctx.good_debts, fn.debt) / max(1, len(ctx.good_debts))


def gate_ramp_size(fn: Fn, file_tokens: int, ctx: Context) -> float:
    return gate_ramp(fn, file_tokens, ctx) * gate_size(fn, file_tokens, ctx)


@dataclass(frozen=True)
class Candidate:
    name: str
    gate: Gate
    k: float = 2.0


CANDIDATES = (
    Candidate("P+D2", gate_none),
    Candidate("G1 hard Phi/c0", gate_hard),
    Candidate("G2 ramp excess", gate_ramp),
    Candidate("G3 size fade", gate_size),
    Candidate("G4 own-cost rank", gate_rank),
    Candidate("G5 ramp x size", gate_ramp_size),
    Candidate("G6 ramp k=4", gate_ramp, 4.0),
)


def extra_debt(prep: Prepared, cand: Candidate, ctx: Context) -> int:
    total = 0.0
    for fn in prep.functions:
        excess = share_excess(fn.tokens, prep.file_tokens)
        if excess:
            total += cand.k * excess * cand.gate(fn, prep.file_tokens, ctx) * fn.debt
    return int(total)


def gated_score(prep: Prepared, cand: Candidate, ctx: Context) -> float:
    return sc.density_score(
        prep.base_debt + extra_debt(prep, cand, ctx), prep.file_tokens
    )


def percentile(values: Sequence[float], q: float) -> float:
    ordered = sorted(values)
    pos = q * (len(ordered) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


def make_context(base: Calibration, good: Sequence[Prepared]) -> Context:
    params = base.languages["python"].parameters
    own = sorted(fn.debt for p in good for fn in p.functions)
    return Context(
        params["Phi"] / sc.MICRO,
        params["c0"] / sc.MICRO,
        percentile([p.file_tokens for p in good], 0.25),
        own,
    )
