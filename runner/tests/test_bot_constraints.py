from __future__ import annotations

import pytest
from varde_runner.bot_constraints import (
    BotConfig,
    ConstraintContext,
    check,
    check_agent_action,
    check_launch,
    load_bot_config,
)
from varde_runner.bot_tokens import BOT_ACTOR, BotIdentity

BOUND_SLOTS = {"orchestrator-9"}
BOUND_PLANS = {"busy-plan"}
LAUNCHED = {
    "mine": BOT_ACTOR,
    "child": f"{BOT_ACTOR}/mine",
    "grandchild": f"{BOT_ACTOR}/child",
    "sibling": f"{BOT_ACTOR}/other",
    "other-root": BOT_ACTOR,
    "theirs": "user",
    "unowned": None,
}
ROOT = BotIdentity(BOT_ACTOR, "manager")
DESCENDANT = BotIdentity(f"{BOT_ACTOR}/mine", "mine")


def ctx(**overrides) -> ConstraintContext:
    values = {
        "workspace_listed": lambda workspace: workspace == "ws-1",
        "slot_bound": lambda slot: slot in BOUND_SLOTS,
        "plan_bound": lambda plan: plan in BOUND_PLANS,
        "launched_by": LAUNCHED.get,
        "plan_exists": lambda plan: plan.startswith("plan-"),
        "plan_status": lambda plan: "backlog" if plan == "plan-backlog" else "active",
    }
    return ConstraintContext(**{**values, **overrides})


CONFIG = BotConfig()
GOOD = {"role": "orchestrator", "workspace": "ws-1", "prompt": "go"}


def test_a_listed_role_workspace_and_free_slot_may_launch() -> None:
    assert check_launch(GOOD, CONFIG, ctx()) is None
    assert (
        check_launch({**GOOD, "requested_identity": "builder"}, CONFIG, ctx()) is None
    )
    with_slot = {**GOOD, "address": {"slot": "orchestrator-3", "plan": "plan-x"}}
    assert check_launch(with_slot, CONFIG, ctx()) is None


@pytest.mark.parametrize(
    ("body", "reason"),
    [
        ({**GOOD, "role": "builder"}, "bot.launch_roles"),
        ({**GOOD, "role": None}, "bot.launch_roles"),
        ({**GOOD, "workspace": "/etc"}, "listed workspace"),
        ({**GOOD, "workspace": 5}, "listed workspace"),
        ({**GOOD, "mode": "full-access"}, "fields not allowed: mode"),
        ({**GOOD, "requested_identity": ""}, "requested_identity"),
        ({**GOOD, "harness": "x", "parent_id": "p"}, "fields not allowed"),
        ({**GOOD, "address": {"slot": "main"}}, "orchestrator-N"),
        ({**GOOD, "address": {"slot": "manager"}}, "orchestrator-N"),
        ({**GOOD, "address": {"slot": "orchestrator-"}}, "orchestrator-N"),
        ({**GOOD, "address": {"slot": "orchestrator-1x"}}, "orchestrator-N"),
        ({**GOOD, "address": {"slot": "orchestrator-9"}}, "slot is bound"),
        (
            {**GOOD, "address": {"slot": "orchestrator-1", "plan": "busy-plan"}},
            "plan is bound",
        ),
        ({**GOOD, "address": {"slot": "orchestrator-1", "plan": 5}}, "plan is bound"),
        ({**GOOD, "address": "orchestrator-1"}, "address must be an object"),
    ],
)
def test_launch_refusals(body, reason) -> None:
    refusal = check_launch(body, CONFIG, ctx())
    assert refusal is not None and reason in refusal


def test_launch_roles_come_from_config() -> None:
    config = BotConfig(("explorer",))
    assert check_launch({**GOOD, "role": "orchestrator"}, config, ctx()) is not None
    assert check_launch({**GOOD, "role": "explorer"}, config, ctx()) is None


