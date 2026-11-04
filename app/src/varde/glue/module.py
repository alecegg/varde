"""Register the app-level search and edit commands."""

from dataclasses import dataclass

from varde_core.io import Io


@dataclass(frozen=True)
class GlueModule:
    name: str = "app"

    def run(self, argv: list[str], io: Io) -> int:
        command = argv[0].rsplit(" ", 1)[-1]
        if command == "edit":
            from .edit import run

            return run(argv[1:], io)
        if command == "search":
            return _search(argv[1:])
        return 2

    def help(self, path: str) -> str:
        from .help_snapshots import EDIT_HELP, SEARCH_HELP

        if path == "search":
            return SEARCH_HELP
        if path == "edit":
            return EDIT_HELP
        return f"Usage: varde {path} [OPTIONS]\n"


def register() -> GlueModule:
    return GlueModule()


def _search(args: list[str]) -> int:
    import json
    import sys

    from .search.core import (
        SOURCE_ORDER,
        parse_search_args,
        render_json,
        render_text,
        search_all,
    )

    query, selected, as_json = parse_search_args(args)
    try:
        from varde_code.index.paths import repo_db_path
        from varde_learn.knowledge.memory import MemoryPaths
        from varde_toz.config import config_dir
        from varde_toz.project import project_root, store_db_path

        from .search.code import CodeSearch
        from .search.friction import FrictionSearch
        from .search.knowledge import KnowledgeSearch
        from .search.toz import TozScope, TozSearch

        root = project_root()
        paths = MemoryPaths.resolve(root)
        toz_db = store_db_path(root, config_dir())
        available = {
            "code": CodeSearch(root, repo_db_path(root)),
            "docs": TozSearch(TozScope.DOCS, toz_db, root, paths.working.path),
            "plans": TozSearch(TozScope.PLANS, toz_db, root, paths.working.path),
            "output": TozSearch(TozScope.OUTPUT, toz_db, root, paths.working.path),
            "knowledge": KnowledgeSearch(paths.knowledge.path),
            "friction": FrictionSearch(paths.learn.path),
        }
        results = search_all([available[name] for name in selected], query)
    except Exception as error:
        from .search.types import SourceResult

        results = [
            SourceResult.unavailable(name, str(error))
            for name in (selected or SOURCE_ORDER)
        ]
    if as_json:
        print(
            json.dumps(
                render_json(results, query),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
    else:
        sys.stdout.write(render_text(results))
    return 0
