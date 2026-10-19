"""Synthetic artworks added in the app, and the examples written for them."""
from __future__ import annotations

import sqlite3

import pytest

from agent.service import NotFound, Rejected
from conftest import lock_deal


def errors(report) -> set[str]:
    return {e["rule"] for e in report["errors"]}


def test_a_new_artwork_is_tagged_placeholder_with_a_new_artist(service):
    out = service.add_artwork({"title": "Blue Hour", "consented_editions": 6, "new_artist_name": "Amina"})
    art, artist = out["artwork"], out["rights_holder"]
    assert art["title"] == "[PLACEHOLDER] Blue Hour"
    assert art["placeholder"] and art["synthetic"]
    assert art["consented_editions"] == 6
    assert "PLACEHOLDER consent record" in art["consent_reference"]
    assert artist["name"] == "Amina (placeholder)" and artist["id"] == "amina"
    assert artist["wallets"] == ["sim-wallet-amina"]
    assert art["id"] in service.registry.artworks and "amina" in service.registry.parties


def test_the_tag_is_not_doubled(service):
    out = service.add_artwork({"title": "[placeholder] Dusk", "consented_editions": 3, "rights_holder": "artist-a"})
    assert out["artwork"]["title"] == "[PLACEHOLDER] Dusk"
    assert not out["created_artist"]


@pytest.mark.parametrize("request_, code", [
    ({"title": "", "consented_editions": 5, "rights_holder": "artist-a"}, "artwork-title-missing"),
    ({"title": "X", "consented_editions": 0, "rights_holder": "artist-a"}, "artwork-consent-invalid"),
    ({"title": "X", "consented_editions": "2.5", "rights_holder": "artist-a"}, "artwork-consent-invalid"),
    ({"title": "X", "consented_editions": 5, "rights_holder": "collector-1"}, "artwork-rights-holder-unknown"),
    ({"title": "X", "consented_editions": 5}, "artwork-rights-holder-unknown"),
])
def test_bad_artwork_requests_are_refused(service, request_, code):
    with pytest.raises(Rejected) as exc:
        service.add_artwork(request_)
    assert exc.value.code == code


def test_examples_follow_the_chosen_artwork(service):
    art = service.add_artwork({"title": "Blue Hour", "consented_editions": 6, "new_artist_name": "Amina"})["artwork"]
    examples = service.examples(art["id"])
    valid, broken = examples["valid"], examples["invalid"]
    assert valid["artwork_id"] == broken["artwork_id"] == art["id"]
    assert valid["edition_count"] == 6  # kept within the consent
    artist = next(p for p in valid["parties"] if p["role"] == "artist")
    assert artist["id"] == "amina" and artist["wallet"] == "sim-wallet-amina"

    report = service.check_deal(valid)
    assert report["valid"] and report["warnings"] == [], report["errors"]
    report = service.check_deal(broken)
    assert errors(report) == {"shares-not-100"}
    assert {w["rule"] for w in report["warnings"]} == {"royalty-above-10"}


def test_examples_when_the_rights_holder_was_already_a_co_owner(service):
    art = service.add_artwork({"title": "Study", "consented_editions": 10, "rights_holder": "broker-c"})["artwork"]
    valid = service.examples(art["id"])["valid"]
    roles = {p["id"]: p["role"] for p in valid["parties"]}
    assert roles["broker-c"] == "artist" and roles["artist-a"] == "co-owner"
    assert service.check_deal(valid)["valid"]


def test_the_default_examples_are_the_sample_deals(service, sample_deal_data):
    valid = service.examples()["valid"]
    expected = {k: v for k, v in sample_deal_data.items() if k != "_notice"}
    assert valid == expected


def test_a_synthetic_artwork_can_get_its_own_deal_while_another_is_locked(service, deal):
    lock_deal(service, deal)  # aw-placeholder-001 now has an active deal
    art = service.add_artwork({"title": "Blue Hour", "consented_editions": 6, "new_artist_name": "Amina"})["artwork"]
    deal_id = lock_deal(service, service.examples(art["id"])["valid"])
    assert deal_id == "deal-2"


def test_unknown_artwork_examples(service):
    with pytest.raises(NotFound):
        service.examples("aw-nope")


def test_consent_records_cannot_be_edited(service):
    service.add_artwork({"title": "Blue Hour", "consented_editions": 6, "new_artist_name": "Amina"})
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        service.store.conn.execute("UPDATE synthetic_artworks SET consented_editions = 99")


def test_reset_removes_synthetic_artworks(service):
    art = service.add_artwork({"title": "Blue Hour", "consented_editions": 6, "new_artist_name": "Amina"})["artwork"]
    service.reset()
    assert art["id"] not in service.registry.artworks
    assert "aw-placeholder-001" in service.registry.artworks
