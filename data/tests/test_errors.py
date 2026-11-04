from varde_data.errors import Conflict, DataError, Invalid, Locked, NotFound


def test_public_errors_share_backend_independent_base() -> None:
    assert all(
        issubclass(error, DataError) for error in (NotFound, Invalid, Conflict, Locked)
    )
