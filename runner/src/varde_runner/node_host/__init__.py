"""Generic supervised Node host (protocol: runner/node-host/PROTOCOL.md)."""

from varde_runner.node_host.errors import (
    CallTimeout,
    FrameTooLarge,
    HostCallError,
    HostDown,
    HostRestarted,
    NodeHostError,
)
from varde_runner.node_host.frames import Event
from varde_runner.node_host.host import NodeHost, Subscription
from varde_runner.node_host.orphans import reap_orphans
from varde_runner.node_host.policy import GiveUp, Restart, RestartPolicy, next_action

__all__ = [
    "CallTimeout",
    "Event",
    "FrameTooLarge",
    "GiveUp",
    "HostCallError",
    "HostDown",
    "HostRestarted",
    "NodeHost",
    "NodeHostError",
    "Restart",
    "RestartPolicy",
    "Subscription",
    "next_action",
    "reap_orphans",
]
