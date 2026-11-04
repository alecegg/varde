from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest
from varde_learn.docs.spec_inventory import inventory


class Fixture:
    def __init__(self, root: Path, tag: str = "inventory") -> None:
        self.root = root / tag
        self.repository = self.root / "repo"
        self.knowledge = self.root / "knowledge"
        self.working = self.root / "working"
        (self.knowledge / "specs").mkdir(parents=True)
        self.repository.mkdir(parents=True)
        self.working.mkdir()
        self.now = 1_800_000_000
        for domain in ("a", "b"):
            source = f"src/{domain}/main.rs"
            path = self.repository / source
            path.parent.mkdir(parents=True)
            path.write_text(f"fn {domain}() {{}}\n")
            self_spec(self.repository, self.knowledge, domain, [source])
        self.git("init", "-q")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "user.name", "Test")
        self.git("add", ".")
        self.git("commit", "-qm", "initial")

    def git(self, *args: str) -> bytes:
        result = subprocess.run(
            ["git", *args], cwd=self.repository, check=True, capture_output=True
        )
        return result.stdout

    def git_access(self, root: Path, args: tuple[str, ...]) -> bytes:
        result = subprocess.run(
            ["git", *args], cwd=root, check=True, capture_output=True
        )
        return result.stdout

    def run(self, refresh: bool = False, acknowledge: str | None = None) -> dict:
        return inventory(
            self.repository,
            self.knowledge,
            self.working,
            refresh=refresh,
            acknowledge_architecture_paths=(
                () if acknowledge is None else (acknowledge,)
            ),
            clock=lambda: self.now,
            git=self.git_access,
        )


def blob_hash(data: bytes) -> str:
    return hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()  # noqa: S324 - Fixture reproduces Git object IDs.


def self_spec(repository: Path, knowledge: Path, domain: str, files: list[str]) -> None:
    pairs = [(name, blob_hash((repository / name).read_bytes())) for name in files]
    roots = f"source_roots:\n  - src/{domain}\n"
    covered = "covered_paths:\n" + "".join(f"  - {name}\n" for name, _ in sorted(pairs))
    sources = "sources:\n" + "".join(
        f"  - path: {name}\n    hash: {digest}\n" for name, digest in sorted(pairs)
    )
    aggregate = "".join(f"{name}{digest}" for name, digest in sorted(pairs)).encode()
    body = (
        f"---\ntype: spec\nid: specs/{domain}\ndomain: {domain}\n"
        f"{roots}{covered}source_hash: {blob_hash(aggregate)}\n"
        f"{sources}---\nBody\n"
    )
    (knowledge / "specs" / f"{domain}.md").write_text(body)


def architecture_spec(fixture: Fixture) -> None:
    name = "Cargo.toml"
    digest = blob_hash((fixture.repository / name).read_bytes())
    aggregate = blob_hash(f"{name}{digest}".encode())
    (fixture.knowledge / "specs/architecture.md").write_text(
        (  # noqa: UP034 - Explicit grouping is required for split fixture text.
            f"---\ntype: spec\ndomain: architecture\nsource_roots:\n  - {name}\n"
            f"covered_paths:\n  - {name}\nsource_hash: {aggregate}\n"
            f"sources:\n  - path: {name}\n    hash: {digest}\n---\nBody\n"
        )
    )


def status(data: dict, domain: str) -> str:
    return next(item["status"] for item in data["domains"] if item["domain"] == domain)


def test_scoped_changes_reuse_unaffected_domain_and_match_refresh(
    tmp_path: Path,
) -> None:
    fixture = Fixture(tmp_path, "scoped")
    cold = fixture.run()
    assert cold["cache_hit"] is False
    assert status(cold, "a") == status(cold, "b") == "reuse"
    assert fixture.run()["cache_hit"] is True
    (fixture.repository / "src/a/main.rs").write_text("fn changed() {}\n")
    warm = fixture.run()
    assert warm["cache_hit"] is True
    assert status(warm, "a") == "stale"
    assert status(warm, "b") == "reuse"
    forced = fixture.run(refresh=True)
    assert forced["cache_hit"] is False
    assert warm["domains"] == forced["domains"]
    fixture.git("add", "src/a/main.rs")
    assert status(fixture.run(), "b") == "reuse"
    fixture.git("commit", "-qm", "changed a")
    assert status(fixture.run(), "b") == "reuse"


