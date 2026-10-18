"""Draft-stage checks: one test per contradiction the deal must not contain."""
from __future__ import annotations

import pytest

from agent import facts as F
from conftest import lock_deal, wallet


def errors(report) -> set[str]:
    return {e["rule"] for e in report["errors"]}


def warnings(report) -> set[str]:
    return {w["rule"] for w in report["warnings"]}


def share(deal, party_id) -> dict:
    return next(s for s in deal["shares"] if s["party_id"] == party_id)


def party(deal, party_id) -> dict:
    return next(p for p in deal["parties"] if p["id"] == party_id)


def test_sample_deal_is_valid(service, deal):
    report = service.check_deal(deal)
    assert report["valid"], report["errors"]
    assert report["errors"] == [] and report["warnings"] == []
    assert report["summary"] is not None
    # The summary's split comes from the agent and adds up to the price.
    assert sum(l["amount_minor"] for l in report["summary"]["lines"]) == 1_500_000


# --------------------------------------------------------------- parties

def test_same_id_twice(service, deal):
    deal["parties"].append({"id": "artist-a", "name": "A. Artist", "role": "co-owner", "wallet": wallet("artist-a")})
    assert "party-duplicate-id" in errors(service.check_deal(deal))


def test_same_wallet_under_two_ids(service, deal):
    party(deal, "studio-d")["wallet"] = wallet("broker-c")
    assert "party-duplicate-wallet" in errors(service.check_deal(deal))


def test_no_artist(service, deal):
    party(deal, "artist-a")["role"] = "co-owner"
    assert "artist-missing" in errors(service.check_deal(deal))


def test_two_artists(service, deal):
    party(deal, "studio-d")["role"] = "artist"
    assert "artist-multiple" in errors(service.check_deal(deal))


def test_share_for_someone_not_listed(service, deal):
    deal["shares"].append({"party_id": "ghost", "kind": "percent", "value": "0.01"})
    assert "share-without-party" in errors(service.check_deal(deal))


def test_co_owner_with_no_share(service, deal):
    deal["shares"] = [s for s in deal["shares"] if s["party_id"] != "studio-d"]
    report = service.check_deal(deal)
    assert "party-without-share" in errors(report)


def test_artist_wallet_missing(service, deal):
    party(deal, "artist-a")["wallet"] = ""
    assert "wallet-missing" in errors(service.check_deal(deal))


def test_artist_wallet_belongs_to_someone_else(service, deal):
    party(deal, "artist-a")["wallet"] = wallet("collector-1")
    report = service.check_deal(deal)
    assert "wallet-owned-by-other" in errors(report)
    detail = next(e for e in report["errors"] if e["rule"] == "wallet-owned-by-other")["detail"]
    assert "Collector 1" in detail


# ---------------------------------------------------------------- shares

def test_shares_total_110(service, deal):
    share(deal, "artist-a")["value"] = "70"
    report = service.check_deal(deal)
    assert "shares-not-100" in errors(report)
    assert "110.00%" in next(e for e in report["errors"] if e["rule"] == "shares-not-100")["detail"]
    assert report["summary"] is None


@pytest.mark.parametrize("value", ["0", "-5"])
def test_zero_or_negative_share(service, deal, value):
    share(deal, "studio-d")["value"] = value
    assert "share-not-positive" in errors(service.check_deal(deal))


def test_mixed_share_forms(service, deal):
    share(deal, "studio-d").update({"kind": "fixed", "value": "1500.00"})
    assert "share-mixed-forms" in errors(service.check_deal(deal))


def test_share_finer_than_a_basis_point(service, deal):
    share(deal, "artist-a")["value"] = "59.995"
    share(deal, "studio-d")["value"] = "10.005"
    assert "share-not-whole-bps" in errors(service.check_deal(deal))


# ---------------------------------------------------- editions and price

@pytest.mark.parametrize("count", [0, -3, 2.5, "2.5"])
def test_bad_edition_count(service, deal, count):
    deal["edition_count"] = count
    assert "edition-count-invalid" in errors(service.check_deal(deal))


def test_edition_count_not_a_number(service, deal):
    deal["edition_count"] = "ten"
    assert "field-unreadable" in errors(service.check_deal(deal))


def test_more_sold_than_the_new_count(service, deal):
    deal_id = lock_deal(service, deal)
    for edition in (1, 2, 3):
        service.record_sale({"event_id": f"e{edition}", "deal_id": deal_id, "type": "primary",
                             "edition": edition, "price": "15000.00", "buyer": wallet("collector-1")})
    deal["edition_count"] = 2
    assert "editions-sold-exceeds-count" in errors(service.check_deal(deal, deal_id))


