"""The installed serve version, compared by shim and daemon."""

from importlib import metadata


def serve_version() -> str:
    try:
        return metadata.version("varde-serve")
    except metadata.PackageNotFoundError:
        return "0"
