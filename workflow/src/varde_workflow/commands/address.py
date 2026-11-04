"""CLI operations for address binding markers."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping
from datetime import datetime, timedelta
from pathlib import Path

from varde_data.records.addresses import ReaderContext

from varde_workflow.binding import annotate_stale_bindings, clock_now

# Bare binds use this priority when more than one harness family is present.
SESSION_ENV_VARS = (
    ("CLAUDE_CODE_SESSION_ID", "claude"),
    ("CLAUDE_SESSION_ID", "claude"),
    ("CODEX_SESSION_ID", "codex"),
    ("CODEX_THREAD_ID", "codex"),
    ("CODEX_SESSION", "codex"),
    # Pi 1.3.0 exposes this in bash with the prompt-hook session ID.
    ("PI_SESSION_ID", "pi"),
)


def run_new(
    name: str,
    working: str | Path,
    *,
    ttl: timedelta = timedelta(hours=24),
    uses: int = 1,
    supersede: bool = False,
    now: datetime | None = None,
) -> int:
    from varde_data.config import load_data_config
    from varde_data.open import open_data

    marker = open_data(Path(working), load_data_config()).addresses.issue(
        name,
        ttl=ttl,
        uses=uses,
        supersede=supersede,
        now=now or clock_now(),
        issuer="cli",
    )
    print(marker)
    return 0


def run(args: argparse.Namespace, working: str | Path) -> int:
    from varde_data.config import load_data_config
    from varde_data.open import open_data

    addresses = open_data(Path(working), load_data_config()).addresses
    inbox = Path(working) / ".cache" / "inbox"
    now = clock_now()
    if args.address_action == "new":
        return _run_new_address(args, working, now)
    if args.address_action == "bind":
        env_session, env_harness = _session_and_harness_from_env(os.environ)
        explicit_harness = args.harness != "unknown"
        if args.session:
            session = args.session
        elif explicit_harness:
            session, _ = _session_and_harness_from_env(os.environ, harness=args.harness)
        else:
            session = env_session
        harness = args.harness if explicit_harness else env_harness
        if not session:
            raise ValueError(
                "a session id is required; pass --session or set a harness session "
                "environment variable"
            )
        context = ReaderContext(
            cwd=str(Path.cwd()),
            paseo_id=os.environ.get("PASEO_AGENT_ID"),
            agent_id=os.environ.get("VARDE_AGENT_ID"),
            runner_harness=os.environ.get("VARDE_HARNESS"),
            runner_endpoint=os.environ.get("VARDE_RUNNER_ENDPOINT"),
        )
        if not addresses.redeem(args.marker, session, harness, context, now=now):
            raise ValueError(addresses.marker_error(args.marker, now))
        return 0
    if args.address_action == "refresh":
        env_session, env_harness = _session_and_harness_from_env(os.environ)
        explicit_harness = args.harness != "unknown"
        if args.session:
            session = args.session
        elif explicit_harness:
            session, _ = _session_and_harness_from_env(os.environ, harness=args.harness)
        else:
            session = env_session
        harness = args.harness if explicit_harness else env_harness
        if not session:
            print("address refresh: a session id is required", file=sys.stderr)
            return 1
        paseo_id = os.environ.get("PASEO_AGENT_ID")
        agent_id = os.environ.get("VARDE_AGENT_ID")
        if not paseo_id and not agent_id:
            print(
                "address refresh: VARDE_AGENT_ID and PASEO_AGENT_ID are unset",
                file=sys.stderr,
            )
            return 1
        context = ReaderContext(
            cwd=str(Path.cwd()),
            paseo_id=paseo_id,
            agent_id=agent_id,
            runner_harness=os.environ.get("VARDE_HARNESS"),
            runner_endpoint=os.environ.get("VARDE_RUNNER_ENDPOINT"),
        )
        if not addresses.refresh_current(harness, session, context, now):
            print("address refresh: session has no current binding", file=sys.stderr)
            return 1
        return 0
    if args.address_action == "unbind":
        return 0 if addresses.unbind(args.target, now) else 1
    bindings = annotate_stale_bindings(
        [_binding_dict(record) for record in addresses.list_bindings()],
        getattr(args, "archived_paseo_id", []),
    )
    if args.json:
        print(
            json.dumps(
                {"bindings": bindings, "store": str(inbox)},
                ensure_ascii=False,
                sort_keys=True,
            )
        )
    else:
        for record in bindings:
            stale = " stale" if record["stale"] else ""
            print(
                f"{record['address']} {record['harness']} {record['session_id']}{stale}"
            )
        print(f"store: {inbox}")
    return 0


def _run_new_address(
    args: argparse.Namespace, working: str | Path, now: datetime
) -> int:
    from varde_data.config import load_data_config
    from varde_data.open import open_data
    from varde_data.service import AddressService

    from varde_workflow.slots import is_orchestrator_slot, is_pipeline_worker_slot

    plan = getattr(args, "plan", None)
    has_plan = plan is not None
    if has_plan and not (
        is_orchestrator_slot(args.name) or is_pipeline_worker_slot(args.name, plan)
    ):
        raise ValueError(
            "slot must use `orchestrator-<n>`, `<plan>-builder`, or "
            "`<plan>-reviewer` form when --plan is given"
        )
    is_slot = has_plan or is_orchestrator_slot(args.name)
    data = open_data(Path(working), load_data_config())
    if is_slot:
        AddressService(data.addresses, data.messages).add_alias(args.name, plan)
    marker = data.addresses.issue(
        args.name,
        ttl=timedelta(seconds=args.ttl),
        uses=args.uses,
        supersede=args.supersede or is_slot,
        now=now,
        issuer="cli",
    )
    print(marker)
    return 0


def _binding_dict(binding) -> dict[str, object]:
    return {
        "address": binding.address,
        "harness": binding.harness,
        "session_id": binding.session_id,
        "bound_at": binding.bound_at.isoformat().replace("+00:00", "Z"),
        "last_seen": binding.last_seen.isoformat().replace("+00:00", "Z"),
        "token_id": binding.token_id,
        **binding.extra,
    }


def _session_and_harness_from_env(
    env: Mapping[str, str], *, harness: str | None = None
) -> tuple[str, str]:
    for variable, family in SESSION_ENV_VARS:
        if harness is not None and family != harness:
            continue
        session = env.get(variable)
        if session:
            return session, family
    return "", "unknown"
