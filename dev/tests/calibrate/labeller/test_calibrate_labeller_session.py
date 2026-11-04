from itertools import pairwise

from varde_dev.calibrate.labeller.session import (
    amend_record,
    assemble_display,
    build_schedule,
    display_unit,
    make_session,
    prompt_choice,
    record_label,
    resume_session,
)


def _units():
    return [
        {"id": "u1", "kind": "pair", "item_ids": ["i1", "i2"], "task_id": "t1"},
        {"id": "u2", "kind": "pair", "item_ids": ["i3", "i4"], "task_id": "t2"},
        {"id": "u3", "kind": "triple", "item_ids": ["i5", "i6", "i7"], "task_id": "t3"},
        {"id": "u4", "kind": "pair", "item_ids": ["i8", "i9"], "task_id": "t4"},
        {"id": "u5", "kind": "pair", "item_ids": ["i10", "i11"], "task_id": "t5"},
    ]


def test_schedule_is_seeded_and_randomizes_unit_and_side_order():
    first = build_schedule(_units(), seed=22)
    assert first == build_schedule(_units(), seed=22)
    assert [entry["unit_id"] for entry in first] != [u["id"] for u in _units()]
    assert any(
        entry["item_order"]
        != next(u["item_ids"] for u in _units() if u["id"] == entry["unit_id"])
        for entry in first
    )
    assert first != build_schedule(_units(), seed=23)
    assert all(left["task_id"] != right["task_id"] for left, right in pairwise(first))


def test_reason_prompts_are_seeded_at_about_one_fifth():
    entries = build_schedule(
        [
            {"id": f"u{i}", "kind": "pair", "item_ids": [f"{i}a", f"{i}b"]}
            for i in range(500)
        ],
        seed=31,
    )
    prompted = sum(entry["reason_prompt"] for entry in entries)
    assert 75 <= prompted <= 125


def test_controls_repeats_distractors_reasons_and_breaks_are_scheduled():
    entries = build_schedule(
        _units(),
        seed=9,
        settings={
            "control_positions": {2: "u1"},
            "reshow_interval": 2,
            "distractor_unit_ids": ["u4"],
            "reason_rate": 0.2,
            "break_every": 2,
        },
    )
    assert entries[1]["role"] == "control"
    assert entries[1]["unit_id"] == "u1"
    assert any(entry["role"] == "reshow" for entry in entries)
    assert any(entry["role"] == "distractor" for entry in entries)
    assert any(entry["reason_prompt"] for entry in entries)
    assert any(entry["break_after"] for entry in entries)
    assert len({entry["schedule_id"] for entry in entries}) == len(entries)
    control_index = next(
        i for i, entry in enumerate(entries) if entry["role"] == "control"
    )
    assert control_index == 1
    repeated = build_schedule(_units(), seed=9, settings={"reshow_interval": 2})
    assert repeated[3]["role"] == "reshow"
    assert repeated[3]["unit_id"] == repeated[0]["unit_id"]


def test_triple_expands_to_all_three_pairs_and_display_is_blind():
    unit = _units()[2]
    schedule = build_schedule([unit], seed=1)[0]
    items = {
        f"i{i}": {"text": f"code {i}", "file_name": f"secret{i}.py", "score": 99}
        for i in range(5, 8)
    }
    display = assemble_display(
        unit, {"description": "Implement behavior"}, items, schedule
    )
    assert len(display["pairs"]) == 3
    text = display_unit(unit, {"description": "Implement behavior"}, items, schedule)
    assert text.count("Pair ") == 3
    for forbidden in ("secret", "score", "99", "category", "variant"):
        assert forbidden not in text


def test_single_choice_prompt_returns_shared_choice_value():
    answers = iter(["x", "b"])
    assert prompt_choice(input_fn=lambda _prompt: next(answers)) == "B"


def test_label_records_cursor_pause_resume_and_amend_are_append_only():
    schedule = build_schedule(_units()[:2], seed=3)
    session = make_session("s1", "human", seed=3, schedule=schedule)
    label = record_label(
        schedule[0], choice="A", confidence="high", duration_ms=1200, reason="clear"
    )
    session = resume_session(session, cursor=1, label=label, paused=True)
    assert session["cursor"] == 1
    assert session["labels"] == [label]
    changed = amend_record(label, choice="tie", confidence="medium", duration_ms=300)
    assert changed["amends"] == label["record_id"]
    assert changed != label
    assert session["labels"] == [label]
