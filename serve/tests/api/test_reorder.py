import pytest
from varde_serve.api import write
from varde_serve.api.errors import ApiError
from varde_serve.project import Project


def test_reorder_is_501_until_wired_to_the_runner_order(tmp_path) -> None:
    project = Project(tmp_path / "cfg", tmp_path, tmp_path)
    with pytest.raises(ApiError) as caught:
        write.reorder_queue(project)
    assert (caught.value.status, caught.value.code) == (501, "reorder_not_wired")
