"""A simulated chain, stored in the same SQLite file as the ledger.

It implements the ChainAdapter reads, plus `settle`, which records one
transaction: an edition transfer and the payments inside it. Minting and
money are simulated; nothing here touches a real chain.
"""
from __future__ import annotations

import sqlite3
from typing import Iterable

from .adapter import Payment, Transfer

SCHEMA = """
CREATE TABLE IF NOT EXISTS chain_transfers (
    tx TEXT PRIMARY KEY,
    collection TEXT NOT NULL,
    edition INTEGER NOT NULL,
    from_wallet TEXT NOT NULL,
    to_wallet TEXT NOT NULL,
    ts INTEGER NOT NULL,
    seq INTEGER NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS chain_payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tx TEXT NOT NULL REFERENCES chain_transfers(tx),
    from_wallet TEXT NOT NULL,
    to_wallet TEXT NOT NULL,
    amount_minor INTEGER NOT NULL CHECK (amount_minor > 0),
    currency TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS chain_transfers_immutable BEFORE UPDATE ON chain_transfers
BEGIN SELECT RAISE(ABORT, 'the chain is append-only'); END;
CREATE TRIGGER IF NOT EXISTS chain_transfers_no_delete BEFORE DELETE ON chain_transfers
BEGIN SELECT RAISE(ABORT, 'the chain is append-only'); END;
CREATE TRIGGER IF NOT EXISTS chain_payments_immutable BEFORE UPDATE ON chain_payments
BEGIN SELECT RAISE(ABORT, 'the chain is append-only'); END;
CREATE TRIGGER IF NOT EXISTS chain_payments_no_delete BEFORE DELETE ON chain_payments
BEGIN SELECT RAISE(ABORT, 'the chain is append-only'); END;
"""


class SimulatedChain:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        conn.executescript(SCHEMA)

    # ------------------------------------------------------------- reads

    def read_transfers(self, collection: str) -> list[Transfer]:
        rows = self.conn.execute(
            "SELECT tx, collection, edition, from_wallet, to_wallet, ts, seq "
            "FROM chain_transfers WHERE collection = ? ORDER BY seq",
            (collection,),
        ).fetchall()
        return [Transfer(*row) for row in rows]

    def read_payments(self, txs: Iterable[str]) -> list[Payment]:
        txs = list(txs)
        if not txs:
            return []
        marks = ",".join("?" * len(txs))
        rows = self.conn.execute(
            f"SELECT tx, from_wallet, to_wallet, amount_minor, currency "
            f"FROM chain_payments WHERE tx IN ({marks}) ORDER BY id",
            txs,
        ).fetchall()
        return [Payment(*row) for row in rows]

    # ------------------------------------------------------------ writes

    def settle(
        self,
        collection: str,
        edition: int,
        from_wallet: str,
        to_wallet: str,
        payments: Iterable[tuple[str, str, int]],
        currency: str,
        ts: int,
    ) -> Transfer:
        """Record one transaction. The caller owns the surrounding DB transaction."""
        seq = self.conn.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM chain_transfers").fetchone()[0]
        tx = f"simtx-{seq:06d}"
        self.conn.execute(
            "INSERT INTO chain_transfers (tx, collection, edition, from_wallet, to_wallet, ts, seq) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (tx, collection, edition, from_wallet, to_wallet, ts, seq),
        )
        for payer, payee, amount in payments:
            if amount > 0:
                self.conn.execute(
                    "INSERT INTO chain_payments (tx, from_wallet, to_wallet, amount_minor, currency) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (tx, payer, payee, int(amount), currency),
                )
        return Transfer(tx, collection, edition, from_wallet, to_wallet, ts, seq)
