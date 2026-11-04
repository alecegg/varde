import json

from varde_learn.knowledge import cmdbase
from varde_workflow import errors


def test_workflow_error_reporting_adds_fix(capsys):
    status = errors.report_error_with_fix(
        "ownership_stray", 1, "stray file", cmdbase.Fix.no_command("update owns"), True
    )
    result = json.loads(capsys.readouterr().err)
    assert status == 1
    assert result["data"]["error"]["fix"] == {"reason": "update owns"}


def test_workflow_failure_reporting_adds_fix(capsys):
    status = errors.report_failure_with_fix(
        "ownership_stray",
        1,
        "stray file",
        {"paths": ["x"]},
        cmdbase.Fix("update owns"),
        True,
    )
    result = json.loads(capsys.readouterr().out)
    assert status == 1
    assert result["data"]["error"]["fix"] == {"reason": "update owns"}
