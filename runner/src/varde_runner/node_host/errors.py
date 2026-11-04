"""Errors raised to callers of a NodeHost."""

from __future__ import annotations


class NodeHostError(Exception):
    """Base class: the host could not start, or a frame was unusable."""


class HostRestarted(NodeHostError):
    """The host child died or is restarting; the call was not replayed."""


class HostDown(NodeHostError):
    """The host is stopped or gave up restarting."""


class CallTimeout(NodeHostError):
    """The host did not reply in time; the host keeps running."""


class FrameTooLarge(NodeHostError):
    """A frame exceeds the 16 MiB line limit."""


class HostCallError(NodeHostError):
    """The engine replied with an error frame."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
