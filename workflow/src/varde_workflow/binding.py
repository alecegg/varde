"""Session-to-address bindings backed by the workflow inbox cache."""

from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from varde_data.records.addresses import ReaderContext

_NAME = re.compile(r"[A-Za-z0-9._-]{1,64}\Z", re.ASCII)
_MARKER = re.compile(
    r"\[varde-address: ([A-Za-z0-9._-]{1,64}) (vt1\.[A-Z2-7]{26})\]\Z",
    re.ASCII,
)


def resolve_working_dir(start: str | Path) -> Path:
    from varde_workflow.workdir import resolve_working_dir

    return resolve_working_dir(start)


def resolve_working_dir_with_source(start: str | Path) -> tuple[Path, bool]:
    from varde_workflow.workdir import resolve_working_dir_with_source

    return resolve_working_dir_with_source(start)


def parse_marker(prompt: str) -> tuple[str, str] | None:
    """Return the first valid marker on its own line in the first five lines."""
    for line in prompt.split("\n")[:5]:
        match = _MARKER.fullmatch(line.removesuffix("\r"))
        if match:
            return match.group(1), match.group(2)
    return None


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def clock_now() -> datetime:
    """Return the injectable workflow clock used by repository operations."""
    return datetime.now(UTC)


def session_key(harness: str, session_id: str) -> str:
    """Return the persistent key for a harness session."""
    return f"{harness}-{hashlib.sha256(session_id.encode()).hexdigest()}"


def annotate_stale_bindings(
    bindings: list[dict[str, object]], archived_paseo_ids: Iterable[str]
) -> list[dict[str, object]]:
    """Copy bindings and mark those belonging to archived Paseo agents."""
    archived = set(archived_paseo_ids)
    result = []
    for record in bindings:
        wake_context = record.get("wake_context")
        paseo_id = None
        if isinstance(wake_context, dict):
            paseo_id = wake_context.get("paseo_id", wake_context.get("paseo_agent_id"))
        result.append(
            {**record, "stale": isinstance(paseo_id, str) and paseo_id in archived}
        )
    return result


class BindingStore:
    """Compatibility facade over the configured address repository."""

    def __init__(self, working: str | Path):
        from varde_data.config import load_data_config
        from varde_data.open import open_data

        self.working = Path(working)
        self.repo = open_data(self.working, load_data_config()).addresses
        # Path shims remain for the frozen workflow golden readers.
        self.addresses = self.working / ".cache" / "inbox" / "addresses"
        self.bindings = self.working / ".cache" / "inbox" / "bindings"

    @staticmethod
    def _context(cwd: str, env: dict[str, str] | None = None) -> ReaderContext:
        env = env or {}
        return ReaderContext(
            cwd=cwd,
            paseo_id=env.get("PASEO_AGENT_ID"),
            agent_id=env.get("VARDE_AGENT_ID"),
            runner_harness=env.get("VARDE_HARNESS"),
            runner_endpoint=env.get("VARDE_RUNNER_ENDPOINT"),
            env_address=env.get("VARDE_ADDRESS"),
        )

    @staticmethod
    def _as_dict(binding) -> dict[str, object]:
        return {
            "address": binding.address,
            "session_id": binding.session_id,
            "harness": binding.harness,
            "bound_at": _timestamp(binding.bound_at),
            "last_seen": _timestamp(binding.last_seen),
            "token_id": binding.token_id,
            **binding.extra,
        }

    def issue(
        self,
        name: str,
        *,
        ttl: timedelta = timedelta(hours=24),
        uses: int = 1,
        supersede: bool = False,
        now: datetime,
        issuer: str = "unknown",
    ) -> str:
        if not _NAME.fullmatch(name):
            raise ValueError("invalid address name")
        return self.repo.issue(
            name, ttl=ttl, uses=uses, supersede=supersede, now=now, issuer=issuer
        )

    def redeem(
        self, marker: str, session_id: str, harness: str, cwd: str, *, now: datetime
    ) -> bool:
        env = dict(os.environ)
        return self.repo.redeem(
            marker, session_id, harness, self._context(cwd, env), now=now
        )

    def marker_error(self, marker: str, now: datetime) -> str:
        return self.repo.marker_error(marker, now)

    def _current(self, address_path: Path) -> dict[str, str] | None:
        """Compatibility view for relay callers still reading the old pointer shape."""
        binding = self.repo.current_binding(address_path.name)
        if binding is None:
            return None
        return {
            "session_key": session_key(binding.harness, binding.session_id),
            "token_id": binding.token_id,
        }

    def refresh_current(  # noqa: PLR0913
        self,
        harness: str,
        session_id: str,
        cwd: str,
        paseo_id: str | None,
        now: datetime,
        *,
        agent_id: str | None = None,
        runner_harness: str | None = None,
        runner_endpoint: str | None = None,
    ) -> bool:
        if not any((paseo_id, agent_id)):
            return False
        context = ReaderContext(
            cwd=cwd,
            paseo_id=paseo_id,
            agent_id=agent_id,
            runner_harness=runner_harness,
            runner_endpoint=runner_endpoint,
        )
        return self.repo.refresh_current(harness, session_id, context, now)

    def resolve_reader(
        self,
        harness: str,
        session_id: str,
        prompt: str,
        env: dict[str, str],
        now: datetime,
    ) -> str | None:
        marker_parts = parse_marker(prompt)
        marker = (
            f"[varde-address: {marker_parts[0]} {marker_parts[1]}]"
            if marker_parts
            else None
        )
        address = self.repo.resolve_reader(
            harness,
            session_id,
            marker,
            self._context(env.get("PWD", "."), env),
            now,
        )
        if address is not None:
            self.repo.clear_wake_gone(address, now)
        return address

    def unbind(self, selector: str, now: datetime) -> bool:
        return self.repo.unbind(selector, now)

    def list_bindings(self) -> list[dict[str, object]]:
        return [self._as_dict(binding) for binding in self.repo.list_bindings()]

    def live_addresses(self, now: datetime) -> set[str]:
        return set(self.repo.live_addresses(now))


def wake_of(working: str | Path, address: str) -> dict[str, object] | None:
    from varde_data.config import load_data_config
    from varde_data.open import open_data

    wake = open_data(Path(working), load_data_config()).addresses.wake_of(address)
    return dict(wake) if wake is not None else None


def mark_wake_gone(working: str | Path, address: str, now: datetime) -> None:
    from varde_data.config import load_data_config
    from varde_data.open import open_data

    open_data(Path(working), load_data_config()).addresses.mark_wake_gone(address, now)


def clear_wake_gone(working: str | Path, address: str, now: datetime) -> None:
    """Clear a gone marker immediately when the bound hook resolves mail."""
    from varde_data.config import load_data_config
    from varde_data.open import open_data

    open_data(Path(working), load_data_config()).addresses.clear_wake_gone(address, now)
