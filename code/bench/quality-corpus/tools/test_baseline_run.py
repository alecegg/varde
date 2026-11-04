# ruff: noqa: S101
"""Offline tests for the baseline agreement driver (stub clients, no model calls)."""

import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import baseline_protocol as bp
import baseline_run as br

CELL = bp.Cell("job-scheduler", "python")
TEXT = bp.ProblemText("prompt", "spec", "api", "idiom")


def block(code: str) -> str:
    return f"```python\n{code}\n```"


class Stub:
    prompts: list[str]
    """Scripted client: ``handler(prompt, call_number) -> Reply``."""

    def __init__(self, name, handler):
        self.name, self.handler, self.prompts = name, handler, []

    def call(self, prompt):
        self.prompts.append(prompt)
        return self.handler(prompt, len(self.prompts))


KIND_MARKERS = (
    ("fails its behaviour tests", "repair"),
    ("List the real design conflicts", "conflicts"),
    ("state what you want and why it is warranted", "case"),
    ("You are the judge", "ruling"),
    ("Write the best python solution", "write"),
)


def kind(prompt: str) -> str:
    return next((name for text, name in KIND_MARKERS if text in prompt), "other")


USAGE = {
    "input_tokens": 100,
    "cache_creation_input_tokens": 10,
    "cache_read_input_tokens": 5,
    "output_tokens": 20,
}


TWO_SCHOOLS = "1. nesting | schools: clean-code, aposd | metric: depth | x"
ALL_SCHOOLS = (
    TWO_SCHOOLS + "\n2. names | schools: clean-code, aposd, modern | metric: n | y"
)


def default_handler(
    conflicts: str = TWO_SCHOOLS,
    write_code="GOOD v",
    ruling_code="GOOD ruled",
):
    def handle(prompt, number):
        what = kind(prompt)
        if what == "conflicts":
            return br.Reply(conflicts, USAGE)
        if what == "case":
            return br.Reply("1. topic: x. priority: flexible", USAGE)
        if what == "ruling":
            return br.Reply(
                "1. topic x: upheld, because y\n" + block(ruling_code), USAGE
            )
        if what == "repair":
            return br.Reply(block("GOOD repaired"), USAGE)
        return br.Reply(block(write_code), USAGE)

    return handle


def fake_tests(cell, code):
    return SimpleNamespace(
        ok="BAD" not in code, output_tail="boom" if "BAD" in code else ""
    )


def make(tmp_path, luna=None, sonnet=None, scanner=None, **kw):
    return br.Driver(
        ledger=br.Ledger(tmp_path / "ledger.jsonl"),
        clients={
            "luna": luna or Stub("luna", default_handler()),
            "sonnet": sonnet or Stub("sonnet", default_handler()),
        },
        run_id="r1",
        state_dir=tmp_path / "state",
        out_dir=tmp_path / "out",
        texts=lambda c: TEXT,
        lens=lambda b: f"lens {b}",
        tester=fake_tests,
        measurer=lambda c, code: {"t0": 3},
        scanner=scanner or (lambda snippets: []),
        clock=lambda: 1000.0,
        **kw,
    )


def stubs(d) -> list[Stub]:
    return [c for c in d.clients.values() if isinstance(c, Stub)]


def all_prompts(d) -> list[str]:
    return [p for s in stubs(d) for p in s.prompts]


def totals(d):
    return bp.ledger_totals(d.ledger.read())


# ---- agreement path ----


def test_typical_cell_takes_seven_calls(tmp_path):
    d = make(tmp_path)
    out = br.run_cell(d, 0, CELL)
    assert (out["agreed"], out["status"], out["calls"], out["tests_passed"]) == (
        True,
        "judge_ruled",
        7,
        True,
    )
    assert totals(d).calls == 7
    kinds = [kind(p) for p in all_prompts(d)]
    assert kinds.count("case") == 2 and kinds.count("ruling") == 1
    assert "upheld" in out["rulings"] and "```" not in out["rulings"]
    provenance = (
        tmp_path / "out/agreed/job-scheduler/python/PROVENANCE.md"
    ).read_text()
    assert "idiom_notes_sha256" in provenance and "agreed: True" in provenance
    code = (tmp_path / "out/agreed/job-scheduler/python/solution.py").read_text()
    assert code.strip() == "GOOD ruled"


