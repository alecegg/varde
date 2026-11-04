"""pytest and unittest naming conventions for Python facts roles."""

from varde_code.quality_pass.facts import extract_facts


def test_test_items_without_decorators_get_the_test_role():
    record = extract_facts(
        "import unittest\n"
        "def test_plain():\n"
        "    assert run()\n"
        "def testify():\n"
        "    return 1\n"
        "class TestThing:\n"
        "    def test_method(self):\n"
        "        return 1\n"
        "    def helper(self):\n"
        "        return 2\n"
        "class TestWithInit:\n"
        "    def __init__(self):\n"
        "        self.value = 1\n"
        "    def test_method(self):\n"
        "        return 3\n"
        "class StorageTests(unittest.TestCase):\n"
        "    def test_storage(self):\n"
        "        return 4\n"
        "class Prod:\n"
        "    def test_connection(self):\n"
        "        return 5\n",
        "python",
        "tests/test_sample.py",
    )

    assert {
        (row["owner"], row["name"]): row["exempt_role"] for row in record["functions"]
    } == {
        (None, "test_plain"): "test",
        (None, "testify"): None,
        ("TestThing", "test_method"): "test",
        ("TestThing", "helper"): None,
        ("TestWithInit", "__init__"): "constructor",
        ("TestWithInit", "test_method"): None,
        ("StorageTests", "test_storage"): "test",
        ("Prod", "test_connection"): None,
    }
