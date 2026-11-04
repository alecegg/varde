import json

from varde_workflow.route_decision import (
    RouteDecision,
    RouteTierSummary,
    append_route_decision,
    read_route_decisions,
    summarize_route_decisions,
)


def test_append_and_read_route_decisions(tmp_path):
    path = tmp_path / "plan" / "notes" / "route-decisions.jsonl"
    decisions = (
        RouteDecision("self", (), "model-a", "provider-a", 10, 4, 0.02),
        RouteDecision(
            "orchestrator",
            ("reviewer",),
            "model-b",
            "provider-b",
            20,
            8,
            0.05,
            "pass",
            0,
            0,
            1,
        ),
    )

    for decision in decisions:
        append_route_decision(path, decision)

    assert read_route_decisions(path).decisions == decisions
    assert read_route_decisions(path).corrupt_lines == 0
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert rows[1]["review_verdict"] == "pass"
    assert rows[1]["retries"] == 1


def test_read_missing_file_and_summarize_by_route_tier(tmp_path):
    assert read_route_decisions(tmp_path / "missing.jsonl").decisions == ()


def test_reader_skips_and_counts_corrupt_lines_and_ignores_unknown_keys(tmp_path):
    path = tmp_path / "decisions.jsonl"
    valid = RouteDecision("self", (), None, None, 1, 2, 0.1)
    append_route_decision(path, valid)
    with path.open("a") as stream:
        stream.write("{broken json}\n")
        stream.write(
            '{"route_tier":"direct","reviewers":[],"model":null,"provider":null,"input_tokens":1,"output_tokens":2,"cost":0.1,"future_key":true}\n'
        )
    result = read_route_decisions(path)
    assert result.decisions == (valid, valid)
    assert result.corrupt_lines == 1


def test_reader_migrates_legacy_route_tiers_and_rejects_unknown_values(tmp_path):
    path = tmp_path / "legacy.jsonl"
    with path.open("w") as stream:
        for tier in ("direct", "plan", "orchestrate", "mystery"):
            stream.write(
                json.dumps(
                    {
                        "route_tier": tier,
                        "reviewers": [],
                        "model": None,
                        "provider": None,
                        "input_tokens": 1,
                        "output_tokens": 2,
                        "cost": 0.1,
                    }
                )
                + "\n"
            )
    result = read_route_decisions(path)
    assert [decision.route_tier for decision in result.decisions] == [
        "self",
        "orchestrator",
        "orchestrator",
    ]
    assert result.corrupt_lines == 1


def test_summary_includes_retries_and_findings():
    summary = summarize_route_decisions(
        [
            RouteDecision(
                "builder", (), None, None, 10, 5, 0.1, retries=2, review_findings=3
            ),
            RouteDecision(
                "builder", (), None, None, 4, 2, 0.2, retries=1, review_findings=1
            ),
        ]
    )
    assert summary["builder"] == RouteTierSummary(2, 14, 7, 0.30000000000000004, 3, 4)
    summary = summarize_route_decisions(
        [
            RouteDecision("orchestrator", (), None, None, 10, 5, 0.1),
            RouteDecision("orchestrator", ("reviewer",), "m", "p", 20, 3, 0.2),
            RouteDecision("self", (), None, None, 4, 2, 0.03),
        ]
    )

    assert summary == {
        "orchestrator": RouteTierSummary(2, 30, 8, 0.30000000000000004, 0, 0),
        "self": RouteTierSummary(1, 4, 2, 0.03, 0, 0),
    }
