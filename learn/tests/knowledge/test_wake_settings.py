from varde_learn.knowledge.memory_config import (
    DEFAULT_WAKE_MAX_FAILURES,
    DEFAULT_WAKE_TIMEOUT_SECONDS,
    Config,
)


def test_wake_settings_have_defaults() -> None:
    orchestration = Config().orchestration
    assert orchestration.wake_command() == ([], None)
    assert orchestration.wake_timeout_seconds() == (DEFAULT_WAKE_TIMEOUT_SECONDS, None)
    assert orchestration.wake_max_failures() == (DEFAULT_WAKE_MAX_FAILURES, None)


def test_wake_settings_parse_valid_user_config() -> None:
    cfg = Config.from_toml(
        (  # noqa: UP034 - keep the wrapped TOML literal explicitly grouped
            '[orchestration]\nwake_command = ["agent", "resume"]\n'
            "wake_timeout_seconds = 25\nwake_max_failures = 5\n"
        )
    )
    assert cfg.orchestration.wake_command() == (["agent", "resume"], None)
    assert cfg.orchestration.wake_timeout_seconds() == (25, None)
    assert cfg.orchestration.wake_max_failures() == (5, None)


def test_invalid_wake_settings_fall_back_with_reasons() -> None:
    for bad in ["0", "-2", '"soon"', "1.5"]:
        cfg = Config.from_toml(f"[orchestration]\nwake_timeout_seconds = {bad}\n")
        value, reason = cfg.orchestration.wake_timeout_seconds()
        assert value == DEFAULT_WAKE_TIMEOUT_SECONDS and reason
        cfg = Config.from_toml(f"[orchestration]\nwake_max_failures = {bad}\n")
        value, reason = cfg.orchestration.wake_max_failures()
        assert value == DEFAULT_WAKE_MAX_FAILURES and reason

    cfg = Config.from_toml('[orchestration]\nwake_command = ["agent", 2]\n')
    command, reason = cfg.orchestration.wake_command()
    assert command == [] and reason


def test_non_array_wake_command_falls_back_with_reason() -> None:
    cfg = Config.from_toml('[orchestration]\nwake_command = "agent resume"\n')
    assert cfg.orchestration.wake_command() == (
        [],
        '"agent resume" is not an array of strings',
    )


def test_non_table_orchestration_is_lenient() -> None:
    cfg = Config.from_toml('orchestration = "bad"\n')
    assert cfg.orchestration.wake_timeout_seconds() == (
        DEFAULT_WAKE_TIMEOUT_SECONDS,
        "`orchestration` is not a table",
    )
