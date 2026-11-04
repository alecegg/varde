# Python dependency versions

Checked 2026-10-14. The versions below are the CPython 3.14 `uv pip compile` results for the workspace's external runtime and root development dependencies. All three target resolutions selected the same versions.

| Dependency | Resolved version |
| --- | --- |
| altgraph | 0.17.5 |
| ast-grep-py | 0.50.0 |
| beautifulsoup4 | 4.12.3 |
| blake3 | 1.0.11 |
| iniconfig | 2.3.1 |
| macholib | 1.16.4 |
| markdownify | 1.2.3 |
| packaging | 26.3 |
| pex | 2.103.4 |
| pluggy | 1.6.0 |
| pygments | 2.21.0 |
| pyinstaller | 6.22.3 |
| pyinstaller-hooks-contrib | 2026.8 |
| pytest | 8.4.2 |
| ruff | 0.17.0 |
| setuptools | 84.0.0 |
| six | 1.17.0 |
| soupsieve | 3.0.3 |
| tree-sitter | 0.26.0 |
| tree-sitter-language-pack | 1.22.1 |
| wasmtime | 49.0.0 |
| watchdog | 6.0.0 |

`tree-sitter-language-pack==1.22.1` declares `tree-sitter==0.26.0`; the workspace also pins `tree-sitter==0.26.0` directly. The Python pin `ast-grep-py==0.50.0` is a separate release line.

PyPI checked 2026-10-14: `tree-sitter` latest is 0.26.0 and `ast-grep-py` latest is 0.50.0, so neither has a newer release than the workspace pin.
