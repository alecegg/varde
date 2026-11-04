"""Generate held-out mutants from a local clean-source directory."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Sequence
from pathlib import Path

CORPUS_ROOT = Path(__file__).resolve().parents[2]
if str(CORPUS_ROOT) not in sys.path:
    sys.path.insert(0, str(CORPUS_ROOT))

from mutations.python import OPERATORS as PYTHON_OPERATORS  # noqa: E402, RUF100 - corpus root must be on sys.path first
from mutations.python import mutate as mutate_python  # noqa: E402, RUF100 - corpus root must be on sys.path first
from mutations.typescript import OPERATORS as TYPESCRIPT_OPERATORS  # noqa: E402, RUF100 - corpus root must be on sys.path first
from mutations.typescript import mutate as mutate_typescript  # noqa: E402, RUF100 - corpus root must be on sys.path first


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--language", choices=("python", "typescript"), required=True)
    parser.add_argument(
        "--operator",
        choices=tuple(sorted(set(PYTHON_OPERATORS) | set(TYPESCRIPT_OPERATORS))),
        required=True,
    )
    parser.add_argument("--seed", type=int)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    operators = PYTHON_OPERATORS if args.language == "python" else TYPESCRIPT_OPERATORS
    if args.operator not in operators:
        parser.error(f"{args.operator} is not supported for {args.language}")
    if not args.input_dir.is_dir():
        parser.error(f"input directory does not exist: {args.input_dir}")
    extension = ".py" if args.language == "python" else ".ts"
    inputs = sorted(
        path for path in args.input_dir.rglob(f"*{extension}") if path.is_file()
    )
    if not inputs:
        parser.error(f"no {extension} source files found in {args.input_dir}")
    mutate = mutate_python if args.language == "python" else mutate_typescript
    errors = 0
    for path in inputs:
        try:
            relative = path.relative_to(args.input_dir)
            source = path.read_text()
            pair_id = _pair_group_id(relative, source)
            result = mutate(args.operator, source, pair_id, args.seed)
            output = (
                args.out
                / relative.parent
                / f"{relative.stem}.{args.operator}.mutant{extension}"
            )
            metadata_path = output.with_suffix(".json")
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(result.source)
            artifact = result.to_dict()
            artifact.pop("source", None)
            artifact["base_path"] = relative.as_posix()
            artifact["metadata_path"] = metadata_path.name
            metadata_path.write_text(
                json.dumps(artifact, indent=2, sort_keys=True) + "\n"
            )
        except (OSError, RuntimeError, SyntaxError, ValueError) as exc:
            errors += 1
            print(f"could not write mutation for {relative}: {exc}", file=sys.stderr)
    return 1 if errors else 0


def _pair_group_id(relative: Path, source: str) -> str:
    digest = hashlib.blake2b(digest_size=12)
    digest.update(relative.as_posix().encode())
    digest.update(b"\0")
    digest.update(source.encode())
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
