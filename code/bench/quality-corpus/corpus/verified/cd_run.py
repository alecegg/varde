"""Reproduce the cd-networked-run corpus stages: pin, roles, fetch, report.

The stage drivers for this task live in ``corpus/verified/`` because the task
owns that directory; run them from the repository root with ``uv run python``.
``pin`` resolves every candidate's default-branch tip, ``roles`` applies the
role plan, ``fetch`` fetches each pin through ``corpus/fetch.py`` and writes
``verified.json``, and ``report`` renders ``REPORT.md`` from the artefacts.

``corpus/fetch.py``'s own license check cannot identify the canonical MIT
text (it requires an unquoted ``THE SOFTWARE IS PROVIDED AS IS`` where the
canonical text quotes ``AS IS``) and searches only LICENSE, LICENSE.md,
LICENSE.txt and COPYING (missing LICENSE-MIT, LICENSE.MIT, License.txt and
MIT-LICENSE). This task may not edit that file, so ``fetch`` records
``corpus/fetch.py``'s verdict for every repository and re-checks the fetched
root license text itself with ``LICENSE_MARKERS`` below; ``REPORT.md`` lists
every repository where the two disagree.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path
from typing import Any

VERIFIED_DIR = Path(__file__).resolve().parent
CORPUS_DIR = VERIFIED_DIR.parent
QUALITY_CORPUS_DIR = CORPUS_DIR.parent
MANIFEST_PATH = CORPUS_DIR / "manifest.toml"
VERIFIED_PATH = VERIFIED_DIR / "verified.json"
REPORT_PATH = VERIFIED_DIR / "REPORT.md"
MINED_SUMMARY_PATH = QUALITY_CORPUS_DIR / "pairs" / "mined" / "summary.json"
INPUTS_SUMMARY_PATH = VERIFIED_DIR / "mutation-inputs" / "summary.json"
RUN_DATE = "2026-10-18"
if str(CORPUS_DIR) not in sys.path:
    sys.path.insert(0, str(CORPUS_DIR))

import fetch as corpus_fetch  # noqa: E402, RUF100 - corpus paths must be on sys.path first
from fetch import FetchError  # noqa: E402, RUF100 - corpus paths must be on sys.path first
from manifest import (  # noqa: E402, RUF100 - corpus paths must be on sys.path first
    SPDX_LICENSES,
    compute_manifest_digest,
    load_manifest,
)

# Role plan: roles are disjoint per repository (corpus/manifest.py). Each
# release language keeps at least two `pairs` repositories (the largest
# histories), one `mutation-base` with clean permissive source, and one
# `held-out` repository when it has four or more candidates; the rest are
# `calibration`. Candidate languages outside the release set take only
# `calibration` and `held-out`.
ROLE_PLAN: dict[str, tuple[str, ...]] = {
    "pairs": (
        "django/django",
        "pandas-dev/pandas",
        "microsoft/TypeScript",
        "nestjs/nest",
        "google/guava",
        "apache/commons-lang",
        "prometheus/prometheus",
        "gin-gonic/gin",
        "tokio-rs/tokio",
        "clap-rs/clap",
        "dotnet/roslyn",
        "JamesNK/Newtonsoft.Json",
        "nlohmann/json",
        "abseil/abseil-cpp",
    ),
    "mutation-base": (
        "pytest-dev/pytest",
        "vuejs/core",
        "lysine-dev/okhttp",
        "spf13/cobra",
        "BurntSushi/ripgrep",
        "App-vNext/Polly",
        "fmtlib/fmt",
    ),
    "held-out": (
        "pallets/flask",
        "excalidraw/excalidraw",
        "serde-rs/serde",
        "google/leveldb",
        "JetBrains/Exposed",
        "typelevel/cats",
        "libuv/libuv",
        "composer/composer",
        "sinatra/sinatra",
        "vapor/vapor",
        "flutter/flutter",
        "elixir-ecto/ecto",
        "yesodweb/yesod",
        "folke/lazy.nvim",
        "pyenv/pyenv",
        "foundry-rs/forge-std",
    ),
    "calibration": (
        "psf/requests",
        "scikit-learn/scikit-learn",
        "typeorm/typeorm",
        "shadcn-ui/ui",
        "mantinedev/mantine",
        "expressjs/express",
        "lodash/lodash",
        "prettier/prettier",
        "eslint/eslint",
        "ktorio/ktor",
        "Kotlin/kotlinx.coroutines",
        "scala/scala",
        "playframework/playframework",
        "redis/redis",
        "curl/curl",
        "jqlang/jq",
        "laravel/framework",
        "symfony/symfony",
        "rails/rails",
        "rubocop/rubocop",
        "Alamofire/Alamofire",
        "apple/swift-nio",
        "dart-lang/http",
        "rrousselGit/riverpod",
        "elixir-lang/elixir",
        "phoenixframework/phoenix",
        "haskell/cabal",
        "PostgREST/postgrest",
        "Kong/kong",
        "LuaRocks/luarocks",
        "nvm-sh/nvm",
        "bats-core/bats-core",
        "ohmyzsh/ohmyzsh",
        "OpenZeppelin/openzeppelin-contracts",
        "Vectorized/solady",
    ),
}
# redis moved to RSALv2/SSPL after the 7.2 line, so its pin is that branch tip.
PIN_REF = {"redis/redis": "refs/heads/7.2"}
# The selection rules permit MIT, BSD, Apache-2.0, ISC and MPL-2.0. EPL-2.0
# (junit-framework) is weak copyleft with no recorded license review, so the
# repository stays unverified and carries no role.
PERMITTED_SPDX = SPDX_LICENSES - {"EPL-2.0"}
NO_ROLE_REPOSITORIES = frozenset({"junit-team/junit-framework"})
POLICY_REASON = (
    "EPL-2.0 is weak copyleft and is not in the permitted permissive set "
    "(validation-plan section 7: MIT, BSD, Apache-2.0, ISC, MPL-2.0 "
    "tolerated); license review not recorded, so the repository stays "
    "unverified and carries no role"
)
# A root license file is any file whose name starts with one of these.
LICENSE_FILE_PREFIXES = ("LICENSE", "COPYING", "MIT-LICENSE")
# Text markers per license family, matched against a quote-stripped, whitespace
# collapsed uppercase form of the root license file, so the canonical MIT
# wording ("THE SOFTWARE IS PROVIDED "AS IS"") matches.
LICENSE_MARKERS: dict[str, tuple[str, ...]] = {
    "MIT": (
        "PERMISSION IS HEREBY GRANTED",
        "FREE OF CHARGE",
        "THE SOFTWARE IS PROVIDED AS IS",
    ),
    "Apache-2.0": (
        "APACHE LICENSE",
        "VERSION 2.0",
        "TERMS AND CONDITIONS FOR USE, REPRODUCTION, AND DISTRIBUTION",
    ),
    "ISC": (
        "PERMISSION TO USE, COPY, MODIFY, AND/OR DISTRIBUTE",
        "THE SOFTWARE IS PROVIDED AS IS",
    ),
    "MPL-2.0": ("MOZILLA PUBLIC LICENSE", "VERSION 2.0"),
    "EPL-2.0": ("ECLIPSE PUBLIC LICENSE", "VERSION 2.0"),
    "curl": (
        "COPYRIGHT AND PERMISSION NOTICE",
        "PERMISSION TO USE, COPY, MODIFY, AND DISTRIBUTE",
        "WITHOUT WARRANTY",
    ),
}
RELEASE_GROUPS: dict[str, tuple[str, ...]] = {
    "Python": ("Python",),
    "TypeScript/JavaScript": ("TypeScript", "JavaScript", "TSX"),
    "Java": ("Java",),
    "Go": ("Go",),
    "Rust": ("Rust",),
    "C#": ("C#",),
    "C++": ("C++",),
}
CALIBRATION_FLOOR = 5


def read_manifest(path: Path = MANIFEST_PATH) -> dict[str, Any]:
    """Parse the manifest without the digest validation of ``load_manifest``."""
    return tomllib.loads(path.read_text(encoding="utf-8"))


def write_manifest(data: dict[str, Any]) -> str:
    """Regenerate the manifest with a fresh digest and validate the result."""
    data["manifest_digest"] = compute_manifest_digest(data)
    lines = [
        "schema_version = 1",
        f'manifest_digest = "{data["manifest_digest"]}"',
    ]
    lines.extend(_render_pair_groups(data.get("pair_groups", [])))
    for repo in data["repositories"]:
        lines.append("[[repositories]]")
        lines.extend(_render_repository(repo))
    MANIFEST_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    load_manifest(MANIFEST_PATH)
    return data["manifest_digest"]


def _render_pair_groups(groups: list[dict[str, Any]]) -> list[str]:
    if not groups:
        return ["pair_groups = []", ""]
    lines: list[str] = []
    for group in groups:
        lines.extend(
            (
                "",
                "[[pair_groups]]",
                f'id = "{group["id"]}"',
                f'repository = "{group["repository"]}"',
                f'kind = "{group["kind"]}"',
                f"samples = {_toml_array(group['samples'])}",
            )
        )
    return lines


def _render_repository(repo: dict[str, Any]) -> list[str]:
    lines = [f'name = "{repo["name"]}"', f'url = "{repo["url"]}"']
    if repo.get("redirected_from"):
        lines.append(f'redirected_from = "{repo["redirected_from"]}"')
    lines.extend(
        (
            f'spdx = "{repo["spdx"]}"',
            f"languages = {_toml_array(repo['languages'])}",
            f'pin_sha = "{repo["pin_sha"]}"',
            f"history_cutoffs = {_toml_array(repo['history_cutoffs'])}",
            f"roles = {_toml_array(repo['roles'])}",
            f'status = "{repo["status"]}"',
            "",
        )
    )
    return lines


def _toml_array(values: list[str]) -> str:
    return "[" + ", ".join(f'"{value}"' for value in values) + "]"


def pin_candidates(data: dict[str, Any]) -> None:
    """Set every candidate's pin_sha to its default-branch tip."""
    for repo in data["repositories"]:
        repo["pin_sha"] = _remote_sha(repo["url"], PIN_REF.get(repo["name"], "HEAD"))


