import json
import sys
import tomllib
from pathlib import Path

BENCH = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(BENCH / "groundtruth" / "java-csharp"))

from build_csharp_dev import csharp_roles, pooled_records  # noqa: E402

NEW_DEV = {"JamesNK/Newtonsoft.Json", "App-vNext/Polly", "serilog/serilog"}


def test_pooled_records_keep_only_repos_with_a_role():
    roles = {"a": "dev"}
    rows = pooled_records([{"repo": "a"}, {"repo": "b"}], [{"repo": "a"}], roles)
    assert [row["repo"] for row in rows] == ["a", "a"]


def test_new_csharp_repos_are_dev_with_verified_fields():
    repos = tomllib.loads((BENCH / "repos/java-csharp.toml").read_text())["repo"]
    roles = csharp_roles(repos)
    assert {name for name in NEW_DEV if roles.get(name) == "dev"} == NEW_DEV
    for row in repos:
        if row["name"] in NEW_DEV:
            assert len(row["sha"]) == 40
            assert row["license_first_nonblank_line"]


def test_dev_csharp_sites_cover_new_repos_with_enough_usable_sites():
    lines = (BENCH / "data/dev/java-csharp/csharp.jsonl").read_text().splitlines()
    rows = [json.loads(line) for line in lines]
    assert len(rows) == 300
    assert {row["repo"] for row in rows} >= NEW_DEV
    assert sum(row["ground_truth"] != "unknown" for row in rows) >= 150
