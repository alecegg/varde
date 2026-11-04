"""Reader behavior for facts-1 and facts-2 records."""

import pytest
from varde_code.quality_pass.facts import extract_facts, normalize_record

OLD_RECORD = {
    "contract": "facts-1",
    "path": "src/a.py",
    "language": "python",
    "content_hash": "blake2b-00",
    "tokens": 9,
    "excluded": None,
    "import_fan_out": None,
    "functions": [
        {
            "id": "src/a.py::run#1",
            "name": "run",
            "owner": None,
            "line": 1,
            "end_line": 2,
            "tokens": 4,
            "params": 0,
            "cognitive": 0,
            "exempt_role": None,
            "file_private": False,
        }
    ],
    "data_functions": [],
    "call_sites": [],
    "call_coverage": None,
    "unresolved_share": None,
    "structure_confidence": None,
    "diagnostics": [],
}

NEW_RECORD = {
    "contract": "facts-2",
    "path": "src/a.cpp",
    "language": "cpp",
    "tokens": 12,
    "markers": ["generated"],
    "comment_parity": {"tokens": 12, "comment_tokens": 3},
    "unmeasured_regions": [{"kind": "template", "start_line": 1, "end_line": 2}],
    "functions": [{"id": "src/a.cpp::Matrix.get#1", "overload_pair": None}],
}


def test_facts_1_record_is_upgraded_with_neutral_optional_fields():
    normalized = normalize_record(OLD_RECORD)

    assert normalized["contract"] == "facts-2"
    assert normalized["markers"] == []
    assert normalized["comment_parity"] == {"tokens": 9, "comment_tokens": 0}
    assert normalized["unmeasured_regions"] == []
    assert normalized["functions"][0]["overload_pair"] is None
    assert normalized["functions"][0]["name"] == "run"
    assert normalized["path"] == "src/a.py"


def test_normalizing_does_not_mutate_the_input_record():
    normalized = normalize_record(OLD_RECORD)

    assert normalized is not OLD_RECORD
    assert OLD_RECORD["contract"] == "facts-1"
    assert "markers" not in OLD_RECORD
    assert "overload_pair" not in OLD_RECORD["functions"][0]


def test_facts_2_record_keeps_its_optional_fields():
    normalized = normalize_record(NEW_RECORD)

    assert normalized["markers"] == ["generated"]
    assert normalized["comment_parity"] == {"tokens": 12, "comment_tokens": 3}
    assert normalized["unmeasured_regions"] == [
        {"kind": "template", "start_line": 1, "end_line": 2}
    ]
    assert normalized["functions"][0]["overload_pair"] is None


def test_facts_2_record_without_optional_fields_gets_defaults():
    normalized = normalize_record({"contract": "facts-2", "tokens": 3, "functions": []})

    assert normalized["markers"] == []
    assert normalized["comment_parity"] == {"tokens": 3, "comment_tokens": 0}
    assert normalized["unmeasured_regions"] == []
    assert normalized["functions"] == []


@pytest.mark.parametrize("contract", ["facts-3", "", None])
def test_unknown_contract_strings_are_rejected(contract):
    with pytest.raises(ValueError):
        normalize_record({"contract": contract, "functions": []})


def test_record_without_functions_does_not_gain_the_key():
    normalized = normalize_record({"contract": "facts-1", "tokens": 3})

    assert "functions" not in normalized
    assert normalized["comment_parity"] == {"tokens": 3, "comment_tokens": 0}


def test_producer_output_is_already_normalized():
    record = extract_facts("def run():\n    return 1\n", "python", "src/a.py")

    assert record["contract"] == "facts-2"
    assert normalize_record(record) == record
