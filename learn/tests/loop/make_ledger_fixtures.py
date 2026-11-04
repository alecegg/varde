"""Build small input fixtures for the ledger golden tests."""

from __future__ import annotations

from pathlib import Path

FIXTURES = Path(__file__).parents[3] / "data" / "tests" / "fixtures" / "ledger"


def main() -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    (FIXTURES / "analyzed.jsonl").write_bytes(
        b'{"session":"same","harness":"codex","analyzed_at":"old","summary":"old"}\n'
        b"not json\n"
        b"\n"
        b"[1]\n"
        b'{"session":"bad","harness":4,"analyzed_at":"now"}\n'
        b'{"session":"missing","harness":"codex"}\n'
        b'{"session":"other","harness":"codex","analyzed_at":"then","summary":"other"}\n'
        b'{"session":"same","harness":"claude","analyzed_at":"claude","summary":"separate"}\n'
        b'{"session":"same","harness":"codex","analyzed_at":"new","summary":"latest"}\n'
        b'{"session":"tail"'
    )
    digests = FIXTURES / "digests"
    digests.mkdir(exist_ok=True)
    (digests / "2026-10-24.json").write_text(
        '{\n  "date": "2026-10-24",\n  "text": "fixture digest",\n'
        '  "candidates": [{"title": "One"}]\n}\n',
        encoding="utf-8",
    )
    (digests / "wrong-shape.json").write_text('["not", "an", "object"]\n')
    (digests / "invalid.json").write_text("not json\n")
    (digests / "no-text.json").write_text('{"candidates": []}\n')
    (digests / "non-string-text.json").write_text('{"text": 7}\n')
    (digests / "no-candidates.json").write_text('{"text": "text only"}\n')
    # A directory at the expected path deterministically produces the same
    # read error as an unreadable file, including when tests run as root.
    unreadable = digests / "unreadable.json"
    unreadable.mkdir(exist_ok=True)
    (unreadable / ".keep").touch()
    configs = FIXTURES / "configs"
    configs.mkdir(exist_ok=True)
    values = {
        "valid.toml": (
            'repos = ["~/source/demo"]\n[summary]\nenabled = true\ntoken_cap = 42\n'
        ),
        "bad-repos.toml": 'repos = "~/source/demo"\n',
        "bad-repos-item.toml": "repos = [1]\n",
        "bad-summary.toml": 'repos = []\nsummary = "bad"\n',
        "bad-enabled.toml": '[summary]\nenabled = "yes"\n',
        "bad-token-bool.toml": "[summary]\ntoken_cap = true\n",
        "bad-token-zero.toml": "[summary]\ntoken_cap = 0\n",
        "bad-token-negative.toml": "[summary]\ntoken_cap = -1\n",
        "bad-token-str.toml": '[summary]\ntoken_cap = "10"\n',
        "bad-token-float.toml": "[summary]\ntoken_cap = 1.5\n",
        "enabled-default-cap.toml": "[summary]\nenabled = true\n",
    }
    for name, value in values.items():
        (configs / name).write_text(value, encoding="utf-8")


if __name__ == "__main__":
    main()
