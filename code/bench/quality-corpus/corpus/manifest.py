"""Load and validate the quality corpus repository manifest."""

from __future__ import annotations

import hashlib
import re
import tomllib
from pathlib import Path
from typing import Any

ROLES = {"calibration", "pairs", "history", "held-out", "mutation-base"}
SPDX_LICENSES = {
    "Apache-2.0",
    "BSD-2-Clause",
    "BSD-3-Clause",
    "curl",
    "EPL-2.0",
    "ISC",
    "MIT",
    "MPL-2.0",
}
SHA = re.compile(r"^[0-9a-f]{40,64}$")


class ManifestError(ValueError):
    """Raised when a corpus manifest is malformed or inconsistent."""


def load_manifest(path: Path) -> dict[str, Any]:
    """Parse a TOML manifest and validate its content and digest."""
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ManifestError(f"cannot read manifest {path}: {exc}") from exc
    validate_manifest(data)
    return data


def manifest_payload(data: dict[str, Any]) -> bytes:
    """Return canonical bytes for the manifest digest."""
    repos = sorted(data.get("repositories", []), key=lambda repo: repo.get("name", ""))
    fields = [
        "\0".join(
            (
                repo.get("name", ""),
                repo.get("url", ""),
                repo.get("redirected_from", ""),
                repo.get("spdx", ""),
                ",".join(sorted(repo.get("languages", []))),
                repo.get("pin_sha", ""),
                repo.get("status", ""),
                ",".join(sorted(repo.get("roles", []))),
                ",".join(sorted(repo.get("history_cutoffs", []))),
            )
        )
        for repo in repos
    ]
    groups = sorted(data.get("pair_groups", []), key=lambda group: group.get("id", ""))
    fields.extend(
        "pair\0"
        + "\0".join(
            (
                group.get("id", ""),
                group.get("repository", ""),
                group.get("kind", ""),
                ",".join(sorted(group.get("samples", []))),
            )
        )
        for group in groups
    )
    return ("\n".join(fields) + "\n").encode()


def compute_manifest_digest(data: dict[str, Any]) -> str:
    """Compute the stable digest for repository and pair-group entries."""
    return hashlib.sha256(manifest_payload(data)).hexdigest()


def validate_manifest(data: dict[str, Any]) -> None:
    """Validate repository fields, pins, licenses, role separation, and digest."""
    repositories = data.get("repositories")
    if not isinstance(repositories, list):
        raise ManifestError("manifest must contain a repositories array")
    roles_by_name: dict[str, list[str]] = {}
    urls: set[str] = set()
    for repo in repositories:
        _validate_repository(repo, roles_by_name, urls)
    _validate_pair_groups(data.get("pair_groups"), roles_by_name)
    digest = data.get("manifest_digest")
    if not isinstance(digest, str) or digest != compute_manifest_digest(data):
        raise ManifestError("manifest_digest does not match repository entries")


def _validate_pair_groups(groups: Any, roles_by_name: dict[str, list[str]]) -> None:
    if not isinstance(groups, list):
        raise ManifestError("manifest must contain a pair_groups array")
    group_ids: set[str] = set()
    for group in groups:
        if not isinstance(group, dict):
            raise ManifestError("each pair group must be a table")
        group_id = group.get("id")
        repository = group.get("repository")
        kind = group.get("kind")
        samples = group.get("samples")
        if not isinstance(group_id, str) or not group_id or group_id in group_ids:
            raise ManifestError("pair group IDs must be non-empty and unique")
        group_ids.add(group_id)
        if not isinstance(repository, str) or repository not in roles_by_name:
            raise ManifestError(
                f"{group_id}: pair group references an unknown repository"
            )
        if "pairs" not in roles_by_name[repository]:
            raise ManifestError(
                f"{group_id}: pair group repository must hold the pairs role"
            )
        if not isinstance(kind, str) or kind not in {"task", "refactor"}:
            raise ManifestError(f"{group_id}: pair group kind must be task or refactor")
        if (
            not isinstance(samples, list)
            or len(samples) < 2
            or not all(isinstance(sample, str) and sample for sample in samples)
        ):
            raise ManifestError(
                f"{group_id}: pair groups require at least two sample IDs"
            )
        if len(samples) != len(set(samples)):
            raise ManifestError(f"{group_id}: sample IDs must not repeat")


def _validate_repository(
    repo: Any, roles_by_name: dict[str, list[str]], urls: set[str]
) -> None:
    if not isinstance(repo, dict):
        raise ManifestError("each repository must be a table")
    name, url, license_id = (repo.get(key) for key in ("name", "url", "spdx"))
    if not all(isinstance(value, str) and value for value in (name, url, license_id)):
        raise ManifestError("repository name, url, and spdx are required")
    if name in roles_by_name or url in urls:
        raise ManifestError(f"duplicate repository name or URL: {name}")
    roles_by_name[name] = repo.get("roles", [])
    urls.add(url)
    redirected_from = repo.get("redirected_from")
    if redirected_from is not None and (
        not isinstance(redirected_from, str) or not redirected_from
    ):
        raise ManifestError(f"{name}: redirected_from must be a non-empty string")
    if license_id not in SPDX_LICENSES:
        raise ManifestError(f"invalid SPDX license identifier: {license_id}")
    languages = repo.get("languages")
    roles = repo.get("roles")
    cutoffs = repo.get("history_cutoffs")
    if (
        not isinstance(languages, list)
        or not languages
        or not all(isinstance(x, str) and x for x in languages)
    ):
        raise ManifestError(f"{name}: languages must be a non-empty string array")
    if not isinstance(roles, list) or not all(role in ROLES for role in roles):
        raise ManifestError(f"{name}: roles must use known roles")
    if len(roles) != len(set(roles)):
        raise ManifestError(f"{name}: roles must not repeat")
    if not isinstance(cutoffs, list):
        raise ManifestError(f"{name}: history_cutoffs must be an array")
    status = repo.get("status")
    if status not in {"unverified", "verified"}:
        raise ManifestError(f"{name}: status must be unverified or verified")
    pin = repo.get("pin_sha", "")
    if status == "verified" and not SHA.fullmatch(pin):
        raise ManifestError(f"{name}: verified repositories require a full pin_sha")
    if status == "unverified" and pin and not SHA.fullmatch(pin):
        raise ManifestError(f"{name}: pin_sha must be a full SHA when provided")
    if len(roles) > 1:
        raise ManifestError(f"{name}: repository roles must be disjoint")
    if any(not SHA.fullmatch(sha) for sha in cutoffs):
        raise ManifestError(f"{name}: history cutoffs must be full commit SHAs")
