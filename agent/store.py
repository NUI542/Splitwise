"""SQLite storage: deal versions, approvals, locks, the ledger and flags.

Deal versions, approvals, locks, sales and payout lines are append-only;
triggers refuse updates and deletes. Flags are the one mutable record, and
every status change is logged in flag_events.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS deals (
    deal_id TEXT PRIMARY KEY,
    seq INTEGER NOT NULL UNIQUE,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS deal_versions (
    deal_id TEXT NOT NULL REFERENCES deals(deal_id),
    version INTEGER NOT NULL,
    terms_json TEXT NOT NULL,
    terms_hash TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    PRIMARY KEY (deal_id, version)
);
CREATE TABLE IF NOT EXISTS approvals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    deal_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    party_id TEXT NOT NULL,
    party_name TEXT NOT NULL,
    terms_hash TEXT NOT NULL,
    approved_at INTEGER NOT NULL,
    FOREIGN KEY (deal_id, version) REFERENCES deal_versions(deal_id, version)
);
CREATE TABLE IF NOT EXISTS locks (
    deal_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    locked_at INTEGER NOT NULL,
    terms_hash TEXT NOT NULL,
    PRIMARY KEY (deal_id, version),
    FOREIGN KEY (deal_id, version) REFERENCES deal_versions(deal_id, version)
);
CREATE TABLE IF NOT EXISTS sales (
    sale_id TEXT PRIMARY KEY,
    payload_hash TEXT NOT NULL,
    deal_id TEXT NOT NULL,
    deal_version INTEGER NOT NULL,
    terms_hash TEXT NOT NULL,
    type TEXT NOT NULL,
    edition INTEGER NOT NULL,
    price_minor INTEGER NOT NULL,
    currency TEXT NOT NULL,
    seller TEXT NOT NULL,
    buyer TEXT NOT NULL,
    sale_ts INTEGER NOT NULL,
    tx TEXT NOT NULL,
    trace_json TEXT NOT NULL,
    recorded_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS payout_lines (
    sale_id TEXT NOT NULL REFERENCES sales(sale_id),
    line_no INTEGER NOT NULL,
    party_id TEXT NOT NULL,
    role TEXT NOT NULL,
    wallet TEXT NOT NULL,
    amount_minor INTEGER NOT NULL CHECK (amount_minor >= 0),
    PRIMARY KEY (sale_id, line_no)
);
CREATE TABLE IF NOT EXISTS flags (
    flag_id TEXT PRIMARY KEY,
    tx TEXT NOT NULL UNIQUE,
    deal_id TEXT NOT NULL,
    edition INTEGER NOT NULL,
    classification TEXT NOT NULL,
    rule TEXT NOT NULL,
    deal_version INTEGER,
    owed_json TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    trace_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('OPEN', 'RESOLVED', 'DISMISSED')),
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS synthetic_parties (
    party_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    wallet TEXT NOT NULL UNIQUE,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS synthetic_artworks (
    artwork_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    rights_holder TEXT NOT NULL,
    consented_editions INTEGER NOT NULL CHECK (consented_editions > 0),
    consent_reference TEXT NOT NULL,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS flag_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    flag_id TEXT NOT NULL REFERENCES flags(flag_id),
    status TEXT NOT NULL,
    reason TEXT NOT NULL,
    at INTEGER NOT NULL
);
"""

APPEND_ONLY = ("deal_versions", "approvals", "locks", "sales", "payout_lines", "flag_events",
               "synthetic_parties", "synthetic_artworks")  # a consent record never changes


def _triggers() -> str:
    parts = []
    for table in APPEND_ONLY:
        for action in ("UPDATE", "DELETE"):
            parts.append(
                f"CREATE TRIGGER IF NOT EXISTS {table}_no_{action.lower()} BEFORE {action} ON {table} "
                f"BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END;"
            )
    return "\n".join(parts)


