"""Loopback HTTP calls that ignore proxy settings."""

from __future__ import annotations

import urllib.request
from typing import Any

_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def open_local(request: urllib.request.Request, timeout: float) -> Any:
    """Open a request to the daemon without HTTP(S)_PROXY ever applying."""
    return _OPENER.open(request, timeout=timeout)
