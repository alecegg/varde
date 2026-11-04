import pytest
from varde_runner.guard_log import approvals_by_pattern, redact_prompt


def test_redact_prompt_removes_token_like_value_and_caps_length():
    prompt = redact_prompt(
        {"command": "deploy --token=ghp_secret123", "note": "x" * 3000}
    )
    assert "ghp_secret123" not in prompt
    assert "[redacted]" in prompt
    assert len(prompt) == 2000


@pytest.mark.parametrize(
    ("prompt", "secret"),
    [
        ("GITHUB_TOKEN=abc123", "abc123"),
        ("Authorization: Bearer bearer-secret", "bearer-secret"),
        ("--token abc-token", "abc-token"),
        ("--password=hunter2", "hunter2"),
        ("--api-key api-secret", "api-secret"),
        ("sk-1234567890abcdef", "sk-1234567890abcdef"),
        ("github_pat_1234567890abcdef", "github_pat_1234567890abcdef"),
        ('{"password": "hunter2 x"}', "hunter2 x"),
        ("mysql -p hunter2", "hunter2"),
        ("ghp_abcDEF123456", "ghp_abcDEF123456"),
        ("gho_abcDEF123456", "gho_abcDEF123456"),
        ('{\\"password\\": \\"a b\\"}', "a b"),
        ("mysql -phunter2", "hunter2"),
        ('mysql -p"my pass"', "my pass"),
        ("Authorization: Basic dXNlcjpwYXNz", "dXNlcjpwYXNz"),
        ("connect user:pass@host", "user:pass"),
        ("AWS key AKIA1234567890ABCDEF", "AKIA1234567890ABCDEF"),
    ],
)
def test_redacts_secret_forms(prompt, secret):
    redacted = redact_prompt(prompt)
    assert secret not in redacted
    assert "[redacted]" in redacted


def test_approvals_by_pattern_summarizes_and_marks_revocation():
    rows = [
        {"request_key": "command:git", "verdict": "approve", "ts": "2026-01-01"},
        {
            "request_key": "command:git",
            "verdict": "approve",
            "ts": "2026-01-02",
            "revoked": True,
        },
        {"request_key": "command:rm", "verdict": "escalated", "ts": "2026-01-03"},
    ]
    assert approvals_by_pattern(rows, frozenset({"command:git"})) == [
        {
            "request_key": "command:git",
            "count": 2,
            "last_ts": "2026-01-02",
            "revoked": True,
        }
    ]
