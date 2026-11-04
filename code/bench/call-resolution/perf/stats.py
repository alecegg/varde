"""Pure statistics for fast-path timing baselines and their comparison."""

from __future__ import annotations

import statistics

TIME_LIMIT = 1.05
MEMORY_LIMIT = 1.5


def summarize(runs: list[dict]) -> dict:
    """Median wall time and peak RSS of one scenario's runs."""
    if not runs:
        raise ValueError("at least one run is required")
    return {
        "runs": len(runs),
        "wall_ms_median": statistics.median(r["wall_ms"] for r in runs),
        "peak_rss_bytes_median": statistics.median(r["peak_rss_bytes"] for r in runs),
        "peak_rss_bytes_max": max(r["peak_rss_bytes"] for r in runs),
    }


def rss_bytes(ru_maxrss: int, platform_name: str) -> int:
    """``ru_maxrss`` is bytes on macOS and kilobytes elsewhere."""
    return ru_maxrss if platform_name == "darwin" else ru_maxrss * 1024


def ratios(baseline: dict, final: dict) -> list[dict]:
    """Time and memory ratios (final / baseline) for every shared scenario."""
    rows = []
    for fixture in sorted(baseline["results"]):
        for scenario in sorted(baseline["results"][fixture]):
            after = final["results"].get(fixture, {}).get(scenario)
            if after is None:
                raise ValueError(f"final is missing {fixture}/{scenario}")
            before = baseline["results"][fixture][scenario]
            rows.append(
                {
                    "fixture": fixture,
                    "scenario": scenario,
                    "time_ratio": after["wall_ms_median"] / before["wall_ms_median"],
                    "memory_ratio": after["peak_rss_bytes_median"]
                    / before["peak_rss_bytes_median"],
                }
            )
    return rows


def violations(rows: list[dict]) -> list[str]:
    """Human-readable lines for every ratio over its limit."""
    lines = []
    for row in rows:
        name = f"{row['fixture']}/{row['scenario']}"
        if row["time_ratio"] > TIME_LIMIT:
            lines.append(f"{name}: time ratio {row['time_ratio']:.3f} > {TIME_LIMIT}")
        if row["memory_ratio"] > MEMORY_LIMIT:
            lines.append(
                f"{name}: memory ratio {row['memory_ratio']:.3f} > {MEMORY_LIMIT}"
            )
    return lines