def test_families_alternate_per_cell(tmp_path):
    even, odd = bp.writer_families(0), bp.writer_families(1)
    assert even == {"clean-code": "luna", "aposd": "sonnet", "modern": "luna"}
    assert (
        odd["aposd"] == "luna"
        and bp.judge_family(0) == "sonnet"
        and bp.judge_family(1) == "luna"
    )


def stub_pair(tmp_path, handler, **kw):
    return make(tmp_path, Stub("luna", handler), Stub("sonnet", handler), **kw)


def test_cases_only_for_schools_party_to_a_conflict(tmp_path):
    d = stub_pair(tmp_path, default_handler())
    br.run_cell(d, 0, CELL)
    cases = [p for p in all_prompts(d) if kind(p) == "case"]
    assert sorted(
        base for p in cases for base in bp.BASES if f"Your school is '{base}'" in p
    ) == ["aposd", "clean-code"]


def test_all_three_parties_cost_the_eight_call_cell(tmp_path):
    d = stub_pair(tmp_path, default_handler(conflicts=ALL_SCHOOLS))
    out = br.run_cell(d, 0, CELL)
    assert (out["agreed"], out["calls"]) == (True, 8)


def test_no_conflicts_skips_cases_and_still_rules(tmp_path):
    d = stub_pair(tmp_path, default_handler(conflicts="No conflicts."))
    out = br.run_cell(d, 0, CELL)
    assert (out["status"], out["calls"]) == ("judge_ruled", 5)
    assert [kind(p) for p in all_prompts(d)].count("case") == 0


def test_ruling_prompt_carries_versions_conflicts_and_cases(tmp_path):
    d = stub_pair(tmp_path, default_handler())
    br.run_cell(d, 0, CELL)
    ruling = next(p for p in all_prompts(d) if kind(p) == "ruling")
    assert "GOOD v" in ruling and "nesting" in ruling and "priority: flexible" in ruling


def test_ruling_that_fails_tests_is_not_agreed(tmp_path):
    shared = default_handler(ruling_code="BAD ruled")

    def handle(prompt, number):
        if kind(prompt) == "repair":  # the one fix call reuses repair wording
            return br.Reply(block("BAD fixed"), USAGE)
        return shared(prompt, number)

    d = stub_pair(tmp_path, handle)
    out = br.run_cell(d, 0, CELL)
    assert (out["agreed"], out["status"], out["tests_passed"]) == (
        False,
        "tests_failed",
        False,
    )
    assert out["calls"] == 8  # 3 writes, conflicts, 2 cases, ruling, one fix
    assert [kind(p) for p in all_prompts(d)].count("ruling") == 1


def test_ruling_without_code_is_no_ruling(tmp_path):
    def handle(prompt, number):
        if kind(prompt) == "ruling":
            return br.Reply("1. x: upheld", USAGE)
        return default_handler()(prompt, number)

    out = br.run_cell(stub_pair(tmp_path, handle), 0, CELL)
    assert (out["status"], out["agreed"]) == ("no_ruling", False)


def test_ruling_resumes_from_saved_negotiation(tmp_path):
    first = default_handler()

    def stop_at_ruling(prompt, n):
        if kind(prompt) == "ruling":
            raise br.LimitStop("sonnet", 5000.0)
        return first(prompt, n)

    d = stub_pair(tmp_path, stop_at_ruling)
    with pytest.raises(br.LimitStop):
        br.run_cell(d, 0, CELL)
    d2 = make(tmp_path)
    d2.clock = lambda: 6000.0
    out = br.run_cell(d2, 0, CELL)
    assert out["status"] == "judge_ruled"
    assert [kind(p) for p in all_prompts(d2)] == ["ruling"]


