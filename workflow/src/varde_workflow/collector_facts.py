"""Compatibility imports for pre-gathered collector inputs."""

from varde_workflow.collectors import (
    CollectorFacts,
    awaiting_user_from_facts,
    gather_collector_facts,
)

__all__ = ["CollectorFacts", "awaiting_user_from_facts", "gather_collector_facts"]
