from varde_data.queue_line import QUEUE_LINE_PATTERN
from varde_workflow.queue_check import _QUEUE_LINE


def test_workflow_regex_matches_data_queue_codec() -> None:
    assert QUEUE_LINE_PATTERN.pattern == _QUEUE_LINE.pattern
