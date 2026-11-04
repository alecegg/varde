"""Small data model helpers used by the accuracy fixture set."""

from dataclasses import dataclass
from typing import Iterable

MAX_RETRIES = 3
DEFAULT_NAME = "anonymous"
WIDE = 1 << 10


@dataclass(frozen=True)
class Account:
    owner: str
    balance: float = 0.0

    def deposit(self, amount: float) -> float:
        if amount <= 0:
            raise ValueError(f"bad amount: {amount}")
        self.balance += amount
        return self.balance


def total(accounts: Iterable[Account]) -> float:
    running = 0.0
    for account in accounts:
        running += account.balance
    return running


def summarize(accounts: Iterable[Account]) -> dict[str, float]:
    ranked = sorted(accounts, key=lambda item: item.balance, reverse=True)
    return {item.owner: item.balance for item in ranked[:MAX_RETRIES]}
