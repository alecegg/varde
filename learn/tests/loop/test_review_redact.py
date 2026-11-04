import pytest
from varde_learn.loop.review.redact import redact


@pytest.mark.parametrize(
    "secret",
    [
        '"password": "hunter2hunter2"',
        '"api_key": "abcd1234efgh"',
        "password: hunter2hunter2",
        r'{"password\":\"hunter2hunter2"}',
        "MY_KEY=abcdefgh12345",
        "a" * 32,
        "a" * 76 + "-_",
        "eyJabc.def.ghi",
        "Authorization: Basic dXNlcjpwYXNzd29yZA==",
        "Authorization: Token opaquecredential",
        "Proxy-Authorization: Basic abc123",
        "Cookie: session=privatecookie",
        "Set-Cookie: token=privatecookie",
        "-----BEGIN RSA PRIVATE KEY-----\nMIIEowI...",
        "-----BEGIN RSA PRIVATE KEY-----\n"
        + "MIIEowI\n" * 30
        + "-----END RSA PRIVATE KEY-----",
    ],
)
def test_redacts_review_secrets(secret: str) -> None:
    assert secret not in redact(secret)


def test_redacts_long_values_before_digest_field_truncation() -> None:
    pem = (
        "-----BEGIN RSA PRIVATE KEY-----\n"
        + "MIIEowI\n" * 100
        + "-----END RSA PRIVATE KEY-----"
    )
    assert "MIIEowI" not in redact(pem)


def test_email_is_redacted() -> None:
    assert "person@example.com" not in redact("person@example.com")
