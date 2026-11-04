from varde_code.quality_pass.facts import extract_facts


def test_csharp_properties_partial_types_roles_async_and_lambda_calls():
    source = (
        """using Xunit;
record Point(int X, int Y);
class Base { public int Value() { return 1; } }
partial class Child : Base {
    private int Secret() { return 1; }
    public int GetX() { return 1; }
    public override int Value() { return 2; }
    [Fact] public void Handles() { System.Action task = () => Value(); }
    public int X { get; set; }
    public async Task<int> GoAsync() { return await Get(); }
    public List<int> Filter(List<int> items) { """
        "return items.Where(item => item > 0).Select(item => item).ToList(); }\n"
        """
}
partial class Child { public int Count { get; } }
"""
    )

    facts = extract_facts(source, "csharp", "Point.cs")
    by_name = {(item["owner"], item["name"]): item for item in facts["functions"]}

    assert facts["language"] == "csharp"
    assert set(by_name) == {
        ("Base", "Value"),
        ("Child", "Secret"),
        ("Child", "GetX"),
        ("Child", "Value"),
        ("Child", "Handles"),
        ("Child", "GoAsync"),
        ("Child", "Filter"),
    }
    assert by_name[("Child", "Secret")]["file_private"] is True
    assert by_name[("Child", "GetX")]["file_private"] is False
    assert by_name[("Child", "Value")]["exempt_role"] == "override"
    assert by_name[("Child", "Handles")]["exempt_role"] == "handler"
    assert by_name[("Child", "GoAsync")]["tokens"] == 17
    assert facts["call_sites"] == [
        {
            "caller": by_name[("Child", "Handles")]["id"],
            "name": "Value",
            "receiver": None,
            "receiver_text": None,
            "arity": 0,
            "line": 8,
        },
        {
            "caller": by_name[("Child", "GoAsync")]["id"],
            "name": "Get",
            "receiver": None,
            "receiver_text": None,
            "arity": 0,
            "line": 10,
        },
        {
            "caller": by_name[("Child", "Filter")]["id"],
            "name": "ToList",
            "receiver": None,
            "receiver_text": None,
            "arity": 0,
            "line": 11,
        },
        {
            "caller": by_name[("Child", "Filter")]["id"],
            "name": "Select",
            "receiver": None,
            "receiver_text": None,
            "arity": 1,
            "line": 11,
        },
        {
            "caller": by_name[("Child", "Filter")]["id"],
            "name": "Where",
            "receiver": None,
            "receiver_text": "items",
            "arity": 1,
            "line": 11,
        },
    ]


def test_csharp_attribute_without_framework_using_is_not_a_handler():
    facts = extract_facts(
        "class Example { [Fact] public void Check() { return; } }", "csharp"
    )

    assert facts["functions"][0]["name"] == "Check"
    assert facts["functions"][0]["exempt_role"] is None