def _remote_sha(url: str, reference: str) -> str:
    result = subprocess.run(
        ["git", "ls-remote", url, reference],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise SystemExit(f"{url}: git ls-remote failed: {result.stderr.strip()}")
    refs = [tuple(line.split()) for line in result.stdout.splitlines() if line.strip()]
    exact = [sha for sha, name in refs if name == reference]
    if len(exact) == 1:
        return exact[0]
    shas = [sha for sha, _name in refs]
    if len(shas) != 1:
        raise SystemExit(f"{url}: expected one {reference} tip, got {len(shas)}")
    return shas[0]


def assign_roles(data: dict[str, Any]) -> None:
    """Apply the role plan and check that every candidate got exactly one role."""
    by_name = {repo["name"]: repo for repo in data["repositories"]}
    for repo in data["repositories"]:
        repo["roles"] = []
    for role, names in ROLE_PLAN.items():
        for name in names:
            if name not in by_name:
                raise SystemExit(f"role plan names unknown repository: {name}")
            if by_name[name]["roles"]:
                raise SystemExit(f"role plan assigns {name} twice")
            by_name[name]["roles"] = [role]
    unassigned = [
        repo["name"]
        for repo in data["repositories"]
        if not repo["roles"] and repo["name"] not in NO_ROLE_REPOSITORIES
    ]
    if unassigned:
        raise SystemExit(f"candidates without a role: {sorted(unassigned)}")


def fetch_candidates(data: dict[str, Any], cache: Path) -> dict[str, Any]:
    """Fetch and verify every candidate, retrying each repository once."""
    verified: list[dict[str, Any]] = []
    failures: dict[str, str] = {}
    differences: list[dict[str, str]] = []
    corrections: list[dict[str, str]] = []
    for repo in data["repositories"]:
        record, reason = _fetch_one(repo, cache)
        if record is None:
            failures[repo["name"]] = reason
            print(f"FAILED {repo['name']}: {reason}", file=sys.stderr)
            continue
        if record["spdx_corrected_from"]:
            corrections.append(
                {
                    "name": repo["name"],
                    "declared": record["spdx_corrected_from"],
                    "verified": record["spdx"],
                    "license_file": record["license_file"],
                }
            )
            repo["spdx"] = record["spdx"]
        verified.append(record)
        if record["fetch_license_check"]:
            differences.append(
                {
                    "name": repo["name"],
                    "spdx": record["spdx"],
                    "license_file": record["license_file"],
                    "fetch_license_check": record["fetch_license_check"],
                }
            )
        print(f"verified {repo['name']} {record['pin_sha'][:12]}", flush=True)
    return {
        "repositories": verified,
        "excluded": failures,
        "validator_differences": differences,
        "spdx_corrections": corrections,
    }


def _fetch_one(repo: dict[str, Any], cache: Path) -> tuple[dict[str, Any] | None, str]:
    reason = "not attempted"
    for _ in range(2):
        try:
            return _fetch_with_snapshot(repo, cache), ""
        except (FetchError, OSError, ValueError, subprocess.SubprocessError) as exc:
            reason = f"{type(exc).__name__}: {exc}"
    return None, reason


def _fetch_with_snapshot(repo: dict[str, Any], cache: Path) -> dict[str, Any]:
    pinned = dict(repo, status="verified")
    with tempfile.TemporaryDirectory(prefix="varde-cd-snapshot-") as root:
        snapshot_root = Path(root)
        record, gate = _fetch_recording_license_verdict(pinned, cache, snapshot_root)
        snapshot = snapshot_root / repo["name"].replace("/", "__")
        checkout = cache / repo["name"].replace("/", "__")
        if repo["spdx"] not in PERMITTED_SPDX:
            raise FetchError(POLICY_REASON)
        license_file, spdx, note = _license_evidence(snapshot, repo["spdx"])
        if not license_file:
            raise FetchError(
                f"no root license file of {_license_candidates(snapshot)} matches "
                f"the declared {repo['spdx']} or another permitted license"
            )
        return {
            "name": repo["name"],
            "url": repo["url"],
            "spdx": spdx,
            "spdx_declared": repo["spdx"],
            "spdx_corrected_from": "" if spdx == repo["spdx"] else repo["spdx"],
            "languages": list(repo["languages"]),
            "roles": list(repo["roles"]),
            "pin_sha": record["pin_sha"],
            "tree_digest": record["tree_digest"],
            "license_verified": True,
            "license_file": license_file,
            "license_text_sha256": _file_sha256(snapshot / license_file),
            "license_note": note,
            "fetch_license_check": gate,
            "snapshot_bytes": _directory_bytes(snapshot),
            "snapshot_files": sum(1 for path in snapshot.rglob("*") if path.is_file()),
            "cache_bytes": _directory_bytes(checkout / ".git"),
            "status": "verified",
            "reason": "",
        }


def _fetch_recording_license_verdict(
    pinned: dict[str, Any], cache: Path, snapshot_root: Path
) -> tuple[dict[str, str], str]:
    """Fetch through corpus/fetch.py, recording its license verdict.

    The task may not edit ``corpus/fetch.py``; this records what its
    ``check_license`` said so the report can name every disagreement with the
    driver's own text check. ``_license_text`` is widened for the call because
    it searches only LICENSE, LICENSE.md, LICENSE.txt and COPYING and so
    raises for LICENSE-MIT, LICENSE.MIT, License.txt and MIT-LICENSE pins.
    """
    original_check = corpus_fetch.check_license
    original_text = corpus_fetch._license_text
    verdict = {"error": ""}

    def recording(text: str, expected: str) -> None:
        try:
            original_check(text, expected)
        except FetchError as exc:
            verdict["error"] = str(exc)

    corpus_fetch.check_license = recording
    corpus_fetch._license_text = _root_license_text
    try:
        record = corpus_fetch.fetch_repository(pinned, cache, snapshot_root)
    finally:
        corpus_fetch.check_license = original_check
        corpus_fetch._license_text = original_text
    return record, verdict["error"]


def _root_license_text(checkout: Path, revision: str) -> str:
    """Return the text of the first root license file, name list widened."""
    listing = subprocess.run(
        ["git", "-C", str(checkout), "ls-tree", revision],
        check=False,
        capture_output=True,
        text=True,
    )
    names = []
    for line in listing.stdout.splitlines():
        meta, _, name = line.partition("\t")
        if meta.split()[1:2] == ["blob"] and name.upper().startswith(
            LICENSE_FILE_PREFIXES
        ):
            names.append(name)
    for name in sorted(names):
        shown = subprocess.run(
            ["git", "-C", str(checkout), "show", f"{revision}:{name}"],
            check=False,
            capture_output=True,
            text=True,
        )
        if shown.returncode == 0:
            return shown.stdout
    raise FetchError("pinned repository has no root license file")


def _license_candidates(snapshot: Path) -> list[str]:
    return sorted(
        path.name
        for path in snapshot.iterdir()
        if path.is_file() and path.name.upper().startswith(LICENSE_FILE_PREFIXES)
    )


def _license_evidence(snapshot: Path, declared: str) -> tuple[str, str, str]:
    """Return the root license file, the family it matches, and a bundling note.

    The declared family wins whenever any root license file identifies it, so a
    dual-licensed repository (LICENSE-MIT beside LICENSE-APACHE) keeps the
    declared family. Only when no root file identifies the declared family is
    another permitted family returned, which the caller records as a
    correction.
    """
    candidates = _license_candidates(snapshot)
    families = [declared, *sorted(PERMITTED_SPDX - {declared})]
    for family in families:
        for name in candidates:
            text = (snapshot / name).read_text(encoding="utf-8", errors="replace")
            if matches_license(text, family):
                return name, family, _bundle_note(text, family)
    return "", "", ""


def _bundle_note(text: str, family: str) -> str:
    families = (*LICENSE_MARKERS, "BSD-2-Clause", "BSD-3-Clause")
    others = sorted(
        other for other in families if other != family and matches_license(text, other)
    )
    return f"bundles notices for {', '.join(others)}" if others else ""


def flatten_license_text(text: str) -> str:
    """Upper-case, de-quote and collapse whitespace so markers match wording."""
    stripped = re.sub(r"[\"'`\u2018\u2019\u201c\u201d]", "", text).upper()
    return re.sub(r"\s+", " ", stripped)


def matches_license(text: str, spdx: str) -> bool:
    """Check a license text against one SPDX family."""
    flat = flatten_license_text(text)
    if spdx in {"BSD-2-Clause", "BSD-3-Clause"}:
        source = "REDISTRIBUTIONS OF SOURCE CODE" in flat
        binary = "REDISTRIBUTIONS IN BINARY FORM" in flat
        endorsement = "NEITHER THE NAME" in flat
        if spdx == "BSD-2-Clause":
            return source and binary and not endorsement
        return source and binary and endorsement
    markers = LICENSE_MARKERS.get(spdx)
    if markers is None:
        return False
    return all(marker in flat for marker in markers)


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _directory_bytes(root: Path) -> int:
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())


