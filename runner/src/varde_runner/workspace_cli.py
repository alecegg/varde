"""CLI for native runner workspaces."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, NoReturn


def _request(
    method: str,
    port: int,
    *,
    payload: dict[str, Any] | None = None,
    query: dict[str, str] | None = None,
) -> tuple[int, dict[str, Any]]:
    url = f"http://127.0.0.1:{port}/api/workspaces"
    if query:
        url += "?" + urllib.parse.urlencode(query)
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(  # noqa: S310 - URL is fixed to loopback above.
        url, data=data, method=method
    )
    if data is not None:
        request.add_header("content-type", "application/json")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=30) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as exc:
        try:
            body = json.load(exc)
        except ValueError, OSError:
            body = {"error": str(exc)}
        return exc.code, body
    except urllib.error.URLError as exc:
        raise SystemExit(f"runner request failed: {exc.reason}") from exc


def _exit_for(code: str) -> int:
    return {
        "exists": 3,
        "base_unresolved": 2,
        "bad_id": 1,
        "bad_caller": 1,
        "repo_not_configured": 4,
        "not_found": 4,
        "ambiguous": 4,
        "dirty": 4,
        "unmerged": 4,
        "live_session": 4,
        "caller_inside": 4,
        "preflight": 4,
        "verify_failed": 5,
        "git_failed": 5,
        "command_timeout": 5,
        "refused": 4,
    }.get(code, 1)


def _fail(status: int, body: dict[str, Any]) -> None:
    error = str(body.get("error", f"HTTP {status}"))
    print(error, file=sys.stderr)
    raise SystemExit(_exit_for(str(body.get("code", "unknown"))))


class _WorkspaceArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        self.print_usage(sys.stderr)
        self.exit(1, f"{self.prog}: error: {message}\n")


def main(argv: list[str]) -> None:
    parser = _WorkspaceArgumentParser(prog="varde-runner workspace")
    parser.add_argument("action", choices=("create", "list", "remove"))
    parser.add_argument("id", nargs="?")
    parser.add_argument("--repo")
    parser.add_argument("--base")
    parser.add_argument("--discard", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    if args.action == "create":
        if not args.id or not args.repo:
            parser.error("create requires --repo and id")
        status, body = _request(
            "POST",
            args.port,
            payload={
                "repo": os.path.abspath(args.repo),
                "id": args.id,
                "base": args.base,
                "caller": os.getcwd(),
            },
        )
        if status != 201:
            _fail(status, body)
        print(f"path={body['path']}\nbranch={body['branch']}\ncreated=true")
        return
    if args.action == "list":
        if args.id or args.repo or args.base or args.discard:
            parser.error("list accepts only --json and --port")
        status, body = _request("GET", args.port)
        if status != 200:
            _fail(status, body)
        if args.json:
            print(json.dumps(body["workspaces"], sort_keys=True))
        else:
            for workspace in body["workspaces"]:
                print(
                    f"{workspace['kind']}\t{workspace.get('branch', '')}"
                    f"\t{workspace['cwd']}"
                )
        return
    if not args.id or args.base:
        parser.error("remove requires id and does not accept --base")
    repo = args.repo
    if repo is None:
        status, body = _request("GET", args.port)
        if status != 200:
            _fail(status, body)
        matches = [
            workspace
            for workspace in body["workspaces"]
            if workspace.get("kind") == "worktree"
            and workspace.get("branch") == f"worktree/{args.id}"
        ]
        repos = sorted({w["repo"] for w in matches})
        if len(repos) != 1:
            print(
                "worktree id must match exactly one configured repo; matches: "
                + (", ".join(repos) if repos else "none"),
                file=sys.stderr,
            )
            raise SystemExit(1)
        repo = repos[0]
    query = {
        "repo": os.path.abspath(repo),
        "id": args.id,
        "caller": os.getcwd(),
        "discard": str(args.discard).lower(),
    }
    status, body = _request("DELETE", args.port, query=query)
    if status != 200:
        _fail(status, body)
    print(f"removed=true\nbranch={body['branch']}")
    for path in body.get("ignored_removed", []):
        print(f"ignored={path}")
