"""Watching the chain: classification, flags and their review."""
from __future__ import annotations

import pytest

from agent import scenarios
from agent.service import Rejected
from conftest import wallet


def by_class(rows):
    return [r["classification"] for r in rows]


@pytest.fixture
def history(service, locked):
    """Primary sale, a paid resale, an unpaid resale elsewhere, and a gift - all of edition 1."""
    scenarios.run(service, "primary-sale", {"edition": 1, "buyer": wallet("collector-1")})
    scenarios.run(service, "resale-with-royalty", {"edition": 1, "buyer": wallet("collector-2"),
                                                   "price": "20000.00"})
    scenarios.run(service, "resale-without-royalty", {"edition": 1, "buyer": wallet("collector-3"),
                                                      "price": "20000.00"})
    scenarios.run(service, "gift-transfer", {"edition": 1, "buyer": wallet("collector-4")})
    return locked


def test_each_transfer_is_classified(service, history):
    rows = service.scan()
    assert by_class(rows) == ["PRIMARY_SALE", "SALE_ROYALTY_PAID", "SALE_ROYALTY_MISSING", "TRANSFER_UNVERIFIED"]
    assert [r["status"] for r in rows] == [None, None, "OPEN", "OPEN"]


def test_unpaid_royalty_is_what_the_deal_would_have_paid(service, history):
    """The watch and the payout use the same split, so the owed amounts equal the paid ones."""
    rows = service.scan()
    paid_resale = next(s for s in service.list_sales(history) if s["type"] == "resale")
    paid = {l["party"]: l["amount_minor"] for l in paid_resale["lines"] if l["role"] != "seller"}
    missing = next(r for r in rows if r["classification"] == "SALE_ROYALTY_MISSING")
    owed = {o["party"]: o["short_minor"] for o in missing["owed"]}
    assert owed == paid  # same price (KES 20,000.00), nothing received
    assert sum(owed.values()) == missing["evidence"]["royalty-due-minor"]
    assert missing["evidence"]["royalty-received-minor"] == 0


def test_a_gift_is_not_an_accusation(service, history):
    gift = service.scan()[-1]
    assert gift["classification"] == "TRANSFER_UNVERIFIED"
    assert gift["rule"] == "no-payment-evidence"
    assert gift["owed"] == []
    flag = service.store.flag_for_tx(gift["tx"])
    text = service._flag_view(flag)["explanation"]
    assert "No royalty is claimed" in text


def test_partial_royalty_is_owed_only_the_shortfall(service, locked):
    scenarios.run(service, "primary-sale", {"edition": 1})
    scenarios.run(service, "resale-partial-royalty", {
        "edition": 1, "buyer": wallet("collector-2"), "price": "20000.00",
        "paid": [{"party": "artist-a", "amount": "100.00"}]})
    row = service.scan()[-1]
    assert row["classification"] == "SALE_ROYALTY_MISSING"
    artist = next(o for o in row["owed"] if o["party"] == "artist-a")
    assert artist["received_minor"] == 10_000
    assert artist["short_minor"] == artist["due_minor"] - 10_000
    assert row["evidence"]["buyer-paid-minor"] == 2_000_000  # the whole price, counted from the payments


def test_rescanning_does_not_duplicate_flags(service, history):
    service.scan()
    service.scan()
    assert len(service.list_flags()) == 2


def test_flags_are_reviewed_with_a_reason(service, history):
    service.scan()
    missing = next(f for f in service.list_flags() if f["classification"] == "SALE_ROYALTY_MISSING")
    with pytest.raises(Rejected):
        service.update_flag(missing["flag_id"], "RESOLVED", "  ")
    resolved = service.update_flag(missing["flag_id"], "RESOLVED", "Seller paid the royalty off-chain; receipt on file.")
    assert resolved["status"] == "RESOLVED"
    assert [h["status"] for h in resolved["history"]] == ["OPEN", "RESOLVED"]
    # A rescan doesn't reopen it.
    row = next(r for r in service.scan() if r["tx"] == missing["tx"])
    assert row["status"] == "RESOLVED"
    assert {f["status"] for f in service.list_flags("OPEN")} == {"OPEN"}


def test_flag_status_must_be_known(service, history):
    service.scan()
    flag = service.list_flags()[0]
    with pytest.raises(Rejected):
        service.update_flag(flag["flag_id"], "IGNORED", "because")


def test_flag_explanation_states_the_evidence(service, history):
    service.scan()
    missing = next(f for f in service.list_flags() if f["classification"] == "SALE_ROYALTY_MISSING")
    assert "the new holder paid KES 20,000.00, so this was a sale" in missing["explanation"]
    assert missing["total_owed_minor"] == missing["evidence"]["royalty-due-minor"]
    assert any(s["rule"] == "royalty-amount" for s in missing["steps"])
