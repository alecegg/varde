"""Assemble repository orientation and render its session-start text form."""

from __future__ import annotations

import contextlib
import json
import os
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

from varde_core.memory_dirs import resolve_project_dir

from varde_code.model import Community, RoleTag
from varde_code.parse import language_for_path

from .entrypoints import (
    Entrypoint,
    detect_node_entrypoints,
    detect_process_mains,
    detect_routes,
    detect_sveltekit_pages,
    detect_sveltekit_server_routes,
    detect_tagged_entrypoints,
)
from .flows import build_flows
from .foundational_files import leaderboard as foundational_leaderboard
from .mapping import hotspots_on
from .modes import register_mode
from .module_layers import compute_module_layers
from .params import QueryError
from .simple import _db
from .subsystems import name_clusters
from .symbols_section import leaderboard as symbol_leaderboard

_SECTIONS = (
    "entrypoints",
    "foundational_files",
    "module_layers",
    "subsystems",
    "symbols",
    "flows",
    "hotspots",
)
_BUDGET_SECTIONS = (
    ("entrypoints", "raise maxTokensEstimate to list more entrypoints"),
    (
        "foundational_files",
        "code_query dependents on a specific file, or raise maxTokensEstimate",
    ),
    ("subsystems", "raise maxTokensEstimate to list more subsystems"),
    (
        "flows",
        (
            "code_query mode=explore on an entrypoint symbol (direction=outgoing) "
            "for its full call tree, or raise maxTokensEstimate to list more flows"
        ),
    ),
    ("symbols", "code_query mode=filter_symbols for the full symbol list"),
    ("hotspots", "code_query mode=hotspots for the full ranked list"),
)
_MODULE_LAYERS_MORE = (
    "raise maxTokensEstimate; module_layers holds the resolved module-dependency graph"
)
_MODULE_LAYERS_EDGE_CAP = 50
_MODULE_LAYERS_CYCLE_CAP = 20
_SECTION_RESERVE_TOKENS = 200
_SUBSYSTEM_MEMBER_CAP = 8


def _entrypoints(conn: sqlite3.Connection, repo_root: str | None) -> list[Entrypoint]:
    entries = [
        *detect_tagged_entrypoints(conn),
        *detect_routes(conn),
        *detect_process_mains(conn),
        *detect_node_entrypoints(conn, repo_root),
        *detect_sveltekit_server_routes(conn),
    ]
    groups: list[tuple[str, list[Entrypoint]]] = []
    for entry in entries:
        language = language_for_path(Path(entry.file)) or Path(entry.file).suffix
        group = next((items for key, items in groups if key == language), None)
        if group is None:
            group = []
            groups.append((language, group))
        group.append(entry)
    ordered = []
    while True:
        emitted = False
        for _, group in groups:
            if group:
                ordered.append(group.pop(0))
                emitted = True
        if not emitted:
            break
    return ordered


def _role_tags(conn: sqlite3.Connection) -> dict[str, RoleTag]:
    result: dict[str, RoleTag] = {}
    try:
        for path, tag in conn.execute(
            "SELECT f.path,e.role_tag FROM entities e JOIN files f "
            "ON f.id=e.file_id WHERE e.role_tag IS NOT NULL"
        ):
            with contextlib.suppress(ValueError):
                result[path] = RoleTag(tag)
    except sqlite3.Error:
        pass
    return result


def in_folder(path: str, folder: str | None) -> bool:
    """Whether ``path`` is ``folder`` or inside it; every path matches ``None``."""
    return folder is None or path == folder or path.startswith(folder + "/")


def _capped_in_folder(
    rank: Callable[[int | None], list[dict[str, Any]]], folder: str | None, limit: int
) -> list[dict[str, Any]]:
    """Top ``limit`` of a leaderboard; with ``folder``, rank the folder's rows only."""
    if folder is None:
        return rank(limit)
    rows = rank(None)
    return [row for row in rows if in_folder(row["file"], folder)][:limit]


