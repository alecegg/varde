import json

import pytest
from varde.json_order import (
    RemoveOptions,
    append_entry,
    remove_matching_commands,
    remove_matching_commands_with_options,
    replace_owned_entries,
    replace_owned_entries_from_json,
)


def test_append_preserves_order_and_raw_foreign_entries():
    source = (
        '{"z_last": { "nested" : {"b": 2, "a": 1} }, '
        '"hooks": {"Stop" : [ { "z": 0, "command" : "echo keep", "a": 1 } ], '
        '"PreToolUse": [{"hooks":[{"command":"foreign"}]}]}, '
        '"a_first": [1, 2]}'
    )
    result = append_entry(
        source, "SessionStart", {"type": "command", "command": "varde hook"}
    )
    assert (
        result.index('"z_last"') < result.index('"hooks"') < result.index('"a_first"')
    )
    assert (
        result.index('"Stop"')
        < result.index('"PreToolUse"')
        < result.index('"SessionStart"')
    )
    assert '{ "nested" : {"b": 2, "a": 1} }' in result
    assert '{ "z": 0, "command" : "echo keep", "a": 1 }' in result
    assert result.endswith("\n")


def test_append_into_empty_hooks():
    result = append_entry(
        '{"z_last":1,"hooks":{},"a_first":2}', "SessionStart", {"command": "owned"}
    )
    assert (
        result.index('"z_last"') < result.index('"hooks"') < result.index('"a_first"')
    )
    assert '"SessionStart"' in result


def test_remove_command_in_group_keeps_foreign_sibling_and_field_order():
    source = (
        '{"hooks":{"SessionStart":[{"metadata":{"y":1,"x":2},'
        '"hooks":[{"type":"command","command":"owned"},'
        '{"type":"command","command":"foreign"}],"tail":3}],'
        '"Stop":[{"z":1,"a":2}]}}'
    )
    result, removed = remove_matching_commands(
        source, "SessionStart", lambda command: command == "owned"
    )
    assert removed == ["owned"]
    metadata = result.index('"metadata"')
    assert metadata < result.index('"hooks"', metadata) < result.index('"tail"')
    assert result.index('"y": 1') < result.index('"x": 2')
    assert '"command": "foreign"' in result and '"Stop"' in result


def test_remove_last_event_and_optional_prune():
    source = '{"z-last":1,"hooks":{"SessionStart":[{"command":"owned"}]} ,"a-first":2}'
    normal, removed = remove_matching_commands(
        source, "SessionStart", lambda command: command == "owned"
    )
    assert removed == ["owned"] and json.loads(normal)["hooks"] == {}
    pruned, removed = remove_matching_commands_with_options(
        source, "SessionStart", lambda command: command == "owned", RemoveOptions(True)
    )
    assert removed == ["owned"]
    assert pruned == '{\n  "z-last": 1,\n  "a-first": 2\n}\n'


def test_replace_owned_entries():
    source = (
        '{"hooks":{"SessionStart":[{"hooks":[{"command":"old"},'
        '{"command":"foreign"}]}],"Stop":[{"z":1,"a":2}]}}'
    )
    result, removed = replace_owned_entries(
        source, "SessionStart", lambda command: command == "old", [{"command": "new"}]
    )
    assert removed == ["old"] and '"new"' in result and '"foreign"' in result
    assert result.index('"SessionStart"') < result.index('"Stop"')


def test_untouched_compact_entry_is_byte_exact():
    foreign = '{ "z":0,"command" : "foreign","a":[1,  2] }'
    source = '{"hooks":{"Stop":[' + foreign + ',{"command":"owned"}]}}'
    result, removed = replace_owned_entries(
        source, "Stop", lambda command: command == "owned", [{"command": "new"}]
    )
    assert (
        removed == ["owned"]
        and foreign in result
        and '"new"' in result
        and "owned" not in result
    )


def test_replacement_field_order_and_idempotence():
    replacement = '{"hooks":[{"type":"command","command":"owned","timeout":20}]}'
    result, removed = replace_owned_entries_from_json(
        '{"hooks":{}}',
        "SessionStart",
        lambda _: False,
        '{"hooks":{"SessionStart":[' + replacement + "]}}",
        "SessionStart",
    )
    assert not removed
    assert result == (
        '{\n  "hooks": {\n    "SessionStart": [\n      {\n'
        '        "hooks": [\n          {\n            "type": "command",\n'
        '            "command": "owned",\n            "timeout": 20\n'
        "          }\n        ]\n      }\n    ]\n  }\n}\n"
    )
    base = (
        '{"hooks":{"SessionStart":[{"matcher":"*","hooks":'
        '[{"type":"command","command":"foreign"}]},'
        '{"type":"command","command":"owned"}]}}'
    )
    one, _ = replace_owned_entries(
        base,
        "SessionStart",
        lambda x: x == "owned",
        [{"type": "command", "command": "owned"}],
    )
    two, _ = replace_owned_entries(
        one,
        "SessionStart",
        lambda x: x == "owned",
        [{"type": "command", "command": "owned"}],
    )
    assert one == two


def test_replacement_document_preserves_order():
    result, removed = replace_owned_entries_from_json(
        '{"hooks":{}}',
        "PostToolUse",
        lambda _: False,
        '{"hooks":{"PostToolUse":[{"type":"command","command":"owned"}]}}',
        "PostToolUse",
    )
    assert not removed
    assert '"type": "command",\n        "command": "owned"' in result


def test_repeated_edits_keep_multiline_foreign_slices_verbatim():
    foreign = '{\n   "command": "foreign",\n        "nested": {\n  "x": 1\n        }\n}'
    stop = '[\n  {\n   "command": "stop-foreign"\n  }\n]'
    source = '{"hooks":{"SessionStart":[' + foreign + '],"Stop":' + stop + "}}"
    once = append_entry(source, "SessionStart", {"command": "owned"})
    twice = append_entry(once, "SessionStart", {"command": "owned-again"})
    assert foreign in once and foreign in twice
    assert stop in twice


@pytest.mark.parametrize(
    "document",
    [
        '{"hooks": ',
        '{"hooks":[1]}',
        '{"hooks":{',
        '{"hooks":{}} trailing',
        '{"hooks":{"E": [NaN]}}',
        '{"hooks":{"E":[1e999]}}',
        '{"hooks":{"E":["\\ud800"]}}',
    ],
)
def test_malformed_documents_raise_value_error(document):
    with pytest.raises(ValueError):
        append_entry(document, "E", {"command": "new"})


@pytest.mark.parametrize(
    "document", ['{"hooks":[1]}', '{"hooks":{"E":3}}', '{"hooks":{"E":null}}']
)
def test_invalid_hooks_or_event_shapes_raise_value_error(document):
    with pytest.raises(ValueError):
        remove_matching_commands(document, "E", lambda _: True)


def test_scalar_exponents_use_jsonio_format():
    result = append_entry('{"hooks":{}}', "E", {"large": 1e21})
    assert '"large": 1e21' in result
