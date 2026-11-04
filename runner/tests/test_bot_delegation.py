from varde_runner.bot_prompt import MANAGER_BOT_PROMPT


def test_manager_prompt_describes_delegation_and_status_rules():
    assert "GET /api/identities" in MANAGER_BOT_PROMPT
    assert "description" in MANAGER_BOT_PROMPT
    assert "only through an orchestrator" in MANAGER_BOT_PROMPT
    assert "A name mentioned by the user is a hint" in MANAGER_BOT_PROMPT
    assert "Never retry a refused action" in MANAGER_BOT_PROMPT
    assert "Progress, Agents:, My work, Needed" in MANAGER_BOT_PROMPT
    assert "Ask the user through Mailbox" in MANAGER_BOT_PROMPT
    assert "varde plan merged <plan>" in MANAGER_BOT_PROMPT
    assert "terminal-specific" in MANAGER_BOT_PROMPT