def test_untracked_content_and_spec_edits_invalidate_cached_verdicts(
    tmp_path: Path,
) -> None:
    fixture = Fixture(tmp_path, "untracked")
    extra = fixture.repository / "src/a/extra.rs"
    extra.write_text("fn extra() {}\n")
    self_spec(
        fixture.repository, fixture.knowledge, "a", ["src/a/extra.rs", "src/a/main.rs"]
    )
    assert status(fixture.run(), "a") == "reuse"
    extra.write_text("fn changed_extra() {}\n")
    warm = fixture.run()
    assert warm["cache_hit"] is True
    assert status(warm, "a") == "stale"
    assert status(warm, "b") == "reuse"
    assert warm["domains"] == fixture.run(refresh=True)["domains"]
    spec = fixture.knowledge / "specs/b.md"
    spec.write_text(spec.read_text().replace("source_hash: ", "source_hash: wrong-"))
    changed = fixture.run()
    assert status(changed, "b") == "stale"
    assert changed["domains"] == fixture.run(refresh=True)["domains"]


def test_additions_deletions_and_corrupt_cache_fail_closed(tmp_path: Path) -> None:
    fixture = Fixture(tmp_path, "corrupt")
    fixture.run()
    (fixture.repository / "src/a/new.rs").write_text("fn new() {}\n")
    added = fixture.run()
    assert status(added, "a") == "stale" and status(added, "b") == "reuse"
    assert added["domains"] == fixture.run(refresh=True)["domains"]
    (fixture.repository / "src/b/main.rs").unlink()
    deleted = fixture.run()
    assert status(deleted, "b") == "stale"
    assert deleted["domains"] == fixture.run(refresh=True)["domains"]
    cache = next((fixture.working / "spec-inventory").glob("*.json"))
    cache.write_bytes(b"{not-json")
    recovered = fixture.run()
    assert recovered["cache_hit"] is False
    assert recovered["domains"] == fixture.run(refresh=True)["domains"]
    value = json.loads(cache.read_text())
    value["cache"]["domains"][0]["status"] = "reuse"
    cache.write_text(json.dumps(value))
    assert fixture.run()["cache_hit"] is False
    assert fixture.root.is_dir()


def test_roots_architecture_and_due_validation_invalidate_safely(
    tmp_path: Path,
) -> None:
    fixture = Fixture(tmp_path, "architecture")
    fixture.run()
    architecture = fixture.knowledge / "specs/architecture.md"
    architecture.write_text(
        "---\ntype: spec\ndomain: architecture\nsource_roots:\n  - Cargo.toml\n"
        "covered_paths: []\nsource_hash: none\nsources: []\n---\nBody\n"
    )
    result = fixture.run()
    assert status(result, "architecture") == "stale"
    assert result["domains"] == fixture.run(refresh=True)["domains"]
    (fixture.repository / "Cargo.toml").write_text('[package]\nname = "fixture"\n')
    assert status(fixture.run(), "architecture") == "stale"
    architecture_spec(fixture)
    assert status(fixture.run(), "architecture") == "reuse"
    deployment = fixture.repository / "infra/deploy.yaml"
    deployment.parent.mkdir()
    deployment.write_text("service: fixture\n")
    assert status(fixture.run(), "architecture") == "stale"
    spec = fixture.knowledge / "specs/a.md"
    spec.write_text(spec.read_text().replace("  - src/a\n", "  - src/b\n"))
    assert status(fixture.run(), "a") == "stale"
    fixture.run(refresh=True)
    for _ in range(10):
        fixture.run()
    due = fixture.run()
    assert due["full_validation_due"] is True
    assert due["full_validation"] is True
    assert due["cache_hit"] is False


