import sqlite3

from varde_code.graph_model import Graph
from varde_code.index.persist.edges import PersistedState, rewrite_edges
from varde_code.index.persist.graph import SqliteGraphCache


def test_rewrite_edges_persists_resolved_and_unresolved_edges_and_fans():
    db = sqlite3.connect(":memory:")
    db.executescript("""
        CREATE TABLE files (id INTEGER PRIMARY KEY, path TEXT, fan_in INTEGER DEFAULT 0,
                           fan_out INTEGER DEFAULT 0, rev INTEGER DEFAULT 0,
                           edges_built_rev INTEGER DEFAULT 0);
        CREATE TABLE entities (id INTEGER PRIMARY KEY, file_id INTEGER);
        CREATE TABLE resolved_edges (id INTEGER PRIMARY KEY, from_file_id INTEGER,
            to_file_id INTEGER, kind INTEGER, resolved INTEGER,
            from_entity_id INTEGER, to_entity_id INTEGER);
        INSERT INTO files(id,path) VALUES (10,'a.py'), (20,'b.py');
        INSERT INTO entities(id,file_id) VALUES (100,10), (200,20);
    """)
    state = PersistedState(
        entities=[{"file_id": 0}, {"file_id": 1}],
        entity_ids=[100, 200],
        files=["a.py", "b.py"],
        file_ids=[10, 20],
        file_index={10: 0, 20: 1},
    )
    edges = [
        {
            "from": 0,
            "to": {"target": "entity", "id": 1},
            "kind": "call",
            "resolved": True,
            "from_entity": 0,
        },
        {
            "from": 1,
            "to": {"target": "unknown"},
            "kind": "import",
            "resolved": False,
            "from_entity": None,
        },
    ]
    nodes = [{"fan_in": 0, "fan_out": 1}, {"fan_in": 1, "fan_out": 0}]

    rewrite_edges(db, state, edges, nodes)

    assert db.execute(
        "SELECT from_file_id,to_file_id,kind,resolved,from_entity_id,to_entity_id "
        "FROM resolved_edges ORDER BY id"
    ).fetchall() == [(10, 20, 0, 1, 100, 200), (20, None, 1, 0, None, None)]
    assert db.execute(
        "SELECT fan_in,fan_out,edges_built_rev FROM files ORDER BY id"
    ).fetchall() == [(0, 1, 0), (1, 0, 0)]


def test_graph_cache_round_trips_python_graph_format(tmp_path):
    db_path = tmp_path / "index.db"
    db = sqlite3.connect(db_path)
    db.execute(
        "CREATE TABLE graph_cache (id INTEGER PRIMARY KEY, blob BLOB NOT NULL, "
        "rev INTEGER NOT NULL)"
    )
    cache = SqliteGraphCache()
    graph = Graph(paths={1: "a.py", 2: "b.py"}, out={1: [2]}, inc={2: [1]})

    cache.write(db_path, graph, 7)

    assert cache.read(db_path, 7) == graph
    assert cache.read(db_path, 8) is None
