import time

from varde_code.quality_resolve import edges_for_file, prepare


def test_prepare_indexes_large_qualified_receiver_input():
    facts = {}
    for index in range(3000):
        path = f"src/Owner{index}.java"
        owner = f"Owner{index}"
        caller = f"{path}::caller"
        facts[path] = {
            "package": f"pkg{index}",
            "functions": [
                {"id": caller, "name": "caller", "params": 0},
                {
                    "id": f"{path}::{owner}.work",
                    "name": "work",
                    "owner": owner,
                    "qualifier": f"pkg{index}.{owner}",
                    "params": 0,
                },
            ],
            "call_sites": [
                {
                    "caller": caller,
                    "name": "work",
                    "receiver_text": f"pkg{index}.{owner}",
                    "arity": 0,
                    "line": line,
                }
                for line in range(10)
            ],
        }

    started = time.perf_counter()
    context = prepare(facts, facts)
    edge_count = sum(len(edges_for_file(context, path)) for path in facts)
    assert edge_count == 30_000
    assert time.perf_counter() - started < 30
