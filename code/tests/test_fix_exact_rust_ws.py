from varde_code.extract.entity import extract_file
from varde_code.model import EntityKind


def test_rust_recursion_markers_match_same_file_callable_cycles():
    source = """
fn direct(value: i32) -> i32 {
    if value <= 0 { 0 } else { direct(value - 1) }
}

fn cycle_a(value: i32) -> i32 { cycle_b(value) }
fn cycle_b(value: i32) -> i32 { cycle_a(value) }

fn outer(value: i32) -> i32 {
    fn inner(value: i32) -> i32 {
        if value <= 0 { 0 } else { inner(value - 1) }
    }
    inner(value)
}

struct Worker;
impl Worker {
    fn method(&self, value: i32) -> i32 {
        if value <= 0 { 0 } else { self.method(value - 1) }
    }

    fn delegates_to_other(&self, other: &Worker, value: i32) -> i32 {
        other.method(value - 1)
    }
}
"""

    output = extract_file("fixture.rs", source, "rust")
    recursion = [
        (entity.enclosing_function, entity.owner_type)
        for entity in output.entities
        if entity.kind == EntityKind.CONTROL_FLOW and entity.name == "recursive_call"
    ]

    assert recursion == [
        ("direct", None),
        ("cycle_a", None),
        ("cycle_b", None),
        ("inner", None),
        ("method", "Worker"),
    ]
