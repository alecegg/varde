from varde_code.extract.entity import extract_file
from varde_code.model import EntityKind


def test_python_literals_inside_type_annotations_are_not_entities():
    output = extract_file(
        "typed_literals.py",
        "from typing import Literal\n"
        "value: list[str] | None = None\n"
        "choice: Literal['a'] = 'a'\n"
        "def returns_none() -> None:\n"
        "    pass\n",
        "python",
    )

    literals = [
        entity.name for entity in output.entities if entity.kind == EntityKind.LITERAL
    ]

    assert literals == ["None", "'a'", "None"]