def test_repair_cap_is_two_per_cell(tmp_path):
    def always_bad(prompt, number):
        what = kind(prompt)
        if what == "repair":
            return br.Reply(block("BAD again"), USAGE)
        return br.Reply(block("BAD v"), USAGE)

    d = make(tmp_path, Stub("luna", always_bad), Stub("sonnet", always_bad))
    out = br.run_cell(d, 0, CELL)
    assert out["status"] == "writers_failed" and out["agreed"] is False
    assert out["calls"] == 3 + bp.MAX_REPAIRS


def test_final_version_gets_one_fix_call(tmp_path):
    def handle(prompt, number):
        if kind(prompt) == "repair":  # the fix call reuses the repair wording
            return br.Reply(block("GOOD fixed"), USAGE)
        return default_handler(ruling_code="BAD ruled")(prompt, number)

    d = stub_pair(tmp_path, handle)
    out = br.run_cell(d, 0, CELL)
    assert out["agreed"] is True and out["calls"] == 8
    assert [line["role"] for line in d.ledger.read() if line["kind"] == "intent"].count(
        "fix"
    ) == 1


def test_missing_toolchain_spends_no_calls(tmp_path):
    d = make(tmp_path, toolchain=lambda language: False)
    out = br.run_cell(d, 0, CELL)
    assert out["status"] == "toolchain_missing" and totals(d).calls == 0


# ---- caps and usage ----


def test_cap_refusal_at_200_calls(tmp_path):
    d = make(tmp_path)
    for n in range(bp.MAX_CALLS):
        d.ledger.append(
            {
                "kind": "intent",
                "run": "old",
                "key": f"k{n}",
                "client": "luna",
                "role": "write",
                "cell": "c",
                "prompt_chars": 1,
                "est_tokens": 1,
                "ts": 0,
            }
        )
        d.ledger.append(
            {
                "kind": "result",
                "run": "old",
                "key": f"k{n}",
                "client": "luna",
                "role": "write",
                "cell": "c",
                "outcome": "ok",
                "tokens": 1,
                "estimated": False,
                "output_chars": 1,
                "ts": 0,
            }
        )
    with pytest.raises(br.CapRefused, match="call cap"):
        d.call(CELL, "write-clean-code", "luna", "write", "p")
    assert stubs(d)[0].prompts == []


def test_cap_refusal_at_1_5m_tokens(tmp_path):
    d = make(tmp_path)
    d.ledger.append(
        {
            "kind": "intent",
            "run": "old",
            "key": "k",
            "client": "luna",
            "role": "write",
            "cell": "c",
            "prompt_chars": 1,
            "est_tokens": 1,
            "ts": 0,
        }
    )
    d.ledger.append(
        {
            "kind": "result",
            "run": "old",
            "key": "k",
            "client": "luna",
            "role": "write",
            "cell": "c",
            "outcome": "ok",
            "tokens": bp.MAX_TOKENS - 10,
            "estimated": False,
            "output_chars": 1,
            "ts": 0,
        }
    )
    with pytest.raises(br.CapRefused, match="token cap"):
        d.call(CELL, "write-clean-code", "luna", "write", "p" * 400)
    assert stubs(d)[0].prompts == []


def test_reported_usage_counts_cache_and_output(tmp_path):
    assert bp.billed_tokens(USAGE) == 135
    d = make(tmp_path)
    d.call(CELL, "write-clean-code", "luna", "write", "p")
    assert totals(d).tokens == 135 and totals(d).estimated_calls == 0


