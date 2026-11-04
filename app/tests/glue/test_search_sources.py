import json

from varde.glue.search.code import CodeSearch
from varde.glue.search.friction import FrictionSearch
from varde.glue.search.knowledge import KnowledgeSearch
from varde.glue.search.toz import TozScope, TozSearch
from varde.glue.search.types import SearchQuery
from varde_data.friction import open_friction
from varde_data.repos.friction import FrictionAddRequest
from varde_toz.capture import CaptureInput, capture
from varde_toz.config import config_dir
from varde_toz.project import store_db_path


def test_code_search_maps_context_pack_results(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    db_path = tmp_path / "code.db"
    monkeypatch.setattr(
        "varde.glue.search.code.run_mode",
        lambda *_: json.dumps(
            {
                "ok": True,
                "data": {
                    "files": [{"path": "sample.py", "relevance": "path"}],
                    "symbols": [
                        {
                            "name": "needle_handler",
                            "filePath": "sample.py",
                            "kind": "function",
                            "span": {"start_line": 1},
                        }
                    ],
                },
            }
        ),
    )

    result = CodeSearch(repo, db_path).search(SearchQuery("needle_handler", 5))

    assert result.source == "code"
    assert any(hit.title == "needle_handler" for hit in result.hits or ())


def test_code_search_missing_index_is_unavailable_without_building(tmp_path):
    db_path = tmp_path / "missing.db"

    result = CodeSearch(tmp_path, db_path).search(SearchQuery("needle", 5))

    assert result.reason == "index_missing"
    assert not db_path.exists()


def test_friction_search_reads_existing_store_and_limits(tmp_path):
    repo = open_friction(tmp_path)
    for title in ("needle one", "needle two"):
        repo.add(
            FrictionAddRequest(
                title=title,
                source="test",
                evidence="evidence",
                cwd=str(tmp_path),
                global_=True,
            )
        )

    result = FrictionSearch(tmp_path).search(SearchQuery("needle", 1))

    assert result.hits is not None
    assert len(result.hits) == 1
    assert result.hits[0].source == "friction"
    assert result.hits[0].snippet == "open (test)"


def test_friction_missing_store_is_unavailable_without_creation(tmp_path):
    store_dir = tmp_path / "missing"

    result = FrictionSearch(store_dir).search(SearchQuery("needle", 5))

    assert result.reason == "no friction store"
    assert not store_dir.exists()


def test_friction_empty_directory_is_unavailable_without_creation(tmp_path):
    store_dir = tmp_path / "empty"
    store_dir.mkdir()

    result = FrictionSearch(store_dir).search(SearchQuery("needle", 5))

    assert result.reason == "no friction store"
    assert list(store_dir.iterdir()) == []


def test_knowledge_search_returns_ranked_concept(tmp_path):
    bundle = tmp_path / "knowledge"
    bundle.mkdir()
    (bundle / "alpha.md").write_text(
        "---\ntitle: Alpha\n---\n# Alpha\nneedle knowledge\n"
    )

    result = KnowledgeSearch(bundle).search(SearchQuery("needle", 5))

    assert result.source == "knowledge"
    assert result.hits is not None
    assert result.hits[0].location == "alpha"
    assert "needle" in result.hits[0].snippet


def test_knowledge_missing_bundle_is_unavailable(tmp_path):
    result = KnowledgeSearch(tmp_path / "missing").search(SearchQuery("needle", 5))

    assert result.reason == "knowledge bundle not found"


def test_toz_output_search_excludes_index_records(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setenv("HOME", str(tmp_path))
    db_path = store_db_path(repo, config_dir())
    capture(
        CaptureInput(b"needle captured", label="capture", source="test", force=True),
        repo,
        db_path,
    )
    capture(
        CaptureInput(
            b"needle indexed",
            label="index",
            source=str(repo / "doc.md"),
            kind="index",
            force=True,
        ),
        repo,
        db_path,
    )

    result = TozSearch(TozScope.OUTPUT, db_path, repo).search(SearchQuery("needle", 5))

    assert result.source == "output"
    assert result.hits is not None
    assert len(result.hits) == 1
    assert result.hits[0].title == "capture"


def test_toz_docs_indexes_and_returns_repo_relative_location(tmp_path):
    import subprocess

    repo = tmp_path / "repo"
    (repo / "work").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)  # noqa: S603,S607,RUF100 - Initializes a temporary Git repository fixture for this test.
    doc = repo / "README.md"
    doc.write_text("# Documentation\nneedle docs\n")
    db_path = tmp_path / "toz.db"

    result = TozSearch(TozScope.DOCS, db_path, repo, repo / "work").search(
        SearchQuery("needle", 5)
    )

    assert result.source == "docs"
    assert result.hits is not None
    assert result.hits[0].location.startswith("README.md:")


def test_code_error_envelope_maps_to_unavailable(monkeypatch):
    monkeypatch.setattr(
        "varde.glue.search.code.run_mode",
        lambda *_: json.dumps({"ok": False, "data": {"error": {"code": "db_error"}}}),
    )
    from varde.glue.search.code import code_hits_from_envelope

    assert code_hits_from_envelope("{}", 2).reason == "error"
    assert (
        code_hits_from_envelope(
            json.dumps({"ok": False, "data": {"error": {"code": "db_error"}}}), 2
        ).reason
        == "db_error"
    )