class Store:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA + _triggers())

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self.lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                yield self.conn
            except BaseException:
                self.conn.execute("ROLLBACK")
                raise
            else:
                self.conn.execute("COMMIT")

    def reset(self) -> None:
        """Wipe everything (demo reset). Rebuilds the file; triggers forbid row deletes."""
        with self.lock:
            tables = [r[0] for r in self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")]
            self.conn.execute("PRAGMA foreign_keys = OFF")
            for table in tables:
                self.conn.execute(f"DROP TABLE IF EXISTS {table}")
            self.conn.execute("PRAGMA foreign_keys = ON")
            self.conn.executescript(SCHEMA + _triggers())

    # --------------------------------------------- synthetic registry

    def add_synthetic_party(self, conn: sqlite3.Connection, party: dict[str, Any], now: int) -> None:
        conn.execute("INSERT INTO synthetic_parties (party_id, name, kind, wallet, created_at) VALUES (?, ?, ?, ?, ?)",
                     (party["id"], party["name"], party["kind"], party["wallets"][0], now))

    def add_synthetic_artwork(self, conn: sqlite3.Connection, artwork: dict[str, Any], now: int) -> None:
        conn.execute(
            "INSERT INTO synthetic_artworks (artwork_id, title, rights_holder, consented_editions, "
            "consent_reference, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (artwork["id"], artwork["title"], artwork["rights_holder"], artwork["consented_editions"],
             artwork["consent_reference"], now))

    def synthetic_parties(self) -> list[dict[str, Any]]:
        return [{"id": i, "name": n, "kind": k, "wallets": [w], "placeholder": True, "synthetic": True}
                for i, n, k, w in self.conn.execute(
                    "SELECT party_id, name, kind, wallet FROM synthetic_parties ORDER BY created_at, rowid")]

    def synthetic_artworks(self) -> list[dict[str, Any]]:
        return [{"id": i, "title": t, "rights_holder": r, "consented_editions": c, "consent_reference": ref,
                 "placeholder": True, "synthetic": True}
                for i, t, r, c, ref in self.conn.execute(
                    "SELECT artwork_id, title, rights_holder, consented_editions, consent_reference "
                    "FROM synthetic_artworks ORDER BY created_at, rowid")]

    # -------------------------------------------------------------- deals

    def new_deal_id(self, conn: sqlite3.Connection, now: int) -> str:
        seq = conn.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM deals").fetchone()[0]
        deal_id = f"deal-{seq}"
        conn.execute("INSERT INTO deals (deal_id, seq, created_at) VALUES (?, ?, ?)", (deal_id, seq, now))
        return deal_id

    def deal_exists(self, deal_id: str) -> bool:
        return self.conn.execute("SELECT 1 FROM deals WHERE deal_id = ?", (deal_id,)).fetchone() is not None

    def deal_ids(self) -> list[str]:
        return [r[0] for r in self.conn.execute("SELECT deal_id FROM deals ORDER BY seq")]

    def add_version(self, conn: sqlite3.Connection, deal_id: str, terms: dict, terms_hash: str,
                    now: int) -> int:
        version = conn.execute(
            "SELECT COALESCE(MAX(version), 0) + 1 FROM deal_versions WHERE deal_id = ?", (deal_id,)
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO deal_versions (deal_id, version, terms_json, terms_hash, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (deal_id, version, json.dumps(terms, sort_keys=True), terms_hash, now),
        )
        return version

    def versions(self, deal_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT version, terms_json, terms_hash, created_at FROM deal_versions "
            "WHERE deal_id = ? ORDER BY version", (deal_id,)
        ).fetchall()
        return [{"version": v, "terms": json.loads(t), "terms_hash": h, "created_at": c}
                for v, t, h, c in rows]

    def version(self, deal_id: str, version: int) -> dict[str, Any] | None:
        for v in self.versions(deal_id):
            if v["version"] == version:
                return v
        return None

    def latest_version(self, deal_id: str) -> int:
        return self.conn.execute(
            "SELECT COALESCE(MAX(version), 0) FROM deal_versions WHERE deal_id = ?", (deal_id,)
        ).fetchone()[0]

    # ------------------------------------------------- approvals & locks

    def add_approval(self, conn: sqlite3.Connection, deal_id: str, version: int, party_id: str,
                     party_name: str, terms_hash: str, now: int) -> None:
        conn.execute(
            "INSERT INTO approvals (deal_id, version, party_id, party_name, terms_hash, approved_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (deal_id, version, party_id, party_name, terms_hash, now),
        )

    def approvals(self, deal_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT version, party_id, party_name, terms_hash, approved_at FROM approvals "
            "WHERE deal_id = ? ORDER BY id", (deal_id,)
        ).fetchall()
        return [{"version": v, "party_id": p, "party_name": n, "terms_hash": h, "approved_at": t}
                for v, p, n, h, t in rows]

    def add_lock(self, conn: sqlite3.Connection, deal_id: str, version: int, terms_hash: str,
                 now: int) -> None:
        conn.execute("INSERT INTO locks (deal_id, version, locked_at, terms_hash) VALUES (?, ?, ?, ?)",
                     (deal_id, version, now, terms_hash))

    def locks(self, deal_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT version, locked_at, terms_hash FROM locks WHERE deal_id = ? ORDER BY version",
            (deal_id,)
        ).fetchall()
        return [{"version": v, "locked_at": t, "terms_hash": h} for v, t, h in rows]

    def locked_artworks(self) -> list[tuple[str, str]]:
        """(deal_id, artwork_id) for every deal with a locked version."""
        rows = self.conn.execute(
            "SELECT l.deal_id, v.terms_json FROM locks l JOIN deal_versions v "
            "ON v.deal_id = l.deal_id AND v.version = l.version"
        ).fetchall()
        seen = set()
        for deal_id, terms_json in rows:
            seen.add((deal_id, json.loads(terms_json).get("artwork_id")))
        return sorted(seen)

    # -------------------------------------------------------------- sales

    def sale(self, sale_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT sale_id, payload_hash, deal_id, deal_version, terms_hash, type, edition, price_minor, "
            "currency, seller, buyer, sale_ts, tx, trace_json, recorded_at FROM sales WHERE sale_id = ?",
            (sale_id,),
        ).fetchone()
        return self._sale_row(row) if row else None

    def sales(self, deal_id: str | None = None) -> list[dict[str, Any]]:
        query = ("SELECT sale_id, payload_hash, deal_id, deal_version, terms_hash, type, edition, "
                 "price_minor, currency, seller, buyer, sale_ts, tx, trace_json, recorded_at FROM sales")
        args: tuple = ()
        if deal_id:
            query += " WHERE deal_id = ?"
            args = (deal_id,)
        query += " ORDER BY recorded_at, rowid"
        return [self._sale_row(r) for r in self.conn.execute(query, args).fetchall()]

    def _sale_row(self, row) -> dict[str, Any]:
        keys = ("sale_id", "payload_hash", "deal_id", "deal_version", "terms_hash", "type", "edition",
                "price_minor", "currency", "seller", "buyer", "sale_ts", "tx", "trace_json", "recorded_at")
        sale = dict(zip(keys, row))
        sale["trace"] = json.loads(sale.pop("trace_json"))
        sale["lines"] = [
            {"line_no": n, "party": p, "role": r, "wallet": w, "amount_minor": a}
            for n, p, r, w, a in self.conn.execute(
                "SELECT line_no, party_id, role, wallet, amount_minor FROM payout_lines "
                "WHERE sale_id = ? ORDER BY line_no", (sale["sale_id"],))
        ]
        return sale

    def add_sale(self, conn: sqlite3.Connection, sale: dict[str, Any], lines: list[dict[str, Any]],
                 trace: dict[str, Any], now: int) -> None:
        conn.execute(
            "INSERT INTO sales (sale_id, payload_hash, deal_id, deal_version, terms_hash, type, edition, "
            "price_minor, currency, seller, buyer, sale_ts, tx, trace_json, recorded_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (sale["sale_id"], sale["payload_hash"], sale["deal_id"], sale["deal_version"],
             sale["terms_hash"], sale["type"], sale["edition"], sale["price_minor"], sale["currency"],
             sale["seller"], sale["buyer"], sale["sale_ts"], sale["tx"], json.dumps(trace), now),
        )
        for n, line in enumerate(lines, start=1):
            conn.execute(
                "INSERT INTO payout_lines (sale_id, line_no, party_id, role, wallet, amount_minor) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (sale["sale_id"], n, line["party"], line["role"], line["wallet"], line["amount_minor"]),
            )

    def primary_sales_count(self, deal_id: str) -> int:
        return self.conn.execute(
            "SELECT COUNT(*) FROM sales WHERE deal_id = ? AND type = 'primary'", (deal_id,)
        ).fetchone()[0]

    # -------------------------------------------------------------- flags

    def flag_for_tx(self, tx: str) -> dict[str, Any] | None:
        row = self.conn.execute(f"SELECT {_FLAG_COLS} FROM flags WHERE tx = ?", (tx,)).fetchone()
        return self._flag_row(row) if row else None

    def flag(self, flag_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(f"SELECT {_FLAG_COLS} FROM flags WHERE flag_id = ?", (flag_id,)).fetchone()
        return self._flag_row(row) if row else None

    def flags(self, status: str | None = None) -> list[dict[str, Any]]:
        query = f"SELECT {_FLAG_COLS} FROM flags"
        args: tuple = ()
        if status:
            query += " WHERE status = ?"
            args = (status,)
        query += " ORDER BY created_at, rowid"
        return [self._flag_row(r) for r in self.conn.execute(query, args).fetchall()]

    def add_flag(self, conn: sqlite3.Connection, flag: dict[str, Any], now: int) -> None:
        conn.execute(
            f"INSERT INTO flags ({_FLAG_COLS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (flag["flag_id"], flag["tx"], flag["deal_id"], flag["edition"], flag["classification"],
             flag["rule"], flag["deal_version"], json.dumps(flag["owed"]), json.dumps(flag["evidence"]),
             json.dumps(flag["trace"]), "OPEN", now, now),
        )
        conn.execute("INSERT INTO flag_events (flag_id, status, reason, at) VALUES (?, 'OPEN', ?, ?)",
                     (flag["flag_id"], "Raised by the watch scan.", now))

    def set_flag_status(self, conn: sqlite3.Connection, flag_id: str, status: str, reason: str,
                        now: int) -> None:
        conn.execute("UPDATE flags SET status = ?, updated_at = ? WHERE flag_id = ?", (status, now, flag_id))
        conn.execute("INSERT INTO flag_events (flag_id, status, reason, at) VALUES (?, ?, ?, ?)",
                     (flag_id, status, reason, now))

    def flag_events(self, flag_id: str) -> list[dict[str, Any]]:
        return [{"status": s, "reason": r, "at": a} for s, r, a in self.conn.execute(
            "SELECT status, reason, at FROM flag_events WHERE flag_id = ? ORDER BY id", (flag_id,))]

    def _flag_row(self, row) -> dict[str, Any]:
        keys = _FLAG_COLS.split(", ")
        flag = dict(zip(keys, row))
        for k in ("owed_json", "evidence_json", "trace_json"):
            flag[k[:-5]] = json.loads(flag.pop(k))
        flag["history"] = self.flag_events(flag["flag_id"])
        return flag


_FLAG_COLS = ("flag_id, tx, deal_id, edition, classification, rule, deal_version, owed_json, "
              "evidence_json, trace_json, status, created_at, updated_at")
