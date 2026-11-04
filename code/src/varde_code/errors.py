"""Errors returned by varde-code operations."""


class ApiError(Exception):
    """Stable machine readable code paired with a human message."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message

    @classmethod
    def not_found(cls, what: object) -> ApiError:
        return cls("not_found", f"not found: {what}")
