"""Run the language ground-truth exporters over pinned repository checkouts."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tomllib
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from export import CALL_CLASSES, resolve_rust_scip, rust_candidates

HERE = Path(__file__).resolve().parent
REPOS = HERE.parents[1] / "repos" / "go-rust.toml"
ENV_ROOT = HERE.parents[1] / "envs" / "go-rust"


@dataclass(frozen=True)
class RustScip:
    """The Rust analyzer binary, its index directory, and index reuse."""

    analyzer: Path
    directory: Path
    reuse: bool


def pinned_repos() -> list[dict[str, object]]:
    with REPOS.open("rb") as stream:
        return tomllib.load(stream)["repo"]


def collect(
    cache: Path,
    output: Path,
    language_filter: str | None,
    rust_resolution: str,
    rust_scip: RustScip,
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    counts: Counter[str] = Counter()
    with output.open("w") as stream:
        for repo in pinned_repos():
            language = str(repo["language"])
            if language_filter and language != language_filter:
                continue
            name = str(repo["name"])
            checkout = cache / name.rsplit("/", 1)[-1]
            sha = subprocess.run(
                ["git", "-C", str(checkout), "rev-parse", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            if sha != repo["sha"]:
                raise ValueError(f"{name} checkout is {sha}, expected {repo['sha']}")
            env = dict(__import__("os").environ)
            if language == "rust":
                env["RUST_ANALYZER"] = str(rust_scip.analyzer)
            if language == "rust" and rust_resolution == "scip":
                rust_scip.directory.mkdir(parents=True, exist_ok=True)
                index_path = rust_scip.directory / f"{checkout.name}.scip"
                if not (rust_scip.reuse and index_path.is_file()):
                    subprocess.run(
                        [
                            str(rust_scip.analyzer),
                            "scip",
                            str(checkout),
                            "--output",
                            str(index_path),
                            "--exclude-vendored-libraries",
                        ],
                        check=True,
                        env=env,
                    )
                sites = resolve_rust_scip(
                    checkout, rust_candidates(checkout, name), index_path
                )
                for site in sites:
                    if site["call_class"] not in CALL_CLASSES:
                        continue
                    stream.write(
                        json.dumps(
                            {
                                key: value
                                for key, value in site.items()
                                if not key.startswith("_")
                            },
                            sort_keys=True,
                        )
                        + "\n"
                    )
                    counts[language] += 1
                print(
                    f"{name}: {counts[language]} candidate rows accumulated",
                    file=sys.stderr,
                )
                continue
            proc = subprocess.Popen(
                [
                    sys.executable,
                    str(HERE / "export.py"),
                    language,
                    str(checkout),
                    name,
                ],
                stdout=subprocess.PIPE,
                env=env,
            )
            assert proc.stdout is not None  # noqa: S101 - PIPE configuration guarantees a stdout stream.
            for line in proc.stdout:
                stream.write(line.decode())
                if line.strip():
                    counts[language] += 1
            status = proc.wait()
            if status:
                raise subprocess.CalledProcessError(status, proc.args)
            print(
                f"{name}: {counts[language]} candidate rows accumulated",
                file=sys.stderr,
            )
    print(json.dumps(dict(counts), sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", type=Path, default=ENV_ROOT / "pins")
    parser.add_argument("--language", choices=("go", "rust"))
    parser.add_argument("--rust-resolution", choices=("lsp", "scip"), default="lsp")
    parser.add_argument("--scip-dir", type=Path, default=ENV_ROOT / "scip")
    parser.add_argument("--output", type=Path, default=ENV_ROOT / "candidates.jsonl")
    parser.add_argument(
        "--rust-analyzer",
        type=Path,
        default=ENV_ROOT
        / "rustup"
        / "toolchains"
        / "stable-aarch64-apple-darwin"
        / "bin"
        / "rust-analyzer",
    )
    parser.add_argument(
        "--reuse-scip",
        action="store_true",
        help="resolve existing SCIP indexes instead of re-indexing each repository",
    )
    args = parser.parse_args()
    collect(
        args.cache,
        args.output,
        args.language,
        args.rust_resolution,
        RustScip(args.rust_analyzer, args.scip_dir, args.reuse_scip),
    )


if __name__ == "__main__":
    main()
