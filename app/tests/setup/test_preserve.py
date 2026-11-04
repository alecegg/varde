import pytest
from varde.setup.sync.harness import HarnessId
from varde.setup.sync.preserve import dry_run, preserve_models


def test_fresh_markdown_adds_default_record():
    actual, keys = preserve_models(
        HarnessId.CLAUDE,
        "varde-planner",
        '---\ndescription: Planner\nmodel: "new"\n---\nbody\n',
        None,
    )
    assert actual.endswith('<!-- varde-default: model: "new" -->\n')
    assert keys == []


def test_custom_markdown_model_is_preserved():
    staged = '---\ndescription: Planner\nmodel: "new"\n---\nbody\n'
    installed = '---\ndescription: Planner\nmodel: "mine"\n---\n'
    actual, keys = preserve_models(HarnessId.CLAUDE, "varde-planner", staged, installed)
    assert 'model: "mine"' in actual
    assert keys == ["model"]


def test_unrecorded_unknown_markdown_model_is_preserved():
    staged = '---\ndescription: Planner\nmodel: "new"\n---\n'
    installed = '---\ndescription: Planner\nmodel: "old"\n---\n'
    actual, keys = preserve_models(HarnessId.CLAUDE, "varde-planner", staged, installed)
    assert 'model: "old"' in actual
    assert keys == ["model"]


def test_recorded_markdown_default_updates():
    staged = '---\ndescription: Planner\nmodel: "new"\n---\n'
    installed = (
        '---\ndescription: Planner\nmodel: "old"\n---\n'
        '<!-- varde-default: model: "old" -->\n'
    )
    actual, _ = preserve_models(HarnessId.CLAUDE, "varde-planner", staged, installed)
    assert 'model: "new"' in actual


def test_dry_run_reports_custom_model():
    staged = '---\nmodel: "new"\n---\n'
    installed = '---\nmodel: "mine"\n---\n'
    assert dry_run(HarnessId.CLAUDE, "varde-planner", staged, installed) == ["model"]


def test_dry_run_without_installed_file_is_empty():
    assert dry_run(HarnessId.CLAUDE, "varde-planner", "", None) == []


def test_codex_preserves_user_values_and_updates_defaults():
    staged = (
        'model = "new"\nmodel_reasoning_effort = "medium"\n'
        'developer_instructions = "new body"\n'
    )
    installed = (
        'model = "mine"\nmodel_reasoning_effort = "high"\n'
        'developer_instructions = "old"\n'
    )
    actual, keys = preserve_models(HarnessId.CODEX, "varde-planner", staged, installed)
    assert actual.startswith('model = "mine"\nmodel_reasoning_effort = "high"')
    assert keys == ["model", "model_reasoning_effort"]


def test_codex_only_headers_are_considered():
    staged = 'model = "new"\n[other]\nmodel = "nested"\n'
    actual, _ = preserve_models(HarnessId.CODEX, "varde-planner", staged, None)
    assert actual.count("varde-default: model =") == 1


def test_pi_keeps_custom_model():
    staged = "---\ndescription: Agent\n---\n"
    installed = '---\ndescription: Agent\nmodel: "mine"\n---\n'
    actual, keys = preserve_models(HarnessId.PI, "varde-planner", staged, installed)
    assert 'model: "mine"' in actual
    assert keys == ["model"]


def test_pi_historical_pin_is_removed():
    staged = "---\ndescription: Agent\n---\n"
    installed = '---\ndescription: Agent\nmodel: "deepseek/deepseek-v4-flash"\n---\n'
    actual, keys = preserve_models(HarnessId.PI, "varde-planner", staged, installed)
    assert "model:" not in actual
    assert keys == []


def test_removed_markdown_model_keeps_custom_value():
    staged = "---\ndescription: Agent\n---\n"
    installed = (
        '---\ndescription: Agent\nmodel: "mine"\n---\n'
        '<!-- varde-default: model: "old" -->\n'
    )
    actual, keys = preserve_models(HarnessId.CLAUDE, "varde-planner", staged, installed)
    assert 'model: "mine"' in actual
    assert keys == ["model"]


def test_removed_recorded_default_does_not_reappear():
    staged = "---\ndescription: Agent\n---\n"
    installed = '---\ndescription: Agent\n---\n<!-- varde-default: model: "old" -->\n'
    actual, keys = preserve_models(HarnessId.CLAUDE, "varde-planner", staged, installed)
    assert "model:" not in actual
    assert keys == []


@pytest.mark.parametrize(
    "harness", [HarnessId.CLAUDE, HarnessId.OPENCODE, HarnessId.PI]
)
def test_markdown_format_used_for_non_codex(harness):
    staged = '---\nmodel: "ship"\n---\n'
    actual, _ = preserve_models(harness, "varde-agent", staged, None)
    assert "<!-- varde-default:" in actual


def test_custom_value_with_record_is_preserved():
    staged = '---\nmodel: "ship"\n---\n'
    installed = '---\nmodel: "custom"\n---\n<!-- varde-default: model: "old" -->\n'
    actual, keys = preserve_models(HarnessId.OPENCODE, "varde-agent", staged, installed)
    assert 'model: "custom"' in actual
    assert keys == ["model"]
