"""Behavior of the TypeScript plugin on JavaScript and TSX files."""

from varde_code.quality_pass.facts import extract_facts

EXPORTED_AND_CALLED = "export function App() { return 1; }\nApp();\n"


def test_javascript_extensions_use_the_export_aware_plugin():
    for path in ("app.js", "app.jsx", "app.mjs", "app.cjs"):
        record = extract_facts(EXPORTED_AND_CALLED, "javascript", path)

        assert record["language"] == "javascript"
        assert [row["file_private"] for row in record["functions"]] == [False]


def test_javascript_default_export_binding_is_public():
    record = extract_facts(
        "function App() { return 1; }\nexport default App;\nApp();\n",
        "javascript",
        "app.js",
    )

    assert [row["file_private"] for row in record["functions"]] == [False]


def test_javascript_class_heritage_marks_the_override():
    record = extract_facts(
        "class Base { render() { return 1; } }\n"
        "class Child extends Base { render() { return 2; } }\n",
        "javascript",
        "app.js",
    )

    roles = {
        (row["owner"], row["name"]): row["exempt_role"] for row in record["functions"]
    }

    assert roles[("Child", "render")] == "override"
    assert roles[("Base", "render")] is None


def test_typescript_implements_clause_is_not_a_base():
    record = extract_facts(
        "class Shape { draw() { return 1; } }\n"
        "class Impl implements Shape { draw() { return 2; } }\n",
        "typescript",
        "shapes.ts",
    )

    roles = {
        (row["owner"], row["name"]): row["exempt_role"] for row in record["functions"]
    }

    assert roles[("Impl", "draw")] is None
    assert roles[("Shape", "draw")] is None


def test_typescript_extends_clause_still_marks_overrides_with_implements():
    record = extract_facts(
        "class Base { render() { return 1; } }\n"
        "class Child extends Base implements Runner { render() { return 2; } }\n",
        "typescript",
        "shapes.ts",
    )

    roles = {
        (row["owner"], row["name"]): row["exempt_role"] for row in record["functions"]
    }

    assert roles[("Child", "render")] == "override"


def test_tsx_exported_component_is_not_file_private():
    record = extract_facts(
        "export function View() { return <div/>; }\nconst used = View();\n",
        "tsx",
        "view.tsx",
    )

    assert record["language"] == "tsx"
    assert [row["file_private"] for row in record["functions"]] == [False]
    assert record["diagnostics"] == []
