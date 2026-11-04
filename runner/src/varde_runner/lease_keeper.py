"""Periodic expiry for abandoned role-queue claims."""

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime

from varde_data.errors import Invalid, Locked, WrongMode
from varde_data.repos.queue import QueueRepository

logger = logging.getLogger(__name__)


def expire_tick(repo: QueueRepository, now: datetime) -> int:
    """Expire claims whose leases have elapsed at ``now``; never renew claims."""
    return len(repo.expire(now.astimezone(UTC).isoformat()))


async def run_expiry_ticks(repository: Callable[[], QueueRepository]) -> None:
    """Retry expiry checks, including while queue migration is pending."""
    while True:
        delay = 15
        try:
            expire_tick(repository(), datetime.now(UTC))
        except WrongMode:
            logger.debug("queue lease expiry unavailable before SQLite store setup")
        except Invalid as error:
            logger.warning("queue lease expiry waiting for a valid queue: %s", error)
            delay = 60
        except Locked as error:
            logger.info("queue lease expiry will retry after store lock: %s", error)
        except Exception:
            logger.exception("lease expiry tick failed")
        await asyncio.sleep(delay)
