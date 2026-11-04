"""Scan-time quality pass: facts, path classes, graph measures and the store.

Public entry points are ``run_quality_pass(root, *, no_cache=False)`` and
``read_facts(root)``. The fast flows never import this package.
"""

from varde_code.quality_pass.pass_ import (
    PassSummary,
    QualityPassError,
    read_facts,
    read_measures,
    run_quality_pass,
)

__all__ = [
    "PassSummary",
    "QualityPassError",
    "read_facts",
    "read_measures",
    "run_quality_pass",
]
