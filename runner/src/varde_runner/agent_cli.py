"""`varde-runner agent`: launch, list and write to managed agents.

The runner authorizes writes only for a client attached to the agent's watch
stream as a writer, so write commands (prompt, interrupt, stop, archive, mode)
hold that stream while they post. Launch and list are plain HTTP calls.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
import uuid
from http.client import IncompleteRead
from typing import Any, NoReturn
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode

from varde_runner.bot_profile import BOT_TOKEN_ENV
from varde_runner.bot_tokens import TOKEN_HEADER
from varde_runner.clients import ClientRole
from varde_runner.web.agent_watch import watch_url

ATTACH_RETRY_SECONDS = 5.0
ATTACH_RETRY_DELAY = 0.2
REQUEST_TIMEOUT = 30
NOT_ATTACHED = "write client is not authorized"


WRITE_ACTIONS = ("prompt", "interrupt", "stop", "archive", "mode")
INSTANCE_CAP_EXIT = 2
HTTP_FORBIDDEN = 403


def write_payload(action: str, client: str, text: str | None) -> dict[str, str]:
    """``text`` is the prompt for ``prompt`` and the new mode for ``mode``."""
    if action == "prompt":
        return {"client": client, "text": text or ""}
    if action == "mode":
        return {"client": client, "mode": text or ""}
    return {"client": client}


def write_url(agent: str, action: str, port: int) -> str:
    return f"http://127.0.0.1:{port}/api/agents/{quote(agent, safe='')}/{action}"


def run(action: str, agent: str, text: str | None, port: int) -> dict[str, Any]:
    client = f"agent-cli-{uuid.uuid4().hex}"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    stream_url = watch_url(
        agent, after=None, client=client, role=ClientRole.WRITER, port=port
    )
    with opener.open(stream_url, timeout=REQUEST_TIMEOUT):
        return _post_when_attached(opener, action, agent, client, text, port)


def _post_when_attached(
    opener: urllib.request.OpenerDirector,
    action: str,
    agent: str,
    client: str,
    text: str | None,
    port: int,
) -> dict[str, Any]:
    request = urllib.request.Request(  # noqa: S310 - loopback http URL built above.
        write_url(agent, action, port),
        data=json.dumps(write_payload(action, client, text)).encode(),
        headers=_request_headers(),
        method="POST",
    )
    deadline = time.monotonic() + ATTACH_RETRY_SECONDS
    while True:
        try:
            with opener.open(request, timeout=REQUEST_TIMEOUT) as response:
                return json.load(response)
        except HTTPError as exc:
            text = _error_text(exc)
            # Only "not authorized" right after the stream opens is the attach race.
            if exc.code == HTTP_FORBIDDEN and action == "mode":
                text += " (mode needs a paired browser; change it in the dashboard)"
            if NOT_ATTACHED not in text or time.monotonic() >= deadline:
                raise SystemExit(f"{action} failed: {text}") from exc
            time.sleep(ATTACH_RETRY_DELAY)


def _error_text(exc: HTTPError) -> str:
    body = exc.read().decode("utf-8", errors="replace")
    return f"HTTP {exc.code} {body}".strip()


def base_url(port: int) -> str:
    return f"http://127.0.0.1:{port}/api/agents"


def launch_payload(args: argparse.Namespace, prompt: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "role": args.role,
        "workspace": args.workspace,
        "prompt": prompt,
    }
    for key in ("harness", "mode"):
        if getattr(args, key):
            payload[key] = getattr(args, key)
    if args.parent:
        payload["parent_id"] = args.parent
    if args.slot:
        payload["address"] = {"slot": args.slot, "plan": args.plan}
    return payload


def _request_headers() -> dict[str, str]:
    """JSON headers plus the taint token when this agent was launched by the bot."""
    headers = {"content-type": "application/json"}
    token = os.environ.get(BOT_TOKEN_ENV)
    if token:
        headers[TOKEN_HEADER] = token
    return headers


def _request_json(
    method: str, url: str, payload: dict[str, Any] | None = None
) -> dict[str, Any] | list[dict[str, Any]]:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(  # noqa: S310 - loopback http URL built above.
        url,
        data=data,
        headers=_request_headers(),
        method=method,
    )
    with opener.open(request, timeout=REQUEST_TIMEOUT) as response:
        return json.load(response)


def _exit_for_launch_error(exc: HTTPError) -> NoReturn:
    body = exc.read().decode("utf-8", errors="replace")
    try:
        detail = json.loads(body)
    except ValueError:
        detail = {}
    if isinstance(detail, dict) and detail.get("error") == "instance_cap":
        message = (
            f"instance cap reached: {detail.get('live')} of {detail.get('max')} "
            "live agents"
        )
        print(message, file=sys.stderr)
        raise SystemExit(INSTANCE_CAP_EXIT) from exc
    raise SystemExit(f"launch failed: HTTP {exc.code} {body}".strip()) from exc


def launch(args: argparse.Namespace) -> dict[str, Any]:
    prompt = sys.stdin.read() if args.prompt == "-" else args.prompt
    payload = launch_payload(args, prompt)
    try:
        result = _request_json("POST", base_url(args.port), payload)
    except HTTPError as exc:
        _exit_for_launch_error(exc)
    assert isinstance(result, dict)  # noqa: S101 - the launch route returns an object.
    return {"id": result["agent_id"], "address": args.slot}


def list_agents(parent: str | None, port: int) -> list[dict[str, Any]]:
    query = f"?{urlencode({'parent': parent})}" if parent else ""
    rows = _request_json("GET", f"{base_url(port)}{query}")
    assert isinstance(rows, list)  # noqa: S101 - the list route returns an array.
    return rows


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="varde-runner agent")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--port", type=int, default=8765)
    commands = parser.add_subparsers(dest="action", required=True)
    prompt = commands.add_parser(
        "prompt", parents=[common], help="send a prompt to an agent"
    )
    prompt.add_argument("agent")
    prompt.add_argument("text", nargs="?")
    for name in ("interrupt", "stop", "archive"):
        commands.add_parser(name, parents=[common]).add_argument("agent")
    mode = commands.add_parser(
        "mode",
        parents=[common],
        help="stop, then resume with a new mode (needs a paired browser)",
    )
    mode.add_argument("agent")
    mode.add_argument("text", metavar="mode")
    launch_parser = commands.add_parser(
        "launch", parents=[common], help="start an agent for a role"
    )
    launch_parser.add_argument("--role", required=True)
    launch_parser.add_argument("--workspace", required=True)
    launch_parser.add_argument("--prompt", required=True, help="text, or - for stdin")
    launch_parser.add_argument("--harness", help="check against the role's harness")
    launch_parser.add_argument("--mode", help="override the role's mode")
    launch_parser.add_argument("--slot")
    launch_parser.add_argument("--plan")
    launch_parser.add_argument(
        "--parent", default=os.environ.get("VARDE_AGENT_ID"), help="parent agent id"
    )
    list_parser = commands.add_parser(
        "list", parents=[common], help="list agents as JSON"
    )
    list_parser.add_argument("--parent")
    return parser


def _validate(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.action == "prompt" and not args.text:
        parser.error("prompt requires text")
    if args.action == "launch" and args.plan and not args.slot:
        parser.error("--plan requires --slot")


def main(argv: list[str]) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    _validate(parser, args)
    try:
        if args.action == "launch":
            result: Any = launch(args)
        elif args.action == "list":
            result = list_agents(args.parent, args.port)
        else:
            text = getattr(args, "text", None)
            result = run(args.action, args.agent, text, args.port)
    except HTTPError as exc:
        raise SystemExit(f"{args.action} failed: {_error_text(exc)}") from exc
    except URLError as exc:
        raise SystemExit(f"{args.action} request failed: {exc.reason}") from exc
    except (OSError, IncompleteRead) as exc:
        raise SystemExit(f"{args.action} stream interrupted: {exc}") from None
    print(json.dumps(result, sort_keys=True))
