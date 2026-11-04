from varde_code.quality_pass.facts import extract_facts


def test_java_roles_records_visibility_handlers_and_lambda_calls():
    source = """import org.junit.jupiter.api.Test;
record Point(int x, int y) {}
class Base { int value() { return 1; } }
class Child extends Base {
    private int secret() { return 1; }
    private int x;
    public int getX() { return this.x; }
    @Override int value() { return 2; }
    @Test void handles() { Runnable task = () -> value(); }
}
"""

    facts = extract_facts(source, "java", "Point.java")
    by_name = {(item["owner"], item["name"]): item for item in facts["functions"]}

    assert facts["language"] == "java"
    assert set(by_name) == {
        ("Base", "value"),
        ("Child", "secret"),
        ("Child", "getX"),
        ("Child", "value"),
        ("Child", "handles"),
    }
    assert by_name[("Child", "secret")]["file_private"] is True
    assert by_name[("Child", "getX")]["file_private"] is False
    assert by_name[("Child", "getX")]["exempt_role"] == "accessor"
    assert by_name[("Child", "value")]["exempt_role"] == "override"
    assert by_name[("Child", "handles")]["exempt_role"] == "handler"
    assert facts["call_sites"] == [
        {
            "caller": by_name[("Child", "handles")]["id"],
            "name": "value",
            "receiver": None,
            "receiver_text": None,
            "arity": 0,
            "line": 9,
        }
    ]


def test_java_annotation_without_matching_import_is_not_a_handler():
    facts = extract_facts("class Example { @Test void check() { return; } }", "java")

    assert facts["functions"][0]["name"] == "check"
    assert facts["functions"][0]["exempt_role"] is None