def test_nested_sources_index_and_ignore_changes_are_not_trusted_hits(
    tmp_path: Path,
) -> None:
    fixture = Fixture(tmp_path, "inputs")
    fixture.run()
    nested = "clis/workflow/member/src/lib.rs"
    path = fixture.repository / nested
    path.parent.mkdir(parents=True)
    path.write_text("pub fn member() {}\n")
    result = fixture.run()
    assert nested in result["unmatched"] and "clis/workflow/member" in result["missing"]
    index = fixture.knowledge / "specs/index.md"
    index.write_text("---\nsource_commit: old\n---\n")
    assert fixture.run()["cache_hit"] is False
    index.write_text("---\nsource_commit: new\n---\n")
    assert fixture.run()["full_validation"] is True
    (fixture.repository / ".gitignore").write_text("src/a/ignored.rs\n")
    assert fixture.run()["full_validation"] is True
    (fixture.repository / "src/a/ignored.rs").write_text("fn ignored() {}\n")
    assert status(fixture.run(), "a") == "reuse"
    (fixture.repository / ".gitignore").write_text("")
    unignored = fixture.run()
    assert unignored["cache_hit"] is False and status(unignored, "a") == "stale"
    assert unignored["domains"] == fixture.run(refresh=True)["domains"]
    (fixture.repository / ".git/info/exclude").write_text("*.scratch\n")
    assert fixture.run()["full_validation"] is True


@pytest.mark.parametrize(
    "declaration",
    ["k8s/service.yaml", "helm/Chart.yaml", "terraform/main.tf", "go.mod"],
)
def test_new_declaration_outside_architecture_roots_is_stale_on_warm_and_full(
    tmp_path: Path, declaration: str
) -> None:
    fixture = Fixture(tmp_path, declaration.replace("/", "-"))
    (fixture.repository / "Cargo.toml").write_text("[workspace]\n")
    architecture_spec(fixture)
    assert status(fixture.run(), "architecture") == "reuse"
    path = fixture.repository / declaration
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("deployment: changed\n")
    warm = fixture.run()
    assert warm["cache_hit"] is True and status(warm, "architecture") == "stale"
    assert warm["domains"] == fixture.run(refresh=True)["domains"]


def test_committed_only_change_and_rename_match_forced_refresh(tmp_path: Path) -> None:
    fixture = Fixture(tmp_path, "commit-rename")
    fixture.run()
    (fixture.repository / "src/a/main.rs").write_text("fn committed() {}\n")
    fixture.git("add", "src/a/main.rs")
    fixture.git("commit", "-qm", "change a without inventory")
    committed = fixture.run()
    assert committed["cache_hit"] is True
    assert status(committed, "a") == "stale" and status(committed, "b") == "reuse"
    assert committed["domains"] == fixture.run(refresh=True)["domains"]
    fixture.git("mv", "src/b/main.rs", "src/b/renamed.rs")
    renamed = fixture.run()
    assert status(renamed, "b") == "stale"
    assert renamed["domains"] == fixture.run(refresh=True)["domains"]


def test_cache_does_not_cross_repository_roots(tmp_path: Path) -> None:
    first = Fixture(tmp_path, "first")
    second = Fixture(tmp_path, "second")
    assert first.run()["cache_hit"] is False
    assert first.run()["cache_hit"] is True
    foreign = inventory(
        second.repository,
        first.knowledge,
        first.working,
        clock=lambda: second.now,
        git=second.git_access,
    )
    assert foreign["cache_hit"] is False
    assert foreign["domains"] == first.run(refresh=True)["domains"]


def test_generic_config_without_architecture_spec_is_only_a_candidate(
    tmp_path: Path,
) -> None:
    fixture = Fixture(tmp_path, "config-candidate")
    sample = fixture.repository / "data/sample.json"
    sample.parent.mkdir()
    sample.write_text("{}\n")
    result = fixture.run()
    assert result["architecture_status"] == "none"
    assert result["architecture_candidates"] == ["data/sample.json"]
    assert "data" not in result["missing"]
    (fixture.repository / "Cargo.toml").write_text("[workspace]\n")
    definite = fixture.run()
    assert definite["architecture_status"] == "missing"
    assert definite["architecture_candidates"] == ["data/sample.json"]


