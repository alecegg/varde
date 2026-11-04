"""Launch a native agent for an explicitly selected role and harness."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, NoReturn

from varde_data.config import load_data_config
from varde_data.open import open_data
from varde_data.records.addresses import ReaderContext
from varde_data.service import AddressService

from varde_runner.bot_profile import profile_for_role
from varde_runner.config import ConfigError, Model, config_path, load_config
from varde_runner.instance_cap import InstanceCapError
from varde_runner.plugins import SessionRef, SessionSpec

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from varde_runner.supervisor import Supervisor


class AgentLaunchError(ValueError):
    """Invalid role, harness selection, or workspace for an agent launch."""


class DisabledHarnessError(AgentLaunchError):
    """The requested harness is known but is not enabled in the runner."""


def _require_available(supervisor: Supervisor, harness: str) -> None:
    if harness in supervisor.registry.harnesses():
        return
    if harness in supervisor.registry.known_harnesses():
        raise DisabledHarnessError(f"harness is disabled: {harness}")
    raise AgentLaunchError(f"unknown harness: {harness}")


def data_root(cwd: Path) -> Path:
    """Return the shared Varde data root, falling back to the agent workspace."""
    working = os.environ.get("VARDE_WORKING_DIR")
    return Path(working).expanduser() if working else cwd


async def launch_agent(  # noqa: PLR0913 - public launch contract; new options are keyword-only.
    supervisor: Supervisor,
    harness: str | None,
    workspace: str,
    role: str,
    prompt: str,
    address: dict[str, str | None] | None = None,
    *,
    mode: str | None = None,
    parent_id: str | None = None,
    launched_by: str | None = None,
) -> SessionRef:
    """Resolve a role and start its session in an existing workspace.

    ``harness`` is an optional check: ``None`` uses the role's resolved harness.
    ``mode`` overrides the role's mode; ``parent_id`` is stored on the session.
    """
    if harness is not None:
        _require_available(supervisor, harness)
    try:
        resolved = load_config(
            config_path(), supervisor.registry.known_harnesses()
        ).resolve(role)
    except ConfigError as exc:
        raise AgentLaunchError(str(exc)) from exc
    if harness is not None and resolved.harness != harness:
        raise AgentLaunchError(f"role {role!r} selects harness {resolved.harness!r}")
    harness = resolved.harness
    _require_available(supervisor, harness)
    if not resolved.enabled:
        raise AgentLaunchError(f"role is disabled: {role}")

    path = Path(workspace).expanduser()
    cwd = path.resolve() if path.is_dir() else None
    if cwd is None:
        try:
            entries = await supervisor.registry.list_workspaces(harness)
        except RuntimeError, OSError:
            entries = []
        entry = next((item for item in entries if item.get("id") == workspace), None)
        listed_cwd = entry.get("cwd") if entry else None
        workspace_path = (
            Path(listed_cwd).expanduser() if isinstance(listed_cwd, str) else None
        )
        if workspace_path is None or not workspace_path.is_dir():
            raise AgentLaunchError(
                "workspace must be an existing directory or listed workspace"
            )
        cwd = workspace_path.resolve()

    model = Model(
        resolved.harness,
        resolved.model,
        resolved.reasoning_effort,
        mode or resolved.mode,
    )
    plugin = supervisor.registry.plugin_for(harness)
    profile = profile_for_role(role)
    if profile is not None and not plugin.capabilities.restricted_profile:
        raise AgentLaunchError(
            f"harness {harness!r} cannot enforce the {profile} profile"
        )
    settings = plugin.session_settings(model)
    try:
        marker, alias_created = await _issue_launch_address(cwd, address)
    except ValueError as exc:
        raise AgentLaunchError(str(exc)) from exc
    if marker:
        prompt = f"{marker}\n{prompt}"
    spec = SessionSpec(
        provider=supervisor.registry.provider_key(harness),
        model=settings.model,
        workspace_id=workspace,
        cwd=str(cwd),
        prompt=prompt,
        reasoning_effort=settings.reasoning_effort,
        mode_id=settings.mode_id,
        runner_harness=runner_harness_name(harness),
        profile=profile,
        launched_by=launched_by,
    )

    async def cleanup_address() -> None:
        if marker is not None and address is not None:
            await asyncio.to_thread(
                _revoke_address, data_root(cwd), address, alias_created
            )

    ref = await _start_session(supervisor, spec, role, cleanup_address, mode)
    if parent_id:
        supervisor.store.update_session(ref.session_id, parent_id=parent_id)
    if launched_by:
        supervisor.store.update_session(ref.session_id, launched_by=launched_by)
    if marker is not None and address is not None:
        await _bind_launch_address(
            supervisor,
            ref,
            cwd,
            harness,
            address,
            (marker, alias_created),
            parent_id,
        )
    return ref


async def _issue_launch_address(
    cwd: Path, address: dict[str, str | None] | None
) -> tuple[str | None, bool]:
    if address is None:
        return None, False
    return await asyncio.to_thread(_issue_address, data_root(cwd), address)


async def _start_session(
    supervisor: Supervisor,
    spec: SessionSpec,
    role: str,
    cleanup: Callable[[], Awaitable[None]],
    explicit_mode: str | None,
) -> SessionRef:
    try:
        return await supervisor.start_session(spec, role)
    except Exception as exc:
        try:
            await cleanup()
        except Exception:
            logger.exception("could not clean up after agent launch failure")
        capped = isinstance(exc, InstanceCapError)
        if explicit_mode and not capped and isinstance(exc, (ValueError, RuntimeError)):
            raise AgentLaunchError(f"mode {explicit_mode!r}: {exc}") from exc
        raise


async def _bind_launch_address(  # noqa: PLR0913, PLR0917 - one binding step with its issued marker and parent.
    supervisor: Supervisor,
    ref: SessionRef,
    cwd: Path,
    harness: str,
    address: dict[str, str | None],
    issued: tuple[str, bool],
    parent_id: str | None,
) -> None:
    marker, alias_created = issued
    try:
        remote_id, session_harness, context = _binding_details(
            supervisor, ref, cwd, harness, parent_id
        )
        redeemed = await asyncio.to_thread(
            _redeem_address,
            data_root(cwd),
            marker,
            remote_id,
            session_harness,
            context,
        )
        if not redeemed:
            _raise_bind_error(address.get("slot"))
        supervisor.register_address_binding(ref.session_id, data_root(cwd), remote_id)
    except Exception:
        try:
            await supervisor.stop(ref.session_id, "system:dashboard")
        except Exception:
            logger.exception("could not stop agent after address bind failure")
        finally:
            try:
                await asyncio.to_thread(
                    _revoke_address, data_root(cwd), address, alias_created
                )
            except Exception:
                logger.exception("could not revoke address after bind failure")
        raise


def _issue_address(cwd: Path, address: dict[str, str | None]) -> tuple[str, bool]:
    data = open_data(data_root(cwd), load_data_config())
    slot, plan = address.get("slot"), address.get("plan")
    if not slot:
        raise ValueError("address slot is required")
    alias_created = bool(
        plan and not any(plan in item.aliases for item in data.addresses.slots())
    )
    AddressService(data.addresses, data.messages).add_alias(slot, plan)
    # Redeeming consumes the marker, so only its first redeemer can bind it.
    marker = data.addresses.issue(
        slot,
        supersede=True,
        now=datetime.now(UTC),
        issuer="runner",
    )
    return marker, alias_created


def _revoke_address(
    cwd: Path, address: dict[str, str | None], remove_plan_alias: bool = True
) -> None:
    data = open_data(data_root(cwd), load_data_config())
    slot = address.get("slot")
    if slot:
        data.addresses.unbind(slot, datetime.now(UTC))
        plan = address.get("plan")
        if plan and remove_plan_alias:
            data.addresses.remove_alias(plan)


def runner_harness_name(harness: str) -> str:
    """Return the hyphenated harness name the supervisor stores and wakes by."""
    return harness.replace("_", "-")


def _binding_details(
    supervisor: Supervisor,
    ref: SessionRef,
    cwd: Path,
    harness: str,
    parent_id: str | None = None,
) -> tuple[str, str, ReaderContext]:
    stored = supervisor.store.get_session(ref.session_id)
    if stored is None:
        raise AgentLaunchError("launched session was not persisted")
    remote_id = json.loads(stored["ref"])["session_id"]
    session_harness = {
        "claude_cli": "claude",
        "claude-cli": "claude",
        "codex_app_server": "codex",
        "codex-app-server": "codex",
    }.get(harness, harness)
    context = ReaderContext(
        cwd=str(cwd),
        agent_id=ref.session_id,
        runner_harness=runner_harness_name(harness),
        runner_binding=True,
        parent_id=parent_id,
    )
    return remote_id, session_harness, context


def _redeem_address(
    cwd: Path, marker: str, remote_id: str, harness: str, context: ReaderContext
) -> bool:
    data = open_data(data_root(cwd), load_data_config())
    return data.addresses.redeem(
        marker, remote_id, harness, context, now=datetime.now(UTC)
    )


def _raise_bind_error(slot: str | None) -> NoReturn:
    raise AgentLaunchError(f"could not bind address slot {slot!r}")