def test_unreported_usage_is_estimated_and_counted(tmp_path):
    luna = Stub("luna", lambda prompt, n: br.Reply("x" * 40))
    d = make(tmp_path, luna=luna, overhead=1000)
    d.call(CELL, "write-clean-code", "luna", "write", "p" * 400)
    result = next(line for line in d.ledger.read() if line["kind"] == "result")
    assert result["estimated"] is True and result["tokens"] == 110 + 1000
    assert totals(d) == bp.Totals(1, 1110, 1)


def test_crash_between_intent_and_result_still_counts(tmp_path):
    def crash(prompt, n):
        raise KeyboardInterrupt  # not caught by the driver: no result line is written

    d = make(tmp_path, luna=Stub("luna", crash), overhead=500)
    with pytest.raises(KeyboardInterrupt):
        d.call(CELL, "write-clean-code", "luna", "write", "p" * 400)
    kinds = [line["kind"] for line in d.ledger.read()]
    assert kinds == ["intent"]
    counted = totals(d)
    assert counted.calls == 1 and counted.tokens > 500 and counted.estimated_calls == 1


def test_crashed_attempt_keeps_its_estimate_after_retry(tmp_path):
    d = make(tmp_path, overhead=500)
    d.ledger.append(
        {
            "kind": "intent",
            "run": "r1",
            "key": "python/job-scheduler:write-aposd",
            "client": "luna",
            "role": "write",
            "cell": "c",
            "prompt_chars": 4,
            "est_tokens": 600,
            "ts": 0,
        }
    )
    d.call(CELL, "write-aposd", "luna", "write", "p")
    counted = totals(d)
    assert counted.calls == 2 and counted.tokens == 600 + 135


# ---- limit stop and resume ----


def test_limit_stop_then_resume_repeats_no_done_call(tmp_path):
    state = {"limited": True}

    def limited(prompt, n):
        if state["limited"] and kind(prompt) == "case":
            raise br.LimitStop("sonnet", 5000.0)
        return default_handler()(prompt, n)

    sonnet = Stub("sonnet", limited)
    luna = Stub("luna", default_handler())
    d = make(tmp_path, luna, sonnet)
    with pytest.raises(br.LimitStop):
        br.run_cell(d, 1, CELL)
    first = totals(d).calls
    done_before = bp.done_keys(d.ledger.read(), "r1")
    assert any(line["kind"] == "limit" for line in d.ledger.read())
    # still limited: a new driver (same run id) refuses before any intent
    d2 = make(tmp_path, luna, sonnet)
    d2.clock = lambda: 1500.0
    with pytest.raises(br.LimitStop):
        br.run_cell(d2, 1, CELL)
    assert totals(d2).calls == first
    # after the reset time: resume skips done keys
    state["limited"] = False
    d3 = make(tmp_path, luna, sonnet)
    d3.clock = lambda: 6000.0
    calls_before = totals(d3).calls
    out = br.run_cell(d3, 1, CELL)
    assert out["agreed"] is True
    new_intents = [
        line["key"] for line in d3.ledger.read() if line["kind"] == "intent"
    ][calls_before:]
    assert new_intents and not set(new_intents) & done_before


# ---- secret scan ----


def test_secret_in_generated_code_blocks_the_write(tmp_path):
    d = make(
        tmp_path,
        scanner=lambda snippets: (
            ["aws-key"] if any("GOOD ruled" in s for s in snippets) else []
        ),
    )
    out = br.run_cell(d, 0, CELL)
    assert out["agreed"] is False and out["status"].startswith("secret_blocked")
    assert not (tmp_path / "out").exists() or not list((tmp_path / "out").rglob("*.py"))


# ---- probes ----


def test_probe_records_overhead(tmp_path):
    luna = Stub(
        "luna",
        lambda prompt, n: br.Reply("ok", {"input_tokens": 9000, "output_tokens": 5}),
    )
    d = make(tmp_path, luna=luna)
    line = br.run_probe(d, "luna")
    assert line["kind"] == "probe" and 8900 < line["overhead_tokens"] < 9000
    assert bp.measured_overhead(d.ledger.read()) == line["overhead_tokens"]


