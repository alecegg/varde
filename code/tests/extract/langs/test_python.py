from varde_code.extract import extract_file, tables_for
from varde_code.model import EntityKind


def test_python_tables_and_entities():
    tables = tables_for("python")
    assert tables.function_scopes == frozenset({"function_definition"})
    assert tables.type_scopes == frozenset({"class_definition"})
    output = extract_file(
        "sample.py",
        "import package.module\nfrom .helpers import run\n"
        "class Worker(Base):\n    def work(self, value=2):\n"
        "        result = run(value)\n        if value and result:\n"
        "            return self.finish('ok')\n        try:\n"
        "            raise ValueError('bad')\n        except ValueError as error:\n"
        "            pass\n",
        "python",
    )
    pairs = {(entity.kind, entity.name) for entity in output.entities}
    assert (EntityKind.IMPORT, "package/module") in pairs
    assert (EntityKind.IMPORT, "./helpers") in pairs
    assert (EntityKind.CLASS, "Worker") in pairs
    assert (EntityKind.FUNCTION, "work") in pairs
    assert (EntityKind.PARAMETER, "value") in pairs
    assert (EntityKind.VARIABLE, "result") in pairs
    assert (EntityKind.CALL, "run") in pairs
    assert (EntityKind.LITERAL, "'ok'") in pairs
    assert (EntityKind.CATCH, "error") in pairs
    assert (EntityKind.THROW, "ValueError('bad')") in pairs
    assert (EntityKind.CONTROL_FLOW, "logical_and") in pairs


def test_python_multiline_decorator_entity():
    source = (
        "@pytest.mark.parametrize(\n    'value', [1, 2]\n)\n"
        "def test_value(value):\n    pass\n"
    )
    entities = extract_file("sample.py", source, "python").entities
    assert (EntityKind.DECORATOR, "pytest.mark.parametrize") in {
        (entity.kind, entity.name) for entity in entities
    }