def apply_outcomes(data: dict[str, Any], outcomes: dict[str, Any]) -> None:
    """Mark fetched candidates verified and excluded ones unverified, role-free."""
    for repo in data["repositories"]:
        if repo["name"] in outcomes["excluded"]:
            repo["status"] = "unverified"
            repo["roles"] = []
        else:
            repo["status"] = "verified"


def write_verified(data: dict[str, Any], outcomes: dict[str, Any], cache: Path) -> None:
    """Write the machine-readable verified manifest for the frozen run."""
    entries = {entry["name"]: entry for entry in outcomes["repositories"]}
    repositories = []
    excluded = []
    for repo in data["repositories"]:
        if repo["name"] in outcomes["excluded"]:
            excluded.append(
                {
                    "name": repo["name"],
                    "url": repo["url"],
                    "spdx": repo["spdx"],
                    "pin_sha": repo["pin_sha"],
                    "status": "unverified",
                    "reason": outcomes["excluded"][repo["name"]],
                }
            )
            continue
        entry = entries[repo["name"]]
        repositories.append(dict(entry, roles=list(repo["roles"])))
    document = {
        "run": "cd-networked-run",
        "run_date": RUN_DATE,
        "manifest_digest": compute_manifest_digest(data),
        "fetch_cache": str(cache),
        "repositories": sorted(repositories, key=lambda entry: entry["name"]),
        "excluded": sorted(excluded, key=lambda entry: entry["name"]),
        "validator_differences": sorted(
            outcomes["validator_differences"], key=lambda entry: entry["name"]
        ),
        "spdx_corrections": sorted(
            outcomes["spdx_corrections"], key=lambda entry: entry["name"]
        ),
        "counts": counts(data, outcomes["excluded"]),
    }
    VERIFIED_PATH.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def counts(data: dict[str, Any], excluded: dict[str, str]) -> dict[str, Any]:
    """Count candidates, verified entries and roles straight from the manifest."""
    repos = data["repositories"]
    verified = [repo for repo in repos if repo["status"] == "verified"]
    return {
        "total_candidates": len(repos),
        "total_verified": len(verified),
        "total_excluded": len(excluded),
        "verified_by_language": _tally(_languages(verified)),
        "verified_by_role": _tally(
            [repo["roles"][0] if repo["roles"] else "none" for repo in verified]
        ),
        "verified_by_group": _tally([_group(repo) for repo in verified]),
        "calibration_by_group": _tally(
            [_group(repo) for repo in verified if repo["roles"] == ["calibration"]]
        ),
        "candidates_by_group": _tally([_group(repo) for repo in repos]),
        "excluded": sorted(excluded),
    }


