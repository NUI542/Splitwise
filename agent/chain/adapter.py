"""The chain adapter: the only way the agent reads the chain.

The simulator implements it now. A real chain (Cardano, an EVM chain or
another) implements the same two reads later, and nothing else changes.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Protocol


@dataclass(frozen=True)
class Transfer:
    """An edition moving from one wallet to another."""

    tx: str
    collection: str  # the deal the editions belong to
    edition: int
    from_wallet: str
    to_wallet: str
    ts: int  # Unix seconds
    seq: int  # position on the chain; orders transfers in the same second


@dataclass(frozen=True)
class Payment:
    """Money moving inside a transaction."""

    tx: str
    from_wallet: str
    to_wallet: str
    amount_minor: int
    currency: str


class ChainAdapter(Protocol):
    def read_transfers(self, collection: str) -> list[Transfer]:
        """Every transfer of the collection's editions, oldest first."""
        ...

    def read_payments(self, txs: Iterable[str]) -> list[Payment]:
        """Every payment inside the given transactions."""
        ...


def mint_address(collection: str) -> str:
    """The address new editions are minted from."""
    return f"mint:{collection}"