# ---- adapters (fake runner, no process) ----


def test_claude_adapter_parses_usage_and_limit():
    ok = json.dumps({"result": "hi", "is_error": False, "usage": USAGE})
    seen = {}

    def runner(argv, stdin, env):
        seen.update(argv=argv, stdin=stdin)
        return 0, ok, ""

    reply = br.ClaudeClient(runner).call("prompt")
    assert reply.text == "hi" and bp.billed_tokens(reply.usage or {}) == 135
    assert "claude-sonnet-5-5" in seen["argv"] and "--bare" not in seen["argv"]
    limited = br.ClaudeClient(
        lambda a, s, e: (1, "", "Claude usage limit reached"), clock=lambda: 10.0
    )
    with pytest.raises(br.LimitStop) as stop:
        limited.call("p")
    assert stop.value.resume_after == 3610.0


def test_codex_adapter_parses_events_and_missing_usage():
    events = "\n".join(
        [
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {"type": "agent_message", "text": "answer"},
                }
            ),
            json.dumps(
                {
                    "type": "turn.completed",
                    "usage": {"input_tokens": 50, "output_tokens": 7},
                }
            ),
        ]
    )
    client = br.CodexClient(lambda a, s, e: (0, events, ""))
    reply = client.call("p")
    assert reply.text == "answer" and bp.billed_tokens(reply.usage or {}) == 57
    no_usage = json.dumps(
        {"type": "item.completed", "item": {"type": "agent_message", "text": "a"}}
    )
    assert br.CodexClient(lambda a, s, e: (0, no_usage, "")).call("p").usage is None


def test_subscription_env_drops_api_keys():
    env = br.subscription_env(
        {"PATH": "/bin", "ANTHROPIC_API_KEY": "x", "OPENAI_API_KEY": "y"}
    )
    assert env == {"PATH": "/bin"}


# ---- check-agreed, check-ledger, dry-run ----


def entries(agreed_by_language):
    out = {}
    for language, count in agreed_by_language.items():
        for i, problem in enumerate(bp.PROBLEMS):
            out[f"{language}/{problem}"] = {
                "agreed": i < count,
                "tests_passed": i < count,
            }
    return out


def test_check_agreed_thresholds():
    good = entries({"python": 3, "typescript": 4, "csharp": 3})
    assert bp.check_agreement_entries(good, 3, 9) == []
    short = entries({"python": 2, "typescript": 4, "csharp": 4})
    assert any("python" in p for p in bp.check_agreement_entries(short, 3, 9))
    low_total = entries({"python": 3, "typescript": 3, "csharp": 2})
    problems = bp.check_agreement_entries(low_total, 2, 9)
    assert problems == ["total: 8 agreed cells, need 9"]


def test_judge_ruled_entry_needs_rulings_text():
    ruled = {"agreed": True, "tests_passed": True, "status": "judge_ruled"}
    without = {f"{lang}/p": dict(ruled) for lang in bp.LANGUAGES}
    assert len(bp.check_agreement_entries(without, 1, 3)) == 4
    with_text = {k: dict(v, rulings="1. x: upheld") for k, v in without.items()}
    assert bp.check_agreement_entries(with_text, 1, 3) == []


def test_check_agreed_cli_requires_provenance(tmp_path):
    data = entries({"python": 3, "typescript": 3, "csharp": 3})
    for key in data:
        data[key]["dir"] = f"agreed/{key}"
    (tmp_path / "agreement.json").write_text(json.dumps(data))
    args = argparse.Namespace(
        check_agreed=str(tmp_path / "agreement.json"),
        min_per_language=3,
        min_total=9,
        out_dir=str(tmp_path),
    )
    assert br.check_agreed(args) == 1  # no PROVENANCE.md anywhere