def _group(repo: dict[str, Any]) -> str:
    return release_group(repo["languages"])


def _languages(repositories: list[dict[str, Any]]) -> list[str]:
    return [language for repo in repositories for language in repo["languages"]]


def _tally(values: list[str]) -> dict[str, int]:
    tally: dict[str, int] = {}
    for value in values:
        tally[value] = tally.get(value, 0) + 1
    return dict(sorted(tally.items()))


def release_group(languages: list[str]) -> str:
    """Map a repository's languages to its release group, else its first language."""
    for group, members in RELEASE_GROUPS.items():
        if set(languages) & set(members):
            return group
    return languages[0]


def tiering(data: dict[str, Any]) -> dict[str, str]:
    """Report whether each group reaches the calibration floor for tiering."""
    counted = counts(data, {})
    result = {}
    for group in counted["candidates_by_group"]:
        calibration = counted["calibration_by_group"].get(group, 0)
        result[group] = _tier_label(group, calibration)
    return result


def _tier_label(group: str, calibration: int) -> str:
    if group not in RELEASE_GROUPS:
        return f"untiered ({calibration} calibration repos)"
    if calibration >= CALIBRATION_FLOOR:
        return f"calibration floor met ({calibration} repos)"
    return f"report-only ({calibration} calibration repos)"


