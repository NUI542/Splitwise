"""Paying out by the deal, and explaining it.

These use a deal of thirds (33.34% / 33.33% / 33.33%) so the rounding is
easy to check by eye. The golden scenarios in data/ are checked separately
against hand-worked answers (tests/test_golden.py).
"""
from __future__ import annotations

import pytest

from conftest import lock_deal, wallet


@pytest.fixture
def thirds() -> dict:
    return {
        "artwork_id": "aw-placeholder-002", "currency": "KES", "edition_count": 5,
        "price": "1.00", "royalty_percent": "10",
        "parties": [
            {"id": "artist-a", "name": "Artist A (placeholder)", "role": "artist", "wallet": wallet("artist-a")},
            {"id": "broker-c", "name": "GTM Broker C (placeholder)", "role": "co-owner", "wallet": wallet("broker-c")},
            {"id": "studio-d", "name": "Print Studio D (placeholder)", "role": "co-owner", "wallet": wallet("studio-d")},
        ],
        "shares": [
            {"party_id": "artist-a", "kind": "percent", "value": "33.34"},
            {"party_id": "broker-c", "kind": "percent", "value": "33.33"},
            {"party_id": "studio-d", "kind": "percent", "value": "33.33"},
        ],
    }


def amounts(sale) -> dict[str, int]:
    return {l["party"]: l["amount_minor"] for l in sale["lines"]}


def test_primary_sale_leftover_goes_to_the_artist(service, thirds):
    deal_id = lock_deal(service, thirds)
    sale = service.record_sale({"event_id": "p1", "deal_id": deal_id, "type": "primary", "edition": 1,
                                "price": "1.00", "buyer": wallet("collector-1")})
    # 100 cents: 33.34% -> 33, 33.33% -> 33, 33.33% -> 33; 1 cent left over -> artist.
    assert amounts(sale) == {"artist-a": 34, "broker-c": 33, "studio-d": 33}
    leftover = next(s for s in sale["trace"]["steps"] if s["rule"] == "leftover-to-artist")["values"]
    assert leftover["leftover-minor"] == 1 and leftover["artist"] == "artist-a"


def test_resale_royalty_rounds_down_and_seller_gets_the_rest(service, thirds):
    deal_id = lock_deal(service, thirds)
    service.record_sale({"event_id": "p1", "deal_id": deal_id, "type": "primary", "edition": 1,
                         "price": "1.00", "buyer": wallet("collector-1")})
    sale = service.record_sale({"event_id": "r1", "deal_id": deal_id, "type": "resale", "edition": 1,
                                "price": "0.19", "seller": wallet("collector-1"),
                                "buyer": wallet("collector-2")})
    # 10% of 19 cents is 1.9 cents -> royalty 1 cent; the seller keeps 18.
    # 1 cent split by thirds: every share rounds to 0, the 1 cent goes to the artist.
    assert amounts(sale) == {"collector-1": 18, "artist-a": 1, "broker-c": 0, "studio-d": 0}
    seller = next(l for l in sale["lines"] if l["role"] == "seller")
    assert seller["wallet"] == wallet("collector-1")


def test_every_payout_adds_up_exactly(service, thirds):
    deal_id = lock_deal(service, thirds)
    sale = service.record_sale({"event_id": "p1", "deal_id": deal_id, "type": "primary", "edition": 1,
                                "price": "1.00", "buyer": wallet("collector-1")})
    total = next(s for s in sale["trace"]["steps"] if s["rule"] == "sum-check")["values"]
    assert total["total-minor"] == total["expected-minor"] == sum(amounts(sale).values()) == 100


def test_the_sale_is_settled_on_the_chain_exactly_as_paid(service, thirds):
    deal_id = lock_deal(service, thirds)
    sale = service.record_sale({"event_id": "p1", "deal_id": deal_id, "type": "primary", "edition": 1,
                                "price": "1.00", "buyer": wallet("collector-1")})
    transfers = service.chain.read_transfers(deal_id)
    assert [(t.edition, t.from_wallet, t.to_wallet) for t in transfers] == [
        (1, f"mint:{deal_id}", wallet("collector-1"))]
    payments = service.chain.read_payments([sale["tx"]])
    assert {p.to_wallet: p.amount_minor for p in payments} == {
        l["wallet"]: l["amount_minor"] for l in sale["lines"]}


def test_explanation_uses_the_numbers_paid(service, thirds):
    deal_id = lock_deal(service, thirds)
    service.record_sale({"event_id": "p1", "deal_id": deal_id, "type": "primary", "edition": 1,
                         "price": "1.00", "buyer": wallet("collector-1")})
    out = service.explain("p1", "artist-a")
    text = out["explanation"]
    assert "Why did Artist A (placeholder) get KES 0.34 for sale p1?" in text
    assert "rounded down to KES 0.33" in text
    assert "left KES 0.01 unallocated" in text
    assert [l["amount_minor"] for l in out["lines"]] == [34]
    rules = [s["rule"] for s in out["trace"]["steps"]]
    assert rules[0] == "primary-split" and rules[-1] == "sum-check" and "leftover-to-artist" in rules
    for step in out["trace"]["steps"]:
        assert step["statement"]


def test_explanation_for_the_seller_and_by_wallet(service, thirds):
    deal_id = lock_deal(service, thirds)
    service.record_sale({"event_id": "p1", "deal_id": deal_id, "type": "primary", "edition": 1,
                         "price": "1.00", "buyer": wallet("collector-1")})
    service.record_sale({"event_id": "r1", "deal_id": deal_id, "type": "resale", "edition": 1,
                         "price": "0.19", "seller": wallet("collector-1"), "buyer": wallet("collector-2")})
    text = service.explain("r1", wallet("collector-1"))["explanation"]
    assert "As the seller" in text and "KES 0.19 − KES 0.01 = KES 0.18" in text


def test_explain_for_someone_who_got_nothing(service, thirds):
    from agent.service import NotFound
    deal_id = lock_deal(service, thirds)
    service.record_sale({"event_id": "p1", "deal_id": deal_id, "type": "primary", "edition": 1,
                         "price": "1.00", "buyer": wallet("collector-1")})
    with pytest.raises(NotFound):
        service.explain("p1", "collector-4")