def _scoped_layers(layers: dict[str, Any], folder: str | None) -> dict[str, Any]:
    if folder is None:
        return layers

    def touches(name: str) -> bool:
        return in_folder(name, folder) or in_folder(folder, name)

    return {
        "edges": [
            edge
            for edge in layers["edges"]
            if touches(edge["from_module"]) or touches(edge["to_module"])
        ],
        "cycles": [cycle for cycle in layers["cycles"] if any(map(touches, cycle))],
    }


def _nav_data(
    conn: sqlite3.Connection,
    repo_root: str | None,
    max_tokens: int,
    folder: str | None = None,
) -> dict[str, Any]:
    entries = _entrypoints(conn, repo_root)
    scoped_entries = [entry for entry in entries if in_folder(entry.file, folder)]
    entrypoint_json = [entry.to_json() for entry in scoped_entries]
    entrypoint_json.extend(
        page
        for page in detect_sveltekit_pages(conn)
        if in_folder(str(page.get("file", "")), folder)
    )
    found = _capped_in_folder(lambda n: foundational_leaderboard(conn, n), folder, 50)
    file_edges = _resolved_file_edges(conn)
    layers = compute_module_layers(file_edges)
    layer_json = _scoped_layers(_module_layers_section(layers), folder)
    subsystems = _subsystems(conn, folder)
    entrypoint_ids = {entry.entity_id for entry in entries}
    symbols = _capped_in_folder(
        lambda n: symbol_leaderboard(conn, entrypoint_ids, n), folder, 100
    )
    roots = [entry for entry in scoped_entries if entry.flow_root]
    flows: list[dict[str, Any]] = []
    for raw_flow in build_flows(conn, roots):
        flow = raw_flow.to_json()
        flow_root = flow.get("root")
        if isinstance(flow_root, dict) and flow_root.get("children"):
            flows.append(flow)
    flows.sort(key=lambda item: -_flow_count(item))
    seen: set[tuple[str, str]] = set()
    deduped = []
    for flow in flows:
        root = flow["root"]
        if not isinstance(root, dict):
            continue
        key = (root["file"], root["symbol"])
        if key not in seen:
            seen.add(key)
            deduped.append(_summarize_flow(flow))
    data: dict[str, Any] = {
        "entrypoints": entrypoint_json,
        "foundational_files": found,
        "module_layers": layer_json,
        "subsystems": subsystems,
        "symbols": symbols,
        "flows": deduped,
        "hotspots": _capped_in_folder(lambda n: hotspots_on(conn, n), folder, 50),
    }
    data["guide"] = _budget_nav_map(data, max_tokens)
    return data


def _module_layers_section(layers: Any) -> dict[str, Any]:
    return {
        "edges": [
            {
                "from_module": edge.from_module,
                "to_module": edge.to_module,
                "crossing_files": edge.crossing_files,
            }
            for edge in layers.edges
        ],
        "cycles": [list(cycle) for cycle in layers.cycles],
    }


def _flow_count(flow: dict[str, Any]) -> int:
    root = flow.get("root")
    return _count_nodes(root) if isinstance(root, dict) else 0


def _resolved_file_edges(conn: sqlite3.Connection) -> list[tuple[str, str]]:
    return [
        (source, target)
        for source, target in conn.execute(
            """SELECT fa.path,fb.path FROM resolved_edges re
        JOIN files fa ON fa.id=re.from_file_id JOIN files fb ON fb.id=re.to_file_id
        WHERE re.resolved=1 AND re.to_file_id IS NOT NULL"""
        )
    ]