def test_load_bot_config_reads_launch_roles_and_falls_back(tmp_path) -> None:
    path = tmp_path / "runner.toml"
    assert load_bot_config(path) == BotConfig()
    path.write_text('[bot]\nlaunch_roles = ["planner"]\n')
    assert load_bot_config(path).launch_roles == ("planner",)
    for broken in (
        "[bot]\nlaunch_roles = []\n",
        "[bot]\nlaunch_roles = [1]\n",
        "[bot",
        "x = 1\n",
    ):
        path.write_text(broken)
        assert load_bot_config(path) == BotConfig()


@pytest.mark.parametrize("action", ["prompt", "interrupt", "resume", "stop", "archive"])
def test_the_bot_may_act_on_agents_it_launched_and_their_descendants(action) -> None:
    assert check_agent_action(action, "mine", ROOT, ctx()) is None
    assert check_agent_action(action, "child", ROOT, ctx()) is None
    assert check_agent_action(action, "mine", DESCENDANT, ctx()) is None
    assert check_agent_action(action, "child", DESCENDANT, ctx()) is None
    assert check_agent_action(action, "grandchild", DESCENDANT, ctx()) is None


@pytest.mark.parametrize("action", ["prompt", "interrupt", "resume", "stop", "archive"])
def test_descendant_cannot_control_sibling_agents(action) -> None:
    assert (
        check(
            "agent_action",
            {"id": "sibling", "action": action},
            {},
            CONFIG,
            ctx(),
            DESCENDANT,
        )
        == "agent was not launched by the bot"
    )
    assert (
        check_agent_action(action, "other-root", DESCENDANT, ctx())
        == "agent was not launched by the bot"
    )


@pytest.mark.parametrize("agent", ["theirs", "unowned", "missing"])
def test_the_bot_may_not_act_on_other_agents(agent) -> None:
    assert (
        check_agent_action("stop", agent, ROOT, ctx())
        == "agent was not launched by the bot"
    )


@pytest.mark.parametrize("action", ["respond", "mode", "", "delete"])
def test_other_actions_are_refused_even_on_its_own_agents(action) -> None:
    assert check_agent_action(action, "mine", ROOT, ctx()) == "action is not allowed"


def test_dispatch_covers_every_constraint_and_unknown_names_refuse() -> None:
    assert check("launch", {}, GOOD, CONFIG, ctx()) is None
    assert (
        check(
            "agent_action",
            {"id": "mine", "action": "stop"},
            {},
            CONFIG,
            ctx(),
            ROOT,
        )
        is None
    )
    assert check("stub", {}, {"text": "idea"}, CONFIG, ctx()) is None
    assert check("stub", {}, {"text": "idea", "agent": "x"}, CONFIG, ctx()) is not None
    assert check("bot_say", {}, {"text": "hello"}, CONFIG, ctx()) is None
    assert check("bot_notes", {}, {"text": "note"}, CONFIG, ctx()) is None
    assert (
        check(
            "bot_mailbox",
            {},
            {"asked": "Continue?", "options": ["Yes"]},
            CONFIG,
            ctx(),
        )
        is None
    )
    assert (
        check(
            "plan_edit",
            {"plan_id": "plan-backlog"},
            {"body": "updated"},
            CONFIG,
            ctx(),
        )
        is None
    )
    assert (
        check(
            "plan_edit",
            {"plan_id": "plan-active"},
            {"body": "updated"},
            CONFIG,
            ctx(),
        )
        == "plan is not backlog"
    )
    assert (
        check("queue_move", {}, {"plan": "plan-1", "direction": "up"}, CONFIG, ctx())
        is None
    )
    assert check("queue_move", {}, {"plan": "other"}, CONFIG, ctx()) == "plan not found"
    assert (
        check("queue_move", {}, {"plan": "plan-1", "x": 1}, CONFIG, ctx()) is not None
    )
    comment = {"target": "plan", "text": "hi"}
    assert check("plan_comment", {"plan_id": "plan-1"}, comment, CONFIG, ctx()) is None
    assert (
        check("plan_comment", {"plan_id": "gone"}, comment, CONFIG, ctx())
        == "plan not found"
    )
    assert (
        check(
            "plan_comment",
            {"plan_id": "plan-1"},
            {**comment, "sender": "main"},
            CONFIG,
            ctx(),
        )
        is not None
    )
    assert check("nope", {}, {}, CONFIG, ctx()) == "unknown constraint"
