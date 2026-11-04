"""Behavior tests for the call-resolution audit runner."""

import json
import subprocess
import sys
from pathlib import Path

import pytest
from run import runner


class FakeAdapter:
    def __init__(self):
        self.exports = 0

    def export_edges(self, repo_path):
        self.exports += 1
        return Path(repo_path) / "edges.jsonl"


class FailingAdapter:
    def export_edges(self, repo_path):
        raise RuntimeError("isolated index build failed; inner stderr tail:\nBOOM-tail")


class UnimplementedAdapter:
    def export_edges(self, repo_path):
        raise NotImplementedError("adapter not implemented")


class TimingOutAdapter:
    def export_edges(self, repo_path, timeout_seconds=None):
        raise subprocess.TimeoutExpired(["venv-python", "-c", "build"], timeout_seconds)


def _record(**changes):
    record = {
        "repo": "sample/project",
        "language": "python",
        "file": "src/main.py",
        "line": 4,
        "call_class": "same_file",
        "ground_truth": "src/target.py::work@7",
        "measured_edge": None,
        "measured_status": "unresolved",
        "truth_source": "hand-labeled",
        "function_id": "src/main.py::run@1",
        "module": "src.main",
        "ground_truth_module": "src.target",
    }
    return record | changes


def _resolved_edge(**changes):
    edge = {
        "file": "src/main.py",
        "site_line": 4,
        "name": "work",
        "callee": "17",
        "callee_file": "src/target.py",
        "callee_name": "work",
        "callee_line": 7,
        "kind": "resolved",
        "pass": "local",
    }
    return edge | changes


def _write_records(folder, records):
    folder.mkdir(parents=True)
    (folder / "sample.jsonl").write_text(
        "".join(json.dumps(record) + "\n" for record in records), encoding="utf-8"
    )


def _setup(monkeypatch, tmp_path, role="dev", adapter=None):
    data_root = tmp_path / "data" / "dev"
    group = data_root / "python-ts"
    _write_records(group, [_record()])
    (tmp_path / "repos").mkdir()
    (tmp_path / "repos" / "python-ts.toml").write_text(
        '[repos."sample/project"]\nurl = "file:///unused"\nsha = "abc"\n'
        f'language = "python"\nrole = "{role}"\n',
        encoding="utf-8",
    )
    cache = tmp_path / "cache"
    repo_path = cache / "sample__project"
    repo_path.mkdir(parents=True)
    (repo_path / "edges.jsonl").write_text(
        json.dumps(_resolved_edge()) + "\n", encoding="utf-8"
    )
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner, "DEFAULT_EDGE_CACHE_DIR", tmp_path / "edge-cache")
    monkeypatch.setattr(runner, "_load_adapter", lambda name: adapter or FakeAdapter())
    monkeypatch.setattr(runner, "_checkout_repo", lambda name, repos, path: repo_path)
    restricted = tmp_path / "restricted"
    test_group = restricted / "python-ts"
    _write_records(test_group, [_record()])
    lock_file = tmp_path / "test-run.lock"
    return cache, restricted, lock_file


def _args(split, cache, restricted, lock_file, *extra):
    return [
        "--adapter",
        "existing",
        "--split",
        split,
        "--repo-cache",
        str(cache),
        "--restricted-dir",
        str(restricted),
        "--lock-file",
        str(lock_file),
        *extra,
    ]


def test_dev_split_reports_metrics_from_group_jsonl(monkeypatch, tmp_path, capsys):
    cache, restricted, lock_file = _setup(monkeypatch, tmp_path)
    restricted = tmp_path / "does-not-exist"

    result = runner.main(_args("dev", cache, restricted, lock_file))

    output = capsys.readouterr().out
    assert result == 0
    assert f"inputs: {tmp_path / 'data' / 'dev'}" in output
    assert "pending review records skipped: 0" in output
    assert (
        "python: precision=1.0000 recall=1.0000 resolved_share=1.0000 "
        "depth_error_le1=1.0000" in output
    )
    assert not lock_file.exists()


def test_test_split_uses_restricted_dir_and_allows_only_one_run(
    monkeypatch, tmp_path, capsys
):
    cache, restricted, lock_file = _setup(monkeypatch, tmp_path, role="test-only")
    args = _args("test", cache, restricted, lock_file)

    assert runner.main(args) == 0
    assert f"inputs: {restricted}" in capsys.readouterr().out
    assert lock_file.exists()
    script = (
        "import sys; from pathlib import Path; "
        f"sys.path.insert(0, {str(Path(__file__).resolve().parents[2])!r}); "
        "from run import runner; "
        f"runner.ROOT = Path({str(tmp_path)!r}); "
        f"runner.DEFAULT_EDGE_CACHE_DIR = Path({str(tmp_path / 'edge-cache')!r}); "
        "import types; "
        "runner._load_adapter = lambda name: types.SimpleNamespace("
        "export_edges=lambda repo_path: Path(repo_path) / 'edges.jsonl'); "
        f"runner._checkout_repo = lambda name, repos, cache: "
        f"Path({str(cache / 'sample__project')!r}); "
        f"runner.main({args!r})"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script], check=False, capture_output=True, text=True
    )
    assert completed.returncode != 0
    assert "already run" in completed.stderr