def _budget_nav_map(data: dict[str, Any], max_tokens: int) -> dict[str, Any]:
    module_layers = data["module_layers"]
    edge_total = len(module_layers["edges"])
    cycle_total = len(module_layers["cycles"])
    module_layers["edges"] = module_layers["edges"][:_MODULE_LAYERS_EDGE_CAP]
    module_layers["cycles"] = module_layers["cycles"][:_MODULE_LAYERS_CYCLE_CAP]
    section_totals = {name: len(data[name]) for name, _ in _BUDGET_SECTIONS}
    truncated: dict[str, dict[str, Any]] = {}
    fixed_cost = _estimate_tokens({"edges": [], "cycles": []})
    remaining = max(0, max_tokens - fixed_cost)
    populated = sum(bool(data[name]) for name, _ in _BUDGET_SECTIONS)
    has_edges = bool(module_layers["edges"])
    reserve = min(
        _SECTION_RESERVE_TOKENS,
        remaining // (populated + int(has_edges)) if populated + int(has_edges) else 0,
    )
    kept = {name: 0 for name, _ in _BUDGET_SECTIONS}
    for name, _ in _BUDGET_SECTIONS:
        items = data[name]
        if items and _item_cost(items[0]) <= reserve:
            kept[name] = 1
            remaining -= _item_cost(items[0])
    edges = module_layers["edges"]
    kept_edges = 0
    if edges and _item_cost(edges[0]) <= reserve:
        kept_edges = 1
        remaining -= _item_cost(edges[0])

    for name, more in _BUDGET_SECTIONS:
        items = data[name]
        while kept[name] < len(items):
            cost = _item_cost(items[kept[name]])
            if cost > remaining:
                break
            remaining -= cost
            kept[name] += 1
        if kept[name] < len(items):
            data[name] = items[: kept[name]]
            truncated[name] = {
                "shown": kept[name],
                "total": section_totals[name],
                "more": more,
            }

    while kept_edges < len(edges) and kept_edges < _MODULE_LAYERS_EDGE_CAP:
        cost = _item_cost(edges[kept_edges])
        if cost > remaining:
            break
        remaining -= cost
        kept_edges += 1
    module_layers["edges"] = edges[:kept_edges]
    if kept_edges < edge_total:
        truncated["module_layers.edges"] = {
            "shown": kept_edges,
            "total": edge_total,
            "more": _MODULE_LAYERS_MORE,
        }

    cycles = module_layers["cycles"]
    kept_cycles = 0
    while kept_cycles < len(cycles):
        cost = _item_cost(cycles[kept_cycles])
        if cost > remaining:
            break
        remaining -= cost
        kept_cycles += 1
    module_layers["cycles"] = cycles[:kept_cycles]
    if kept_cycles < cycle_total:
        truncated["module_layers.cycles"] = {
            "shown": kept_cycles,
            "total": cycle_total,
            "more": _MODULE_LAYERS_MORE,
        }

    guide = {"budgetTokens": max_tokens, "truncated": truncated}
    while _estimate_tokens({**data, "guide": guide}) > max_tokens:
        if module_layers["cycles"]:
            module_layers["cycles"].pop()
            truncated["module_layers.cycles"] = {
                "shown": len(module_layers["cycles"]),
                "total": cycle_total,
                "more": _MODULE_LAYERS_MORE,
            }
        else:
            name = next(
                (name for name, _ in reversed(_BUDGET_SECTIONS) if data[name]), None
            )
            if name is not None:
                data[name].pop()
                more = dict(_BUDGET_SECTIONS)[name]
                truncated[name] = {
                    "shown": len(data[name]),
                    "total": section_totals[name],
                    "more": more,
                }
            elif module_layers["edges"]:
                module_layers["edges"].pop()
                truncated["module_layers.edges"] = {
                    "shown": len(module_layers["edges"]),
                    "total": edge_total,
                    "more": _MODULE_LAYERS_MORE,
                }
            else:
                minimum = _estimate_tokens({**data, "guide": guide})
                while True:
                    guide = {
                        "budgetTokens": max_tokens,
                        "truncated": truncated,
                        "minimumBudgetTokens": minimum,
                    }
                    actual = _estimate_tokens({**data, "guide": guide})
                    if actual == minimum:
                        return guide
                    minimum = actual
        guide = {"budgetTokens": max_tokens, "truncated": truncated}
    return guide