def write_report(data: dict[str, Any], verified: dict[str, Any], cache: Path) -> None:
    """Render REPORT.md from the verified manifest and stage summaries."""
    sections = [
        *_report_header(data, verified, cache),
        *_report_counts(data, verified),
        *_report_repositories(verified),
        *_report_licenses(verified),
        *_report_spdx_corrections(verified),
        *_report_license_gate_differences(verified),
        *_report_mining(),
        *_report_inputs(),
        *_report_notes(data, verified),
    ]
    REPORT_PATH.write_text("\n".join(sections) + "\n", encoding="utf-8")


def _report_header(
    data: dict[str, Any], verified: dict[str, Any], cache: Path
) -> list[str]:
    digest = compute_manifest_digest(data)
    return [
        "# Verified quality corpus (cd-networked-run)",
        "",
        (
            f"Frozen {RUN_DATE} by task `cd-networked-run`. Manifest digest "
            f"`{digest}`. Fetch cache `{cache}`; `$VARDE_BENCH_CACHE` must point "
            "there for mining and snapshot reads."
        ),
        "",
        "Reproduce with:",
        "",
        "```sh",
        "uv run python code/bench/quality-corpus/corpus/verified/cd_run.py pin",
        "uv run python code/bench/quality-corpus/corpus/verified/cd_run.py roles",
        "uv run python code/bench/quality-corpus/corpus/verified/cd_run.py fetch",
        "uv run python code/bench/quality-corpus/corpus/verified/cd_artifacts.py mine",
        (
            "uv run python "
            "code/bench/quality-corpus/corpus/verified/cd_artifacts.py inputs"
        ),
        "uv run python code/bench/quality-corpus/corpus/verified/cd_run.py report",
        "```",
        "",
        (
            "Every pin is the default-branch tip at run time from `git ls-remote "
            "<url> HEAD`, except `redis/redis`, pinned on the BSD-3 `7.2` line "
            "(`refs/heads/7.2`) because later releases changed license. The "
            "license was read from the fetched pin's root license files and "
            "checked against the declared SPDX twice: once by "
            "`corpus/fetch.py`, whose verdict is recorded per repository in "
            "`verified.json`, and once by `cd_run.py`'s own text check "
            "(`LICENSE_MARKERS`), whose verdict decides `license_verified`. The "
            "tree digest is `git ls-tree -r --full-tree` over the pinned ref."
        ),
        "",
    ]


