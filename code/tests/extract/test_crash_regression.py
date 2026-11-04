import subprocess
import sys
from pathlib import Path

import pytest


def _source(language: str) -> str:
    statements = {
        "bash": "x_{i}=0\n",
        "c": "int x_{i} = 0;\n",
        "cpp": "int x_{i} = 0;\n",
        "go": "var x_{i} = 0\n",
        "java": "int x_{i} = 0;\n",
        "javascript": "const x_{i} = 0;\n",
        "python": "x_{i} = 0\n",
        "rust": "let x_{i} = 0;\n",
        "typescript": "const x_{i}: number = 0;\n",
        "tsx": "const x_{i}: number = 0;\n",
    }
    body = "".join(statements[language].format(i=index) for index in range(40))
    wrappers = {
        "c": ("int main(void) {\n", "return 0;\n}\n"),
        "cpp": ("int main() {\n", "return 0;\n}\n"),
        "go": ("package main\nfunc main() {\n", "}\n"),
        "java": ("class Main { void main() {\n", "}\n}\n"),
        "javascript": ("function main() {\n", "}\n"),
        "python": ("def main():\n", ""),
        "rust": ("fn main() {\n", "}\n"),
        "typescript": ("function main() {\n", "}\n"),
        "tsx": ("function Main() {\n", "}\n"),
    }
    prefix, suffix = wrappers.get(language, ("", ""))
    if prefix:
        body = "".join("    " + line for line in body.splitlines(keepends=True))
    return prefix + body + suffix


@pytest.mark.parametrize(
    "language",
    (
        "bash",
        "c",
        "cpp",
        "go",
        "java",
        "javascript",
        "python",
        "rust",
        "typescript",
        "tsx",
    ),
)
def test_extract_file_large_source_does_not_crash(language: str):
    code = (
        "import sys\n"
        "from varde_code.extract import extract_file\n"
        "extract_file('large.' + sys.argv[1], sys.stdin.read(), sys.argv[1])\n"
    )
    result = subprocess.run(  # noqa: S603 - Runs the crash-regression fixture in a child process.
        [sys.executable, "-X", "faulthandler", "-c", code, language],
        input=_source(language),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    assert result.returncode == 0, (
        f"extract_file crashed for {language}:\n{result.stdout}\n{result.stderr}"
    )


def test_extract_all_python_package_sources_in_one_process():
    root = Path(__file__).resolve().parents[4]
    code = (
        "import sys\n"
        "from pathlib import Path\n"
        "from varde_code.extract import extract_file\n"
        "root = Path(sys.argv[1])\n"
        "files = sorted(root.glob('core/src/**/*.py'))[:3]\n"
        "for path in files:\n"
        "    extract_file(str(path), path.read_text(encoding='utf-8'), 'python')\n"
        "print(f'extracted {len(files)} files')\n"
    )
    result = subprocess.run(  # noqa: S603 - Runs the crash-regression fixture in a child process.
        [sys.executable, "-X", "faulthandler", "-c", code, str(root)],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )

    assert result.returncode == 0, (
        "extracting representative Python package sources crashed:\n"
        f"{result.stdout}\n{result.stderr}"
    )
    assert result.stdout.startswith("extracted ")