def _item_cost(item: Any) -> int:
    return max(1, _estimate_tokens(item))


def _estimate_tokens(value: Any) -> int:
    return (
        len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()) // 4
    )


def _subsystems(
    conn: sqlite3.Connection, folder: str | None = None
) -> list[dict[str, Any]]:
    communities: dict[int, list[str]] = {}
    for cid, path in conn.execute(
        """SELECT cm.community_id,f.path FROM community_members cm
        JOIN files f ON f.id=cm.file_id WHERE f.is_test_path=0 ORDER BY f.path"""
    ):
        communities.setdefault(cid, []).append(path)
    named = name_clusters(
        [Community(cid, paths) for cid, paths in communities.items()], _role_tags(conn)
    )
    scoped = [
        (item, [name for name in item.members if in_folder(name, folder)])
        for item in named
    ]
    scoped = [(item, members) for item, members in scoped if members]
    scoped.sort(key=lambda pair: (-len(pair[1]), pair[0].name, pair[0].id))
    return [
        {
            "id": item.id,
            "name": item.name,
            "members": members[:_SUBSYSTEM_MEMBER_CAP],
            **(
                {"membersOmitted": len(members) - _SUBSYSTEM_MEMBER_CAP}
                if len(members) > _SUBSYSTEM_MEMBER_CAP
                else {}
            ),
        }
        for item, members in scoped
    ]


def _count_nodes(node: dict[str, Any]) -> int:
    return 1 + sum(_count_nodes(child) for child in node.get("children", []))


def _summarize_flow(flow: dict[str, Any]) -> dict[str, Any]:
    def trim(node: dict[str, Any], depth: int, budget: list[int]) -> dict[str, Any]:
        budget[0] -= 1
        result = {
            "entity_id": node["entity_id"],
            "file": node["file"],
            "symbol": node["symbol"],
        }
        if "backref_to" in node:
            result["backref_to"] = node["backref_to"]
        elif depth < 4 and budget[0] > 0:
            children = node.get("children", [])
            result["children"] = [
                trim(child, depth + 1, budget)
                for child in children[: max(0, budget[0])]
            ]
            if len(children) > len(result["children"]):
                result["childrenOmitted"] = len(children) - len(result["children"])
        return result

    return {
        "entrypoint": flow["entrypoint"],
        "root": trim(flow["root"], 0, [30]),
        "nodeCount": _count_nodes(flow["root"]),
    }


def _indexed_folder(repo_root: str | None, folder: object) -> str | None:
    """Return ``folder`` (relative to the repo root) as the index stores paths."""
    if not isinstance(folder, str):
        return None
    if repo_root is None:
        return folder
    return (Path(repo_root).resolve() / folder).as_posix()


def nav_map(input: dict[str, Any]) -> dict[str, Any]:
    conn = _db(input)
    try:
        maximum = input.get("maxTokensEstimate", 12000)
        if isinstance(maximum, bool) or not isinstance(maximum, int) or maximum < 0:
            maximum = 12000
        repo_root = (
            input.get("repoRoot") if isinstance(input.get("repoRoot"), str) else None
        )
        return _nav_data(
            conn, repo_root, maximum, _indexed_folder(repo_root, input.get("folder"))
        )
    finally:
        conn.close()


