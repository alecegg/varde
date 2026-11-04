from contract_queue import check_queue_contract, check_queue_lease_and_role_contract
from varde_data.backends.memory.queue import MemoryQueue


def test_memory_queue_contract() -> None:
    check_queue_contract(MemoryQueue())


def test_memory_queue_lease_and_role_contract() -> None:
    check_queue_lease_and_role_contract(MemoryQueue())