def test_unknown_new_paths_require_inspection_and_can_be_acknowledged(
    tmp_path: Path,
) -> None:
    fixture = Fixture(tmp_path, "unknown")
    (fixture.repository / "Cargo.toml").write_text("[workspace]\n")
    architecture_spec(fixture)
    assert status(fixture.run(), "architecture") == "reuse"
    unknown = fixture.repository / "ops/binding.custom"
    unknown.parent.mkdir()
    unknown.write_text("unit = api\n")
    warm = fixture.run()
    assert warm["cache_hit"] is True and status(warm, "architecture") == "inspect"
    assert warm["architecture_inspect_paths"] == ["ops/binding.custom"]
    assert "ops/binding.custom" in warm["unclassified_paths"]
    assert fixture.run()["unclassified_paths"] == []
    refreshed = fixture.run(refresh=True)
    assert status(refreshed, "architecture") == "inspect"
    assert "ops/binding.custom" in refreshed["unclassified_paths"]
    acknowledged = fixture.run(acknowledge="ops/binding.custom")
    assert status(acknowledged, "architecture") == "reuse"
    assert acknowledged["architecture_inspect_paths"] == []
    assert status(fixture.run(refresh=True), "architecture") == "reuse"
    unknown.write_text("unit = other\n")
    assert status(fixture.run(), "architecture") == "inspect"
    unknown.unlink()
    assert status(fixture.run(), "architecture") == "reuse"

    cold = Fixture(tmp_path, "unknown-cold")
    (cold.repository / "Cargo.toml").write_text("[workspace]\n")
    architecture_spec(cold)
    cold_path = cold.repository / "ops/binding.custom"
    cold_path.parent.mkdir()
    cold_path.write_text("unit = api\n")
    assert status(cold.run(refresh=True), "architecture") == "inspect"

    committed = Fixture(tmp_path, "unknown-committed")
    (committed.repository / "Cargo.toml").write_text("[workspace]\n")
    architecture_spec(committed)
    assert status(committed.run(), "architecture") == "reuse"
    committed_path = committed.repository / "ops/binding.custom"
    committed_path.parent.mkdir()
    committed_path.write_text("unit = api\n")
    committed.git("add", "ops/binding.custom")
    committed.git("commit", "-qm", "add unknown path")
    assert status(committed.run(), "architecture") == "inspect"
    assert status(committed.run(refresh=True), "architecture") == "inspect"

    indexed = Fixture(tmp_path, "unknown-indexed")
    baseline = indexed.git("rev-parse", "HEAD").decode().strip()
    (indexed.knowledge / "specs/index.md").write_text(
        f"---\nsource_commit: {baseline}\n---\n"
    )
    (indexed.repository / "Cargo.toml").write_text("[workspace]\n")
    architecture_spec(indexed)
    indexed_path = indexed.repository / "ops/binding.custom"
    indexed_path.parent.mkdir()
    indexed_path.write_text("unit = api\n")
    indexed.git("add", "ops/binding.custom")
    indexed.git("commit", "-qm", "add unknown path")
    assert status(indexed.run(refresh=True), "architecture") == "inspect"

    generic = Fixture(tmp_path, "ambiguous-config")
    (generic.repository / "Cargo.toml").write_text("[workspace]\n")
    architecture_spec(generic)
    assert status(generic.run(), "architecture") == "reuse"
    setting = generic.repository / "data/settings.json"
    setting.parent.mkdir()
    setting.write_text("{}\n")
    assert status(generic.run(), "architecture") == "inspect"
    assert status(generic.run(refresh=True), "architecture") == "inspect"
    assert (
        status(generic.run(acknowledge="data/settings.json"), "architecture") == "reuse"
    )
    assert status(generic.run(refresh=True), "architecture") == "reuse"

    readme = generic.repository / "deploy/README.md"
    readme.parent.mkdir()
    readme.write_text("notes\n")
    result = generic.run()
    assert status(result, "architecture") == "inspect"
    assert result["architecture_inspect_paths"] == ["deploy/README.md"]
    assert (
        status(generic.run(acknowledge="deploy/README.md"), "architecture") == "reuse"
    )


def test_cache_expires_after_twenty_four_hours_and_ten_reuses(tmp_path: Path) -> None:
    fixture = Fixture(tmp_path, "expiry")
    assert fixture.run()["full_validation"] is True
    for _ in range(10):
        assert fixture.run()["full_validation"] is False
    due = fixture.run()
    assert due["full_validation_due"] is True and due["full_validation"] is True
    fixture.now += 24 * 60 * 60
    expired = fixture.run()
    assert expired["full_validation_due"] is True and expired["full_validation"] is True
