"""Park and unpark a session's durable slot around idle reaping."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from varde_data.config import load_data_config
from varde_data.errors import WrongMode
from varde_data.open import open_data
from varde_data.repos.slots import SlotRepository
from varde_data.slot_model import Slot

logger = logging.getLogger(__name__)


def _slots() -> SlotRepository | None:
    working = os.environ.get("VARDE_WORKING_DIR")
    if not working:
        return None
    return open_data(Path(working).expanduser(), load_data_config()).slots


def _slot_for_session(session_id: str) -> tuple[SlotRepository, Slot] | None:
    slots = _slots()
    if slots is None:
        return None
    slot = slots.by_session(session_id)
    return None if slot is None else (slots, slot)


def park_session(session_id: str) -> bool:
    """Park the slot bound to a reaped session; a missing store is a no-op."""
    try:
        bound = _slot_for_session(session_id)
        if bound is None:
            return False
        slots, slot = bound
        if slot.state != "parked":
            slots.park(slot.slot_id, epoch=slot.epoch)
    except WrongMode:
        logger.debug("slot store is not SQLite; skipping park for %s", session_id)
        return False
    except Exception:
        logger.warning("could not park slot for session %s", session_id, exc_info=True)
        return False
    return True


def unpark_session(session_id: str) -> bool:
    """Reactivate the slot bound to a resumed session; a missing store is a no-op."""
    try:
        bound = _slot_for_session(session_id)
        if bound is None:
            return False
        slots, slot = bound
        if slot.state == "parked":
            slots.unpark(slot.slot_id, epoch=slot.epoch)
    except WrongMode:
        logger.debug("slot store is not SQLite; skipping unpark for %s", session_id)
        return False
    except Exception:
        logger.warning(
            "could not unpark slot for session %s", session_id, exc_info=True
        )
        return False
    return True
