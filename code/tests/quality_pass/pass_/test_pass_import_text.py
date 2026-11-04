"""Import specs retain source statements for language-specific resolution."""

from __future__ import annotations

import pytest
from varde_code.quality_pass.pass_.extract import import_specs


@pytest.mark.parametrize(
    ("language", "source", "module", "expected"),
    [
        (
            "python",
            "from a import work as w, other\n",
            "a",
            "from a import work as w, other",
        ),
        ("python", "import a\n", "a", "import a"),
        ("python", "from x import *\n", "x", "from x import *"),
        (
            "typescript",
            "import { a as b, c } from './m';\n",
            "./m",
            "import { a as b, c } from './m';",
        ),
        ("typescript", "import d from './n';\n", "./n", "import d from './n';"),
        (
            "typescript",
            "import * as ns from './o';\n",
            "./o",
            "import * as ns from './o';",
        ),
        (
            "typescript",
            "import {\n a as b,\n c\n} from './m'; import q from './q'\n",
            "./m",
            "import {\n a as b,\n c\n} from './m';",
        ),
        (
            "typescript",
            "import {\n a as b,\n c\n} from './m'; import q from './q'\n",
            "./q",
            "import q from './q'",
        ),
        ("python", "import x; import y\n", "x", "import x"),
        ("python", "import x; import y\n", "y", "import y"),
        (
            "java",
            "import static java.util.Collections.emptyList;\n",
            "java/util/Collections/emptyList",
            "import static java.util.Collections.emptyList;",
        ),
        (
            "csharp",
            "using static System.Math;\n",
            "System/Math",
            "using static System.Math;",
        ),
        ("go", 'import (\n "os"\n z "net/http"\n)\n', "os", '"os"'),
        ("go", 'import (\n "os"\n z "net/http"\n)\n', "net/http", 'z "net/http"'),
        ("rust", "mod m;\n", "mod m", "mod m;"),
        ("cpp", '#include <vector>\n#include "a.h"\n', "vector", "#include <vector>"),
        ("cpp", '#include <vector>\n#include "a.h"\n', "a.h", '#include "a.h"'),
    ],
)
def test_import_specs_keep_statement_text(language, source, module, expected, tmp_path):
    path = tmp_path / f"unique_{language}.{'ts' if language == 'typescript' else 'py'}"

    specs = import_specs(str(path), source, language)

    assert specs
    assert all(set(spec) == {"line", "module", "text"} for spec in specs)
    matching = [spec for spec in specs if spec["module"] == module]
    assert matching
    assert {spec["text"] for spec in matching} == {expected}
    expected_line = {"./q": 4, "os": 2, "net/http": 3, "a.h": 2}.get(module, 1)
    assert all(spec["line"] == expected_line for spec in matching)


def test_import_specs_keep_first_text_for_duplicate_module(tmp_path):
    source = "import x; import x\n"
    path = tmp_path / "duplicate.py"

    specs = import_specs(str(path), source, "python")

    assert specs == [{"line": 1, "module": "x", "text": "import x"}]


def test_import_text_is_trimmed_and_capped(tmp_path):
    source = "from a import " + ("x, " * 500) + "last\n"
    path = tmp_path / "unique_long.py"

    specs = import_specs(str(path), source, "python")

    assert len(specs) == 1
    assert specs[0]["text"].startswith("from a import ")
    assert len(specs[0]["text"]) == 1000