def format_map(data: dict[str, Any]) -> str:
    out = []
    truncated = data.get("guide", {}).get("truncated", {})
    for section in _SECTIONS:
        out.append(f"## {section}\n")
        items = data.get(section)
        if isinstance(items, list):
            if not items:
                info = truncated.get(section)
                out.append(
                    (
                        f"(truncated: 0/{info.get('total', 0)} shown; "
                        f"{info.get('more', '')})\n\n"
                    )
                    if info
                    else "(none)\n\n"
                )
                continue
            out.extend(_render_item(section, item) for item in items)
            out.append("\n")
        elif section == "module_layers" and isinstance(items, dict):
            edges = items.get("edges", [])
            cycles = items.get("cycles", [])
            out.extend(
                [
                    (
                        f"- {edge.get('from_module', '')} → "
                        f"{edge.get('to_module', '')} "
                        f"({edge.get('crossing_files', 0)} files)\n"
                    )
                    for edge in edges
                ]
            )
            out.extend([f"- cycle: {' → '.join(cycle)}\n" for cycle in cycles])
            out.append("(none)\n\n" if not edges and not cycles else "\n")
        else:
            out.append("(missing)\n\n")
    if truncated:
        out.append("## truncated (token budget)\n")
        out.extend(
            (
                f"- {key}: {value.get('shown', 0)}/{value.get('total', 0)} shown — "
                f"{value.get('more', '')}\n"
            )
            for key, value in truncated.items()
        )
        out.append("\n")
    return "".join(out)


def _render_item(section: str, item: Any) -> str:
    if not isinstance(item, dict):
        return f"- {json.dumps(item, ensure_ascii=False)}\n"
    if section == "entrypoints":
        route = (
            f" ({item.get('method', '')} {item.get('path', '')})"
            if item.get("path") and item.get("path") != item.get("symbol")
            else ""
        )
        return (
            f"- {item.get('symbol', '')}{route}  {item.get('file', '')} "
            f"[{item.get('role', '')}]\n"
        )
    if section == "foundational_files":
        return (
            f"- {item.get('file', '')}  ({item.get('dependents', 0)} dependents, "
            f"{item.get('count', 0)} refs)\n"
        )
    if section == "subsystems":
        return f"- {item.get('name', '')} ({', '.join(item.get('members', []))})\n"
    if section == "symbols":
        return (
            f"- {item.get('file', '')}::{item.get('symbol', '')}  "
            f"({item.get('callers', 0)} callers)\n"
        )
    if section == "hotspots":
        return (
            f"- {item.get('file', '')}  (score {item.get('score', 0)}, "
            f"complexity {item.get('complexity', 0)}, churn {item.get('churn', 0)})\n"
        )
    if section == "flows":
        return f"- {item.get('entrypoint', '')} ({item.get('nodeCount', 0)} nodes)\n"
    return f"- {json.dumps(item, ensure_ascii=False)}\n"