def test_check_ledger_flags_cap_and_post_limit_calls(tmp_path):
    ledger = br.Ledger(tmp_path / "l.jsonl")
    ledger.append({"kind": "limit", "client": "luna", "resume_after": 500.0, "ts": 100})
    ledger.append(
        {
            "kind": "intent",
            "run": "r",
            "key": "k",
            "client": "luna",
            "role": "write",
            "cell": "c",
            "prompt_chars": 1,
            "est_tokens": 10,
            "ts": 200,
        }
    )
    args = argparse.Namespace(
        check_ledger=str(ledger.path), max_calls=200, max_tokens=1500000
    )
    assert br.check_ledger(args) == 1
    assert bp.calls_after_limit(ledger.read()) == ["luna:k"]


def test_planned_calls_arithmetic():
    # 3 writes, 2 repairs, conflicts, 3 cases, ruling, fix
    assert bp.max_agreement_calls() == 11
    assert bp.planned_calls(12) == {
        "agreement": 132,
        "probes": 4,
        "total": 136,
        "typical_total": 88,
    }
    assert len(bp.TYPICAL_CELL_ROLES) == 7


def test_dry_run_exit_codes(tmp_path, capsys):
    base = [
        "--dry-run",
        "--cells",
        "all",
        "--token-estimate",
        "--max-tokens",
        "2100000",
        "--ledger",
        str(tmp_path / "none.jsonl"),
    ]
    assert br.main([*base, "--max-planned-calls", "136"]) == 0
    assert "planned calls: 136" in capsys.readouterr().out
    assert br.main([*base, "--max-planned-calls", "135"]) == 1
    assert br.main([*base, "--max-planned-calls", "136", "--max-tokens", "1000"]) == 1


def test_parse_conflicts_reads_party_schools():
    reply = (
        "1. nesting | schools: clean-code, aposd | metric: depth | x\n"
        "2. names | Schools: modern | metric: names | y\n"
        "3. unmarked conflict"
    )
    parsed = bp.parse_conflicts(reply)
    assert [c.schools for c in parsed] == [
        ("clean-code", "aposd"),
        ("modern",),
        bp.BASES,
    ]
    assert bp.conflict_parties(parsed[:2]) == ["clean-code", "aposd", "modern"]
    assert bp.conflict_parties(parsed[:1]) == ["clean-code", "aposd"]
    assert bp.parse_conflicts("No conflicts.") == []


def test_prompts_carry_personas_and_no_scaffolding():
    root = Path(__file__).parent.parent
    text = bp.ProblemText("prompt", "spec", "api", "idiom")
    versions: dict[str, str] = dict.fromkeys(bp.BASES, "code\n")
    cases = {b: f"case of {b}" for b in bp.BASES}
    for base in bp.BASES:
        lens = br.load_lens(base, root)
        school = bp.PERSONAS[base].school
        prompts = {
            "write": bp.writer_prompt(text, "python", base, lens),
            "case": bp.case_prompt(base, lens, "python", versions, {}, "1. x"),
        }
        for prompt in prompts.values():
            for banned in ("{{", "pair_id", "Q1", "A|B"):
                assert banned not in prompt
            assert school in prompt
            assert bp.lens_principles(lens).split("\n")[0] in prompt
        assert "must-keep" in prompts["case"]
        assert "evidence in the code" in prompts["case"]
    ruling = bp.ruling_prompt("python", versions, {}, "1. topic x", cases)
    assert "You are the judge" in ruling and "case of aposd" in ruling
    assert "1. topic x" in ruling
    assert "do not side with an expert automatically" in ruling
    assert "validity" in ruling and "one ruling per issue" in ruling
    for banned in ("{{", "pair_id", "Q1", "A|B"):
        assert banned not in ruling
    conflicts = bp.conflicts_prompt("python", versions, {})
    assert "List the real design conflicts" in conflicts
    assert "schools:" in conflicts and "no conflicts" in conflicts
