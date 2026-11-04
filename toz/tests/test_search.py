from varde_toz.chunk import chunk_default
from varde_toz.search import search
from varde_toz.store import NewCapture, Store


def _store(tmp_path, bodies):
    store = Store.open(tmp_path / "toz.db")
    handles = []
    for label, body in bodies:
        chunks = [("stdout", chunk) for chunk in chunk_default(body)]
        handles.append(
            store.insert_capture(
                NewCapture(
                    label=label, kind="run", source=label, bytes=len(body), exit_code=0
                ),
                chunks,
            )
        )
    return store, handles


def test_query_corrects_a_typo_from_trigram_candidates(tmp_path):
    store, _ = _store(tmp_path, [("docs", "connection refused in database startup")])
    try:
        result = search(store, ["conection"], limit=3)[0]
        assert result["corrected"] == "connection"
        assert len(result["hits"]) == 1
    finally:
        store.close()


def test_search_ranks_clustered_terms_above_distant_terms(tmp_path):
    close = "alpha beta\n"
    far = "alpha\n" + "filler line\n" * 30 + "beta\n"
    store, _ = _store(tmp_path, [("close", close), ("far", far)])
    try:
        hits = search(store, ["alpha beta"], limit=3)[0]["hits"]
    finally:
        store.close()
    assert hits[0]["label"] == "close"


def test_search_snippet_selects_dense_hit_cluster_and_clips_by_bytes(tmp_path):
    body = "intro\n" + "quiet\n" * 8 + "alpha\nbeta\ngamma\n" + ("é" * 400) + "\nlast"
    store, _ = _store(tmp_path, [("fixture", body)])
    try:
        hit = search(store, ["alpha beta"], limit=1)[0]["hits"][0]
    finally:
        store.close()
    assert "alpha" in hit["snippet"] and "beta" in hit["snippet"]
    assert "intro" not in hit["snippet"]
    assert len(hit["snippet"].encode()) <= 620
