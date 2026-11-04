"""Build a one-version quality-corpus item from a seeded-judge sample."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

SAMPLES = {
    "python": (".py", ()),
    "typescript": (".ts", ()),
    "go": (".go", ("go.mod",)),
    "java": (".java", ()),
    "csharp": (".cs", ("qssample.csproj",)),
}


def build_sample_item(sample_dir: Path, out_item_dir: Path) -> None:
    """Copy a sample's smoothed source and harness files into an item directory."""
    language = sample_dir.name
    if language not in SAMPLES:
        raise ValueError(f"unsupported sample language: {language}")
    extension, metadata = SAMPLES[language]
    required = (f"smoothed{extension}", f"behaviour_test{extension}")
    missing = [
        name for name in (*required, *metadata) if not (sample_dir / name).is_file()
    ]
    if missing:
        raise ValueError(f"sample is missing required files: {', '.join(missing)}")

    out_item_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(sample_dir / required[0], out_item_dir / f"sensible{extension}")
    shutil.copyfile(sample_dir / required[1], out_item_dir / required[1])
    for name in metadata:
        shutil.copyfile(sample_dir / name, out_item_dir / name)
    (out_item_dir / "spec-profile.toml").write_text('profile = "layered"\n')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("sample_dir", type=Path)
    parser.add_argument("out_item_dir", type=Path)
    args = parser.parse_args(argv)
    try:
        build_sample_item(args.sample_dir, args.out_item_dir)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