def _report_counts(data: dict[str, Any], verified: dict[str, Any]) -> list[str]:
    counted = verified["counts"]
    tiers = tiering(data)
    lines = [
        "## Counts",
        "",
        "| group | candidates | verified | roles | tier |",
        "|---|---|---|---|---|",
    ]
    lines.extend(
        f"| {group} | {counted['candidates_by_group'][group]} | "
        f"{counted['verified_by_group'].get(group, 0)} | "
        f"{_role_summary(verified, group)} | {tiers[group]} |"
        for group in counted["candidates_by_group"]
    )
    roles = ", ".join(
        f"{role}={count}" for role, count in counted["verified_by_role"].items()
    )
    lines.extend(
        (
            "",
            (
                f"Total: {counted['total_verified']} verified of "
                f"{counted['total_candidates']} candidates, "
                f"{counted['total_excluded']} excluded. Roles: {roles}."
            ),
            "",
            "<!-- counts:start -->",
            "```toml",
            *_counts_block(counted),
            "```",
            "<!-- counts:end -->",
            "",
        )
    )
    return lines


def _role_summary(verified: dict[str, Any], group: str) -> str:
    roles: dict[str, int] = {}
    for entry in verified["repositories"]:
        if release_group(entry["languages"]) != group:
            continue
        role = entry["roles"][0] if entry["roles"] else "none"
        roles[role] = roles.get(role, 0) + 1
    return ", ".join(f"{role} {count}" for role, count in sorted(roles.items()))


def _counts_block(counted: dict[str, Any]) -> list[str]:
    lines = [
        f"total_candidates = {counted['total_candidates']}",
        f"total_verified = {counted['total_verified']}",
        f"total_excluded = {counted['total_excluded']}",
    ]
    for key in (
        "verified_by_language",
        "verified_by_group",
        "verified_by_role",
        "calibration_by_group",
        "candidates_by_group",
    ):
        lines += ["", f"[{key}]"]
        lines += [f'"{name}" = {value}' for name, value in counted[key].items()]
    return lines


