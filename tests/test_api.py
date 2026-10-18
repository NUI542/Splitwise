"""The acceptance run, end to end over HTTP:

invalid deal -> fix -> approve -> lock -> primary sale -> resale with royalty
-> resale without royalty (flagged) -> gift (unverified, not accused)
-> "why did I get this?" answered.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agent.engine import Engine
from agent.registry import Registry
from agent.service import DealService
from agent.store import Store
from api.main import create_app
from conftest import Clock

DATA = Path(__file__).resolve().parent.parent / "data"


@pytest.fixture
def client(engine, registry) -> TestClient:
    return TestClient(create_app(DealService(Store(":memory:"), engine, registry, clock=Clock())))


def test_end_to_end(client):
    invalid = json.loads((DATA / "sample_deal_invalid.json").read_text(encoding="utf-8"))

    # 1. An invalid deal is rejected with a clear reason; the 12% royalty is only a warning.
    report = client.post("/deals/check", json=invalid).json()
    assert not report["valid"]
    assert [e["rule"] for e in report["errors"]] == ["shares-not-100"]
    assert report["errors"][0]["detail"] == "The shares add up to 110.00%, not 100.00%."
    assert [w["rule"] for w in report["warnings"]] == ["royalty-above-10"]
    assert client.post("/deals", json=invalid).status_code == 422

    # 2. Fix it: 60% for the artist. Still a 12% royalty, which is allowed.
    fixed = dict(invalid, shares=[dict(s) for s in invalid["shares"]])
    fixed["shares"][0]["value"] = "60"
    report = client.post("/deals/check", json=fixed).json()
    assert report["valid"] and report["summary"]["text"]
    saved = client.post("/deals", json=fixed).json()
    deal_id, version = saved["deal_id"], saved["version"]

    # 3. Approvals: locking with one missing is refused, naming who.
    for p in fixed["parties"][:-1]:
        assert client.post(f"/deals/{deal_id}/approve", json={"version": version, "party_id": p["id"]}).status_code == 200
    refused = client.post(f"/deals/{deal_id}/lock", json={"version": version})
    assert refused.status_code == 422
    errors = refused.json()["report"]["errors"]
    assert [(e["rule"], e["data"]["party"]) for e in errors] == [("approval-missing", "studio-d")]
    client.post(f"/deals/{deal_id}/approve", json={"version": version, "party_id": "studio-d"})
    locked = client.post(f"/deals/{deal_id}/lock", json={"version": version}).json()
    assert locked["locked_at"]
    assert client.get(f"/deals/{deal_id}/versions").json()[0]["status"] == "active"

    # 4. Sales.
    primary = client.post("/sim/primary-sale", json={}).json()["sale"]
    assert sum(l["amount_minor"] for l in primary["lines"]) == primary["price_minor"]
    resale = client.post("/sim/resale-with-royalty", json={}).json()["sale"]
    assert resale["type"] == "resale"
    assert client.post("/sim/resale-without-royalty", json={}).status_code == 200
    assert client.post("/sim/gift-transfer", json={}).status_code == 200
    assert len(client.get("/sales").json()) == 2  # only the two BASIX.MARKET sales are in the ledger

    # 5. Watch.
    rows = client.post("/watch/scan").json()
    assert [r["classification"] for r in rows] == [
        "PRIMARY_SALE", "SALE_ROYALTY_PAID", "SALE_ROYALTY_MISSING", "TRANSFER_UNVERIFIED"]
    flags = client.get("/flags", params={"status": "open"}).json()
    assert {f["classification"] for f in flags} == {"SALE_ROYALTY_MISSING", "TRANSFER_UNVERIFIED"}
    gift = next(f for f in flags if f["classification"] == "TRANSFER_UNVERIFIED")
    assert gift["owed"] == []
    dismissed = client.patch(f"/flags/{gift['flag_id']}", json={"status": "DISMISSED",
                                                               "reason": "Collector moved it to their own wallet."})
    assert dismissed.json()["status"] == "DISMISSED"

    # 6. "Why did I get this?"
    answer = client.get(f"/sales/{resale['sale_id']}/explain", params={"party": "studio-d"}).json()
    line = answer["lines"][0]
    assert line["party"] == "studio-d"
    assert f"get {line['amount_display']} for sale {resale['sale_id']}" in answer["explanation"]
    assert answer["trace"]["steps"][0]["rule"] == "royalty-amount"


def test_errors_are_json_with_a_code(client):
    missing = client.get("/sales/nope/explain")
    assert missing.status_code == 404 and missing.json()["error"] == "sale-not-found"
    assert client.post("/sim/not-a-scenario", json={}).json()["error"] in ("scenario-unknown", "deal-not-locked")


def test_rules_catalogue(client):
    rules = {r["rule"]: r for r in client.get("/rules").json()["rules"]}
    assert rules["shares-not-100"]["statement"] == "Shares add up to exactly 100%."
    assert rules["royalty-above-10"]["stage"] == "draft"
