"""The call row type, the table columns and the hook row type must agree."""

from __future__ import annotations

from varde.glue import hook_record
from varde_data.calls_store import COLUMNS, connect
from varde_learn.loop import calls


def table_columns(tmp_path) -> set[str]:
    db = connect(tmp_path)
    try:
        return {row[1] for row in db.execute("PRAGMA table_info(cli_calls)")} - {"id"}
    finally:
        db.close()


def test_call_row_keys_equal_the_table_columns(tmp_path) -> None:
    keys = set(calls.CallRow.__annotations__) - {"retry"}
    assert keys == table_columns(tmp_path)
    assert keys == set(COLUMNS)


def test_hook_row_keys_are_columns(tmp_path) -> None:
    # hook rows never carry `arg`, so their keys are a subset of the columns
    assert set(hook_record.CallRow.__annotations__) <= table_columns(tmp_path)


def test_hook_row_keys_are_the_columns_minus_arg() -> None:
    # exact match: a dropped status or duration_s would make typed_row reject the row
    assert set(hook_record.CallRow.__annotations__) == set(COLUMNS) - {"arg"}