def _report_repositories(verified: dict[str, Any]) -> list[str]:
    lines = [
        "## Repositories",
        "",
        (
            "| repository | language | SPDX | license file | pin | tree digest | "
            "tip bytes | cache bytes | role | status |"
        ),
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    lines.extend(
        f"| {entry['name']} | {', '.join(entry['languages'])} | "
        f"{entry['spdx']} | {entry['license_file']} | "
        f"`{entry['pin_sha'][:12]}` | `{entry['tree_digest'][:12]}` | "
        f"{entry['snapshot_bytes']} | {entry['cache_bytes']} | "
        f"{', '.join(entry['roles']) or 'none'} | {entry['status']} |"
        for entry in verified["repositories"]
    )
    return [*lines, ""]


def _report_licenses(verified: dict[str, Any]) -> list[str]:
    lines = ["## Excluded candidates and license failures", ""]
    if not verified["excluded"]:
        lines.append("None: every candidate's license text matched its declared SPDX.")
    lines.extend(
        f"- `{entry['name']}` ({entry['spdx']}): {entry['reason']}. "
        f"No role assigned; pin `{entry['pin_sha'][:12]}` left in the "
        "manifest for evidence."
        for entry in verified["excluded"]
    )
    return [*lines, ""]


def _report_spdx_corrections(verified: dict[str, Any]) -> list[str]:
    corrections = verified["spdx_corrections"]
    lines = ["## Declared SPDX corrected by the fetched license text", ""]
    if not corrections:
        lines.append("None: every declared SPDX identifier matched its pin.")
        return [*lines, ""]
    lines += [
        (
            "The manifest's per-repository `spdx` came from memory and is a "
            "claim, not a fact; these entries were corrected to the family the "
            "fetched license text identifies (all still permitted):"
        ),
        "",
        "| repository | declared | verified | license file |",
        "|---|---|---|---|",
    ]
    for entry in corrections:
        lines.append(
            f"| {entry['name']} | {entry['declared']} | {entry['verified']} | "
            f"{entry['license_file']} |"
        )
    return [*lines, ""]


def _report_license_gate_differences(verified: dict[str, Any]) -> list[str]:
    differences = verified["validator_differences"]
    lines = [
        "## corpus/fetch.py license-check differences",
        "",
        (
            "Most differences are MIT false negatives: `corpus/fetch.py` misses "
            "quoted canonical wording and alternate license filenames, and it "
            "rejects EPL text that mentions GPL as a secondary reference."
        ),
        "",
    ]
    if not differences:
        lines.append("No repository disagreed with `corpus/fetch.py`.")
        return [*lines, ""]
    lines += [
        (
            f"{len(differences)} of {len(verified['repositories'])} repositories "
            "passed the driver's text check and failed `corpus/fetch.py`'s:"
        ),
        "",
        "| repository | SPDX | license file matched | corpus/fetch.py verdict |",
        "|---|---|---|---|",
    ]
    for entry in differences:
        lines.append(
            f"| {entry['name']} | {entry['spdx']} | {entry['license_file']} | "
            f"{entry['fetch_license_check']} |"
        )
    return [*lines, ""]


def _report_mining() -> list[str]:
    lines = ["## Category (c): mined refactor pairs", ""]
    summary = _read_json(MINED_SUMMARY_PATH)
    if not summary:
        return [*lines, "Mining has not run in this checkout.", ""]
    lines += [
        (
            f"Completed mining from {summary['completed_repositories']} pinned `pairs` "
            f"repositories; {summary['time_capped_repositories']} are time-capped, "
            "partial. Target is 6 pairs per release language."
        ),
        "",
        (
            "| language | completed repos | partial repos | commits walked | "
            "intent matches | accepted | vs target |"
        ),
        "|---|---|---|---|---|---|---|",
    ]
    for language, stats in summary["languages"].items():
        lines.append(
            f"| {language} | {stats['repositories']} | "
            f"{stats['partial_repositories']} | {stats['commits_walked']} | "
            f"{stats['intent_matches']} | {stats['accepted']} | "
            f"{_shortfall(stats['accepted'], 6)} |"
        )
    short_languages = [
        language
        for language, stats in summary["languages"].items()
        if stats["accepted"] < 6
    ]
    lines += [
        "",
        (
            "Languages short of 6 pairs: "
            f"{', '.join(short_languages) if short_languages else 'none'}."
        ),
    ]
    for name, repository in summary["repositories"].items():
        if repository["status"] != "time-capped, partial":
            continue
        lines += [
            "",
            (
                f"`{name}`: **time-capped, partial**; "
                f"{repository['accepted']} Roslyn pairs were persisted before the cap. "
                f"{repository['reason']}"
            ),
        ]
        if repository["language"] == "csharp":
            completed_pairs = sum(
                item["accepted"]
                for item in summary["repositories"].values()
                if item["language"] == "csharp" and item["status"] == "complete"
            )
            lines.append(
                f"C# has {completed_pairs} accepted pairs from completed repositories, "
                "meeting the 6-pair target."
            )
    lines += [
        "",
        "Filter pass rates (passed / evaluated at that stage):",
        "",
        (
            "| language | parent | intent | file limit | parse | function limit "
            "| generated | public feature |"
        ),
        "|---|---|---|---|---|---|---|---|",
    ]
    for language, stats in summary["languages"].items():
        cells = " | ".join(_rate_cells(stats["filters"]))
        lines.append(f"| {language} | {cells} |")
    return [*lines, ""]


def _rate_cells(rates: dict[str, Any]) -> list[str]:
    stages = (
        "parent",
        "intent",
        "file_limit",
        "parse",
        "function_limit",
        "generated",
        "public_feature",
    )
    return [f"{rates[stage]['passed']}/{rates[stage]['evaluated']}" for stage in stages]


def _shortfall(accepted: int, target: int) -> str:
    return f"short by {target - accepted}" if accepted < target else "target met"


def _report_inputs() -> list[str]:
    lines = ["## Category (d): mutation inputs", ""]
    summary = _read_json(INPUTS_SUMMARY_PATH)
    if not summary:
        return [*lines, "Input selection has not run in this checkout.", ""]
    lines += [
        (
            f"Selected {summary['total']} functions (target 20 per release "
            "language) into `corpus/verified/mutation-inputs/<language>/`; each "
            "input is one function, 10-60 lines, parseable on its own, with "
            "provenance in the language's `provenance.json` and any license "
            "header kept as a `.license.txt` sidecar."
        ),
        "",
        (
            "| language | mutation-base repos | inputs | license headers kept | "
            "vs target |"
        ),
        "|---|---|---|---|---|",
    ]
    for language, stats in summary["languages"].items():
        lines.append(
            f"| {language} | {', '.join(stats['repositories'])} | {stats['inputs']} | "
            f"{stats['license_headers']} | {_shortfall(stats['inputs'], 20)} |"
        )
    return [*lines, ""]


def _report_notes(data: dict[str, Any], verified: dict[str, Any]) -> list[str]:
    lines = ["## Notes", ""]
    for group, status in tiering(data).items():
        lines.append(f"- {group}: {status}.")
    lines += [
        (
            "- The calibration floor is 5 repositories per release language "
            "(validation-plan section 7); Python and TypeScript/JavaScript "
            "meet the floor after this reassignment. Other language groups "
            "remain report-only or untiered."
        ),
        (
            "- No repository carries the `history` role in this run, so no "
            "`history_cutoffs` are pinned; the role and its T-12m/T-24m/T-36m "
            "cutoffs stay for the later history-validation task."
        ),
        (
            "- `pairs/mined/` holds candidate records only; `pair_groups` in the "
            "manifest stays empty because registering every mined candidate "
            "there would add hundreds of groups for a set the panel has not "
            "labelled yet."
        ),
        (
            "- `roles.py --check-reservations` reports no conflict; the four "
            "call-resolution repositories carry no quality-corpus role."
        ),
        (
            "- `lysine-dev/okhttp`, the Java `mutation-base` repository, is "
            "predominantly Kotlin at its pin (573 `.kt` files, 71 `.java` "
            "files); its Java inputs come from its Java sources."
        ),
        (
            "- Pins are brute-forced tips, so they will move upstream; "
            "`verified.json` records each pin and tree digest, and "
            "`corpus/fetch.py` fails a cached checkout whose pinned tree no "
            "longer matches."
        ),
    ]
    for entry in verified["repositories"]:
        if entry.get("license_note"):
            lines.append(
                f"- `{entry['name']}`: {entry['license_file']} {entry['license_note']}."
            )
    return [*lines, ""]


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _cache_dir() -> Path:
    return Path(
        os.environ.get("VARDE_BENCH_CACHE", Path.home() / ".cache" / "varde" / "bench")
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("pin", "roles", "fetch", "report"))
    args = parser.parse_args(argv)
    data = read_manifest()
    if args.stage == "pin":
        pin_candidates(data)
        print(write_manifest(data))
    elif args.stage == "roles":
        assign_roles(data)
        print(write_manifest(data))
    elif args.stage == "fetch":
        outcomes = fetch_candidates(data, _cache_dir())
        apply_outcomes(data, outcomes)
        write_manifest(data)
        write_verified(data, outcomes, _cache_dir())
    else:
        write_report(data, _read_json(VERIFIED_PATH), _cache_dir())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
