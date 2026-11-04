"""Reusable behavioral checks for queue repository backends."""

from varde_data.errors import Conflict, NotFound
from varde_data.records.queue import QueueItemInput


def check_queue_contract(repo) -> None:
    initial_version = repo.version()
    first = repo.enqueue(QueueItemInput("one", "plan", queue_name="contract"))
    assert repo.version() != initial_version
    item_version = repo.version()
    assert repo.enqueue(QueueItemInput("one", "plan", queue_name="contract")) == first
    assert repo.version() == item_version
    assert repo.get("contract", "one") == first
    try:
        repo.get("contract", "missing")
    except NotFound:
        pass
    else:
        raise AssertionError("missing item should raise NotFound")
    claimed = repo.claim("contract", worker="worker", lease_s=60)
    assert claimed is not None and claimed.state == "claimed"
    try:
        repo.renew(
            "contract",
            "one",
            worker="other",
            generation=claimed.claim_generation,
            lease_s=60,
        )
    except Conflict:
        pass
    else:
        raise AssertionError("lost lease should raise Conflict")
    released = repo.release(
        "contract", "one", worker="worker", generation=claimed.claim_generation
    )
    assert released.state == "queued"
    assert repo.events("one")


def check_queue_lease_and_role_contract(repo) -> None:
    repo.enqueue(QueueItemInput("review", "plan", role="reviewer", queue_name="roles"))
    repo.enqueue(QueueItemInput("build", "plan", role="builder", queue_name="roles"))
    repo.enqueue(QueueItemInput("unassigned", "plan", queue_name="roles"))

    claimed = repo.claim("roles", worker="builder-1", role="builder", lease_s=1)
    assert claimed is not None and claimed.id == "build"
    assert claimed.role == "builder"
    repo.release(
        "roles", claimed.id, worker="builder-1", generation=claimed.claim_generation
    )
    repo.transition("roles", "build", "merged", actor="builder-1")
    claimed = repo.claim("roles", worker="builder-2", role="builder", lease_s=1)
    assert claimed is not None and claimed.id == "unassigned"
    assert claimed.role is None
    repo.enqueue(QueueItemInput("any-role", "plan", role="reviewer", queue_name="any"))
    unfiltered = repo.claim("any", worker="worker", lease_s=1)
    assert unfiltered is not None and unfiltered.id == "any-role"

    repo.enqueue(QueueItemInput("active", "plan", queue_name="leases"))
    active = repo.claim(
        "leases", worker="worker", lease_s=120, now="2030-01-01T00:00:00+00:00"
    )
    assert active is not None
    active = repo.transition("leases", "active", "building", actor="worker")
    renewed = repo.renew_all(
        "leases", worker="worker", lease_s=30, now="2030-01-01T00:00:00+00:00"
    )
    assert len(renewed) == 1 and renewed[0].state == "building"
    expired = repo.expire(now="2030-01-01T00:00:10+00:00")
    assert all(item.id != "active" for item in expired)
    active = repo.transition("leases", "active", "in_review", actor="worker")
    renewed_item = repo.renew(
        "leases",
        "active",
        worker="worker",
        generation=active.claim_generation,
        lease_s=30,
    )
    assert renewed_item.state == "in_review"

    finished = repo.transition("leases", "active", "merged", actor="worker")
    assert finished.claimed_by is None and finished.claim_expires_at is None
    assert repo.expire(now="2040-01-01T00:00:00+00:00") == []
    assert repo.get("leases", "active").state == "merged"

    repo.enqueue(QueueItemInput("blocked", "plan", queue_name="leases"))
    blocked = repo.claim("leases", worker="worker", lease_s=1)
    assert blocked is not None and blocked.id == "blocked"
    blocked = repo.transition("leases", "blocked", "blocked", actor="worker")
    assert blocked.claimed_by is None and blocked.claim_expires_at is None
    assert repo.expire(now="2040-01-01T00:00:00+00:00") == []
