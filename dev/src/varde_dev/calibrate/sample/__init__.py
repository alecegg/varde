"""Built-in calibration examples for Python, TypeScript, and C# pairs."""

from pathlib import Path


def dataset_dir() -> Path:
    """Return the packaged pair-export directory used by ``import --sample``."""
    return Path(__file__).with_name("data")