def nav_map_text(input: object, with_knowledge: bool) -> str:
    """Return the plain-text nav map, optionally prefixed with the project knowledge
    pointer.

    `input` may be a raw mode input, an already-rendered envelope, or its JSON text.
    """
    value: object = input
    if isinstance(input, str):
        try:
            value = json.loads(input)
        except ValueError, TypeError:
            return input
    if isinstance(value, dict) and "ok" in value:
        if value.get("ok") is not True:
            return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        data = value.get("data")
    elif isinstance(value, dict) and "entrypoints" in value:
        data = value
    elif isinstance(value, dict):
        try:
            data = nav_map(value)
        except QueryError as exc:
            return json.dumps(
                {
                    "ok": False,
                    "data": {"error": {"code": exc.code, "message": exc.message}},
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
    else:
        return json.dumps(
            {
                "ok": False,
                "data": {
                    "error": {
                        "code": "invalid_input",
                        "message": "input must be an object",
                    }
                },
            },
            separators=(",", ":"),
        )
    if not isinstance(data, dict):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    rendered = (
        _orientation_text(data)
        if os.environ.get("VARDE_CODE_TOZ") == "0"
        else format_map(data)
    )
    root = value.get("repoRoot") if isinstance(value, dict) else None
    if with_knowledge and isinstance(root, str):
        directory = Path(root).resolve()
        if directory.is_dir():
            knowledge = resolve_project_dir(directory, "knowledge")
            if knowledge.is_dir():
                rendered = (
                    f"Project knowledge: {knowledge}/ (use varde learn knowledge "
                    f"search --bundle {knowledge} --text <term>).\n\n"
                ) + rendered
    return rendered


def _orientation_text(data: dict[str, Any]) -> str:
    sections = (
        ("entrypoints", "entrypoints"),
        ("subsystems", "subsystems"),
        ("flows", "flows"),
        ("hotspots", "hotspots"),
    )
    counts = ", ".join(f"{len(data.get(key, []))} {label}" for key, label in sections)
    out = ["## Repository outline\n", f"Items present in this capped map: {counts}.\n"]
    omitted = []
    truncated = data.get("guide", {}).get("truncated", {})
    if isinstance(truncated, dict):
        for key, label in sections:
            total = truncated.get(key, {}).get("total")
            if isinstance(total, int) and total > len(data.get(key, [])):
                omitted.append(f"{total - len(data.get(key, []))} {label}")
    if omitted:
        out.append(
            f"Additional items omitted by the token budget: {', '.join(omitted)}.\n"
        )
    subsystems = data.get("subsystems", [])
    names = [item.get("name", "") for item in subsystems[:5] if item.get("name")]
    if names:
        out.append(f"Subsystems: {', '.join(names)}\n")
    for heading, key, limit in (
        ("Key entrypoints", "entrypoints", 5),
        ("Main flows (root and direct calls)", "flows", 4),
    ):
        items = data.get(key, [])
        if not items:
            continue
        out.append(f"## {heading}\n")
        for item in items[:limit]:
            if key == "entrypoints":
                route = (
                    f" ({item.get('method')} {item.get('path')})"
                    if item.get("path") and item.get("path") != item.get("symbol")
                    else ""
                )
                out.append(
                    (  # noqa: UP034 - Groups adjacent literals inside this call.
                        f"- {item.get('symbol', '')}{route}  {item.get('file', '')} "
                        f"[{item.get('role', '')}]\n"
                    )
                )
            else:
                out.append(
                    (  # noqa: UP034 - Groups adjacent literals inside this call.
                        f"- {item.get('entrypoint', '')} "
                        f"({item.get('nodeCount', 0)} nodes)\n"
                    )
                )
        if len(items) > limit:
            out.append(f"- … {len(items) - limit} more; query for details\n")
    out.append("## Investigate further\n")
    out.append(
        (  # noqa: UP034 - Groups adjacent literals inside this call.
            "- Find a declaration by name: `varde map get_symbol --json "
            '\'{"repoRoot":"<repo-root>","name":"<name>"}\'`\n'
            "- Find call sites (no index needed): `varde map find_pattern --json "
            '\'{"repoRoot":"<repo-root>","language":"<lang>",'
            '"pattern":"<name>($$$ARGS)"}\'`; methods use '
            "`$RECV.<name>($$$ARGS)`; qualified calls need the full path\n"
            "- Expanded map (section caps still apply): `varde map nav_map --json "
            '\'{"repoRoot":"<repo-root>","maxTokensEstimate":'
            "18446744073709551615}'`\n"
            "- Find relevant files and symbols: `varde map context_pack --json "
            '\'{"repoRoot":"<repo-root>","query":"<term>"}\'`\n'
            "- Explore file dependencies from a file or symbol: "
            "`varde map explore --json "
            '\'{"repoRoot":"<repo-root>","query":{"params":'
            '{"input":"<file-or-symbol>","direction":"outgoing"}}}\'`\n'
            "- Inspect risk hotspots: `varde map hotspots --json "
            '\'{"repoRoot":"<repo-root>"}\'`\n'
        )
    )
    return "".join(out)


register_mode("nav_map", nav_map)

__all__ = ["nav_map", "nav_map_text"]