@pytest.mark.parametrize("price", ["0", "-100.00"])
def test_zero_or_negative_price(service, deal, price):
    deal["price"] = price
    assert "price-not-positive" in errors(service.check_deal(deal))


def test_price_in_another_currency(service, deal):
    deal["price_currency"] = "USD"
    assert "price-currency-mismatch" in errors(service.check_deal(deal))


def test_unknown_currency(service, deal):
    deal["currency"] = "XYZ"
    assert "currency-unknown" in errors(service.check_deal(deal))


def test_price_too_small_to_split(service, deal):
    deal["price"] = "0.05"
    report = service.check_deal(deal)
    flagged = {e["data"]["party"] for e in report["errors"] if e["rule"] == "price-too-small-to-split"}
    assert flagged == {"basix-market", "broker-c", "studio-d"}  # 60% of 5 cents is still 3 cents


def test_price_above_the_ceiling(service, deal):
    deal["price"] = "10000000000.01"
    assert "price-out-of-range" in errors(service.check_deal(deal))


def test_price_with_extra_decimals_rounds_down(service, deal):
    deal["price"] = "15000.999"
    report = service.check_deal(deal)
    assert report["valid"]
    assert report["terms"]["price_minor"] == 1_500_099


# --------------------------------------------------------------- royalty

@pytest.mark.parametrize("rate", ["-1", "100", "150"])
def test_royalty_out_of_range(service, deal, rate):
    deal["royalty_percent"] = rate
    assert "royalty-out-of-range" in errors(service.check_deal(deal))


def test_royalty_above_10_is_a_warning_not_an_error(service, deal):
    deal["royalty_percent"] = "12"
    report = service.check_deal(deal)
    assert report["valid"]
    assert warnings(report) == {"royalty-above-10"}


def test_royalty_too_small_for_anyone_but_the_artist(service, deal):
    deal["price"] = "100.00"
    deal["royalty_percent"] = "0.01"
    report = service.check_deal(deal)
    assert report["valid"]
    assert "royalty-too-small" in warnings(report)


def test_zero_royalty_is_allowed_without_warning(service, deal):
    deal["royalty_percent"] = "0"
    report = service.check_deal(deal)
    assert report["valid"] and report["warnings"] == []


# --------------------------------------------------------------- artwork

def test_artwork_already_has_a_locked_deal(service, deal):
    lock_deal(service, deal)
    assert "artwork-has-other-active-deal" in errors(service.check_deal(deal))


def test_new_version_of_the_same_deal_is_not_a_conflict(service, deal):
    deal_id = lock_deal(service, deal)
    deal["price"] = "16000.00"
    assert service.check_deal(deal, deal_id)["valid"]


def test_artist_is_not_the_rights_holder(service, deal):
    party(deal, "artist-a")["role"] = "co-owner"
    party(deal, "broker-c")["role"] = "artist"
    assert "artist-not-rights-holder" in errors(service.check_deal(deal))


def test_more_editions_than_consented(service, deal):
    deal["edition_count"] = 25
    report = service.check_deal(deal)
    assert "editions-exceed-consent" in errors(report)
    assert "consented to 10" in next(e for e in report["errors"] if e["rule"] == "editions-exceed-consent")["detail"]


def test_unknown_artwork(service, deal):
    deal["artwork_id"] = "aw-does-not-exist"
    assert "artwork-unknown" in errors(service.check_deal(deal))


# ----------------------------------------------------- input robustness

def test_awkward_text_is_quoted_safely(service, deal):
    party(deal, "studio-d")["name"] = 'Studio "D" \\ (placeholder) )) ; !(boom)'
    report = service.check_deal(deal)
    assert report["valid"], report["errors"]


def test_every_finding_names_a_catalogued_rule(service, engine, deal):
    share(deal, "artist-a")["value"] = "70"
    deal["edition_count"] = 0
    deal["royalty_percent"] = "12"
    docs = engine.rule_docs()
    report = service.check_deal(deal)
    for finding in report["errors"] + report["warnings"]:
        assert finding["rule"] in docs
        assert finding["statement"] and finding["detail"]


def test_facts_are_returned_for_inspection(service, deal):
    report = service.check_deal(deal)
    assert any(f.startswith("(deal-share 1 1 \"artist-a\" bps 6000)") for f in report["facts"])
    assert report["terms_hash"] == F.terms_hash(F.normalize_terms(deal))
