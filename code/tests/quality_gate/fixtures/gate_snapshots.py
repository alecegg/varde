"""Pinned per-language snapshots for the scan-gate attack suite.

Each snapshot is a small repository as ``{relative path: source}`` with the same
roles in every language: a debt-heavy file, a clean file, a mid file, an
overhead-exempt shape, a direct cross-file call edge, a syntax-error variant,
and generators for filler files. Sources are embedded strings so linters and
type-checkers never see the intentionally bad code.
"""

from __future__ import annotations

from dataclasses import dataclass

from gate_sources_cs import SPEC as CSHARP
from gate_sources_py import SPEC as PYTHON
from gate_sources_ts import SPEC as TYPESCRIPT


@dataclass(frozen=True)
class Snapshot:
    language: str
    module_dir: str
    files: dict[str, str]
    roles: dict[str, str]
    syntax_error: str
    edge_caller: str
    edge_callee: str
    edge_verdict: str
    marker_comment: str
    generated_header: str | None
    long_comment: str
    suppress_file: str
    suppress_next_line: str
    test_paths: tuple[str, ...]
    ext: str
    filler_clean: str
    filler_tiny: str

    def path(self, role: str) -> str:
        return self.roles[role]

    def with_generated_marker(self, source: str) -> str:
        return (self.generated_header or self.marker_comment) + source

    def with_long_comment(self, source: str) -> str:
        return self.long_comment + source

    def with_file_suppression(self, source: str) -> str:
        return self.suppress_file + source

    def filler_files(self, count: int, *, tiny: bool = True) -> dict[str, str]:
        template = self.filler_tiny if tiny else self.filler_clean
        return {
            f"{self.module_dir}/filler_{index:03d}.{self.ext}": template.replace("{n}", str(index))
            for index in range(count)
        }


SNAPSHOTS: dict[str, Snapshot] = {
    "python": Snapshot(**PYTHON),
    "typescript": Snapshot(**TYPESCRIPT),
    "csharp": Snapshot(**CSHARP),
}
LANGUAGES = tuple(SNAPSHOTS)