def test_test_split_accepts_test_only_repo_entry(monkeypatch, tmp_path, capsys):
    cache, restricted, lock_file = _setup(monkeypatch, tmp_path, role="test-only")

    assert runner.main(_args("test", cache, restricted, lock_file)) == 0

    assert "pending review records skipped: 0" in capsys.readouterr().out
    assert lock_file.exists()


def test_dev_split_rejects_test_only_repo_entry(monkeypatch, tmp_path):
    cache, restricted, lock_file = _setup(monkeypatch, tmp_path, role="test-only")

    with pytest.raises(ValueError, match="dev split.*test-only"):
        runner.main(_args("dev", cache, restricted, lock_file))


def test_test_split_requires_explicit_allow_for_pending_review_records(
    monkeypatch, tmp_path, capsys
):
    cache, restricted, lock_file = _setup(monkeypatch, tmp_path, role="test-only")
    pending_file = restricted / "python-ts" / "pending.jsonl"
    pending_file.write_text(
        json.dumps(
            {
                "status": "pending_human_verification",
                "site": {"repo": "sample/project"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    args = _args("test", cache, restricted, lock_file)

    script = (
        "import sys; from pathlib import Path; "
        f"sys.path.insert(0, {str(Path(__file__).resolve().parents[2])!r}); "
        "from run import runner; "
        f"runner.ROOT = Path({str(tmp_path)!r}); "
        f"runner.main({args!r})"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script], check=False, capture_output=True, text=True
    )
    assert completed.returncode != 0
    assert "--allow-pending-skip" in completed.stderr
    assert not lock_file.exists()

    assert runner.main([*args, "--allow-pending-skip"]) == 0
    assert "pending review records skipped: 1" in capsys.readouterr().out
    assert lock_file.exists()


def test_quality_adapter_exports_empty_edge_file_for_repo_without_sources(tmp_path):
    from adapters.quality import export_edges

    output = export_edges(tmp_path)
    try:
        assert output.is_file()
        assert output.read_text(encoding="utf-8") == ""
    finally:
        output.unlink(missing_ok=True)


def test_quality_adapter_can_be_selected_by_runner(monkeypatch, capsys, tmp_path):
    cache, restricted, lock_file = _setup(monkeypatch, tmp_path)
    monkeypatch.setattr(
        runner,
        "_load_adapter",
        lambda name: __import__("adapters.quality", fromlist=["export_edges"]),
    )

    result = runner.main(_args("dev", cache, restricted, lock_file))

    assert result == 0
    assert (
        "python: precision=n/a recall=0.0000 resolved_share=0.0000"
        in capsys.readouterr().out
    )
    assert not lock_file.exists()


def test_edges_are_matched_by_file_and_line():
    records = [_record(), _record(file="src/other.py")]

    runner._apply_edges(
        "sample/project",
        records,
        [_resolved_edge()],
    )

    assert records[0]["measured_edge"] == "src/target.py::work@7"
    assert records[0]["measured_status"] == "resolved"
    assert records[1]["measured_edge"] is None
    assert records[1]["measured_status"] == "unresolved"


def test_same_name_in_another_file_is_not_a_match():
    records = [_record(ground_truth="src/other.py::work@7")]

    runner._apply_edges("sample/project", records, [_resolved_edge()])

    assert records[0]["measured_status"] == "resolved"
    assert records[0]["measured_edge"] == "index:src/target.py:7:work"


def test_same_name_on_another_line_is_not_a_match():
    records = [_record(ground_truth="src/target.py::work@11")]

    runner._apply_edges("sample/project", records, [_resolved_edge()])

    assert records[0]["measured_edge"] == "index:src/target.py:7:work"


def test_line_less_target_matches_a_line_bearing_measured_target():
    record = _record(
        language="java",
        file="src/Ai.java",
        ground_truth="src/Ai.java::org.example.Ai.calculate(int,int)",
        module="org.example",
        ground_truth_module="org.example",
        function_id="src/Ai.java::org.example.Ai.run()",
    )
    edge = _resolved_edge(
        file="src/Ai.java",
        callee_file="src/Ai.java",
        callee_name="calculate",
        callee_line=42,
        name="calculate",
    )

    runner._apply_edges("sample/project", [record], [edge])

    assert record["measured_edge"] == "src/Ai.java::org.example.Ai.calculate(int,int)"
    assert record["measured_status"] == "resolved"


def test_runner_join_keeps_same_line_calls_in_separate_files():
    records = [
        _record(file="src/first.py", ground_truth="targets/first.py::target_first@3"),
        _record(
            file="src/second.py", ground_truth="targets/second.py::target_second@3"
        ),
    ]
    edges = [
        _resolved_edge(
            file="src/first.py",
            callee_file="targets/first.py",
            callee_name="target_first",
            callee_line=3,
        ),
        _resolved_edge(
            file="src/second.py",
            callee_file="targets/second.py",
            callee_name="target_second",
            callee_line=3,
        ),
    ]

    runner._apply_edges("sample/project", records, edges)

    assert [record["measured_edge"] for record in records] == [
        "targets/first.py::target_first@3",
        "targets/second.py::target_second@3",
    ]


def test_runner_disambiguates_nested_calls_on_one_line():
    records = [
        _record(ground_truth="src/b.py::b@1"),
        _record(call_name="x", ground_truth="src/x.py::x@1"),
    ]
    edges = [
        _resolved_edge(
            name="b", callee_file="src/b.py", callee_name="b", callee_line=1
        ),
        _resolved_edge(
            name="x", callee_file="src/x.py", callee_name="x", callee_line=1
        ),
    ]

    runner._apply_edges("sample/project", records, edges)

    assert [record["measured_edge"] for record in records] == [
        "src/b.py::b@1",
        "src/x.py::x@1",
    ]
    assert [record["measured_status"] for record in records] == [
        "resolved",
        "resolved",
    ]


def test_unmatched_nested_call_is_recorded_as_ambiguous():
    records = [_record(ground_truth="unknown")]
    edges = [
        _resolved_edge(name="a"),
        _resolved_edge(name="b"),
    ]

    runner._apply_edges("sample/project", records, edges)

    assert records[0]["measured_edge"] is None
    assert records[0]["measured_status"] == "ambiguous"


def test_resolved_edge_without_callee_identity_asks_for_a_cache_rebuild():
    with pytest.raises(TypeError, match="--refresh-edges"):
        runner._apply_edges(
            "sample/project",
            [_record()],
            [{"file": "src/main.py", "site_line": 4, "kind": "resolved"}],
        )


def test_failed_test_split_does_not_create_lock(monkeypatch, tmp_path):
    cache, restricted, lock_file = _setup(
        monkeypatch, tmp_path, role="test-only", adapter=UnimplementedAdapter()
    )

    with pytest.raises(NotImplementedError, match="not implemented"):
        runner.main(_args("test", cache, restricted, lock_file))

    assert not lock_file.exists()


def test_local_pinned_repository_checkout_and_toml_loader(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    subprocess.run(["git", "init", "-q", str(source)], check=True)
    subprocess.run(
        ["git", "-C", str(source), "config", "user.email", "test@example.com"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(source), "config", "user.name", "Runner Test"], check=True
    )
    (source / "sample.txt").write_text("pinned\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(source), "add", "sample.txt"], check=True)
    subprocess.run(["git", "-C", str(source), "commit", "-qm", "fixture"], check=True)
    sha = subprocess.run(
        ["git", "-C", str(source), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    repos_dir = tmp_path / "repos"
    repos_dir.mkdir()
    (repos_dir / "local.toml").write_text(
        f'[repos."sample/project"]\nurl = "{source.as_uri()}"\nsha = "{sha}"\n'
        'language = "python"\nrole = "dev"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(runner, "ROOT", tmp_path)

    repos = runner._load_repositories("local")
    checkout = runner._checkout_repo("sample/project", repos, tmp_path / "cache")

    assert (checkout / "sample.txt").read_text(encoding="utf-8") == "pinned\n"
    assert (
        subprocess.run(
            ["git", "-C", str(checkout), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        == sha
    )


def test_missing_group_repository_manifest_has_clear_error(tmp_path, monkeypatch):
    (tmp_path / "repos").mkdir()
    monkeypatch.setattr(runner, "ROOT", tmp_path)

    with pytest.raises(
        FileNotFoundError, match="missing pinned repositories file.*python-ts"
    ):
        runner._load_repositories("python-ts")


def test_edge_cache_reuses_exported_edges(monkeypatch, tmp_path, capsys):
    adapter = FakeAdapter()
    cache, restricted, lock_file = _setup(monkeypatch, tmp_path, adapter=adapter)
    records_dir = tmp_path / "records"
    metrics_json = tmp_path / "metrics.json"
    args = _args(
        "dev",
        cache,
        restricted,
        lock_file,
        "--records-dir",
        str(records_dir),
        "--metrics-json",
        str(metrics_json),
    )

    assert runner.main(args) == 0
    assert adapter.exports == 1
    cached = tmp_path / "edge-cache" / "sample__project__abc.jsonl"
    assert cached.is_file()

    assert runner.main(args) == 0
    assert adapter.exports == 1
    capsys.readouterr()
    assert (records_dir / "python-progress-records.jsonl").is_file()
    assert json.loads(metrics_json.read_text())["python"]["precision"] == 1.0


def test_export_failure_is_recorded_and_sites_stay_unresolved(
    monkeypatch, tmp_path, capsys
):
    cache, restricted, lock_file = _setup(
        monkeypatch, tmp_path, adapter=FailingAdapter()
    )
    failures = tmp_path / "failures.jsonl"
    records_dir = tmp_path / "records"

    assert (
        runner.main(
            _args(
                "dev",
                cache,
                restricted,
                lock_file,
                "--failures-jsonl",
                str(failures),
                "--records-dir",
                str(records_dir),
            )
        )
        == 0
    )

    entry = json.loads(failures.read_text().strip())
    assert entry["repo"] == "sample/project"
    assert entry["status"] == "worker_failure"
    assert "BOOM-tail" in entry["evidence"]
    assert entry["sites_unresolved_by_failure"] == 1
    record = json.loads(
        (records_dir / "python-progress-records.jsonl").read_text().strip()
    )
    assert record["measured_status"] == "unresolved"
    assert "resolved_share=0.0000" in capsys.readouterr().out


def test_export_timeout_is_recorded_as_an_index_build_timeout(monkeypatch, tmp_path):
    cache, restricted, lock_file = _setup(
        monkeypatch, tmp_path, adapter=TimingOutAdapter()
    )
    failures = tmp_path / "failures.jsonl"

    assert (
        runner.main(
            _args(
                "dev",
                cache,
                restricted,
                lock_file,
                "--failures-jsonl",
                str(failures),
                "--export-timeout-seconds",
                "60",
            )
        )
        == 0
    )

    entry = json.loads(failures.read_text().strip())
    assert entry["status"] == "index_build_timeout"
    assert "60.0s" in entry["evidence"]


def test_skip_repo_keeps_its_records_unresolved(monkeypatch, tmp_path, capsys):
    adapter = FakeAdapter()
    cache, restricted, lock_file = _setup(monkeypatch, tmp_path, adapter=adapter)
    records_dir = tmp_path / "records"

    assert (
        runner.main(
            _args(
                "dev",
                cache,
                restricted,
                lock_file,
                "--skip-repo",
                "sample/project",
                "--records-dir",
                str(records_dir),
            )
        )
        == 0
    )

    assert adapter.exports == 0
    record = json.loads(
        (records_dir / "python-progress-records.jsonl").read_text().strip()
    )
    assert record["measured_status"] == "unresolved"
    assert "resolved_share=0.0000" in capsys.readouterr().out


def test_metrics_only_recomputes_from_saved_records_without_an_adapter(
    monkeypatch, tmp_path, capsys
):
    records_dir = tmp_path / "records"
    records_dir.mkdir()
    record = _record(
        measured_edge="src/target.py::work@7",
        measured_status="resolved",
        measured_file="src/target.py",
        measured_name="work",
        measured_line=7,
    )
    (records_dir / "python-progress-records.jsonl").write_text(
        json.dumps(record) + "\n", encoding="utf-8"
    )
    metrics_json = tmp_path / "metrics.json"
    monkeypatch.setattr(runner, "_load_adapter", lambda name: pytest.fail("adapter"))

    assert (
        runner.main(
            [
                "--adapter",
                "existing",
                "--split",
                "dev",
                "--repo-cache",
                str(tmp_path / "cache"),
                "--records-dir",
                str(records_dir),
                "--metrics-json",
                str(metrics_json),
                "--metrics-only",
            ]
        )
        == 0
    )

    assert "python: precision=1.0000 recall=1.0000" in capsys.readouterr().out
    assert json.loads(metrics_json.read_text())["python"]["precision"] == 1.0


def test_repo_filters_reject_unknown_names(monkeypatch, tmp_path):
    cache, restricted, lock_file = _setup(monkeypatch, tmp_path)

    with pytest.raises(ValueError, match="not pinned in this split"):
        runner.main(
            _args("dev", cache, restricted, lock_file, "--repo", "unknown/repo")
        )


def test_repo_time_limit_names_the_repository():
    import time

    with (
        pytest.raises(runner.RepoTimeLimitExceeded, match="big/repo"),
        runner._repo_time_limit("big/repo", 0.05),
    ):
        time.sleep(2)


def test_repo_time_limit_zero_disables():
    with runner._repo_time_limit("any/repo", 0):
        pass
