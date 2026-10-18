"""The golden scenarios: the code must match the hand-worked answers in
data/golden_scenarios.csv to the cent.

The scenarios run once, in order, under data/sample_deal.json. Each row is
then compared with whatever answers have been filled in. A row with no
answers yet, or with some still blank, is reported as skipped (pending),
never as passed.
"""
from __future__ import annotations

import csv
from pathlib import Path

import pytest

from agent import scenarios
from agent.engine import Engine
from agent.registry import Registry
from agent.service import DealService
from agent.store import Store
from conftest import Clock, lock_deal, wallet

CSV = Path(__file__).resolve().parent.parent / "data" / "golden_scenarios.csv"
PARTIES = ("artist_a", "basix_market", "broker_c", "studio_d")


def load_rows() -> list[dict[str, str]]:
    with CSV.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


ROWS = load_rows()


def _wallet_of(name: str, deal_id: str) -> str:
    return f"mint:{deal_id}" if name.startswith("mint:") else wallet(name)


@pytest.fixture(scope="module")
def actual(sample_deal_data) -> dict[str, dict[str, object]]:
    service = DealService(Store(":memory:"), Engine(), Registry.load(), clock=Clock())
    deal_id = lock_deal(service, dict(sample_deal_data))
    assert deal_id == "deal-1"
    tx_of: dict[str, str] = {}
    results: dict[str, dict[str, object]] = {}
    for row in ROWS:
        rid, edition = row["id"], int(row["edition"])
        seller, buyer = _wallet_of(row["seller"], deal_id), _wallet_of(row["buyer"], deal_id)
        out: dict[str, object] = {}
        if row["channel"] == "platform":
            sale = service.record_sale({
                "event_id": rid, "deal_id": deal_id, "type": row["type"], "edition": edition,
                "price": row["price_kes"], "seller": seller, "buyer": buyer})
            lines = {l["party"]: l["amount_minor"] for l in sale["lines"]}
            for p in PARTIES:
                out[f"expected_{p}_minor"] = lines.get(p.replace("_", "-"))
            if row["type"] == "resale":
                royalty = next(s for s in sale["trace"]["steps"] if s["rule"] == "royalty-amount")
                out["expected_royalty_minor"] = royalty["values"]["result-minor"]
                out["expected_seller_minor"] = next(l["amount_minor"] for l in sale["lines"] if l["role"] == "seller")
            tx_of[rid] = sale["tx"]
        else:
            params = {"deal_id": deal_id, "edition": edition, "buyer": buyer, "price": row["price_kes"]}
            if row["type"] == "gift":
                name = "gift-transfer"
            elif row["royalty_paid_to"] in ("", "none"):
                name = "resale-without-royalty"
            else:
                name = "resale-partial-royalty"
                party, amount = row["royalty_paid_to"].split(":")
                params["paid"] = [{"party": party, "amount": amount}]
            done = scenarios.run(service, name, params)
            assert done["transfer"]["from"] == seller, f"{rid}: the seller in the CSV doesn't hold the edition"
            tx_of[rid] = done["transfer"]["tx"]
        results[rid] = out
    rows = {r["tx"]: r for r in service.scan(deal_id)}
    for rid, tx in tx_of.items():
        watch = rows[tx]
        results[rid]["expected_classification"] = watch["classification"]
        owed = {o["party"]: o["short_minor"] for o in watch["owed"]}
        for p in PARTIES:
            results[rid][f"expected_owed_{p}_minor"] = owed.get(p.replace("_", "-"), 0)
        if watch["classification"] == "SALE_ROYALTY_MISSING":
            results[rid].setdefault("expected_royalty_minor", watch["evidence"]["royalty-due-minor"])
    return results


@pytest.mark.parametrize("row", ROWS, ids=[r["id"] for r in ROWS])
def test_golden(row, actual):
    expected_cols = [c for c in row if c.startswith("expected_")]
    filled = {c: row[c].strip() for c in expected_cols if row[c].strip()}
    got = actual[row["id"]]
    mismatches = []
    for col, want in filled.items():
        have = got.get(col)
        want_value = want if col == "expected_classification" else int(want)
        if have != want_value:
            mismatches.append(f"{col}: hand-worked {want_value}, code {have}")
    assert not mismatches, f"{row['id']} ({row['description']}):\n  " + "\n  ".join(mismatches)
    blank = len(expected_cols) - len(filled)
    if not filled:
        pytest.skip(f"{row['id']}: pending - no hand-worked answers filled in yet")
    if blank:
        pytest.skip(f"{row['id']}: {len(filled)} values match; {blank} answer columns still blank")
