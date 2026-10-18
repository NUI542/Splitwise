"""Consent, versions, locking, timing and exactly-once sales."""
from __future__ import annotations

import sqlite3

import pytest

from agent import facts as F
from agent.engine import fact, number, quote
from agent.service import Conflict, Rejected
from conftest import lock_deal, wallet


def lock_errors(exc: pytest.ExceptionInfo) -> set[str]:
    return {e["rule"] for e in exc.value.report["errors"]}


def primary(deal_id, edition, event_id=None, **extra):
    return {"event_id": event_id or f"p{edition}", "deal_id": deal_id, "type": "primary",
            "edition": edition, "price": "15000.00", "buyer": wallet("collector-1"), **extra}


# --------------------------------------------------------------- consent

def test_lock_needs_every_approval(service, deal):
    saved = service.save_version(deal)
    service.approve(saved["deal_id"], 1, "artist-a")
    with pytest.raises(Rejected) as exc:
        service.lock(saved["deal_id"], 1)
    missing = {e["data"]["party"] for e in exc.value.report["errors"] if e["rule"] == "approval-missing"}
    assert missing == {"basix-market", "broker-c", "studio-d"}


def test_full_approval_locks(service, deal):
    saved = service.save_version(deal)
    for p in deal["parties"]:
        view = service.approve(saved["deal_id"], 1, p["id"])
    assert view["pending_approvals"] == []
    locked = service.lock(saved["deal_id"], 1)
    assert locked["version"] == 1 and locked["locked_at"]
    assert service.versions(saved["deal_id"])[0]["status"] == "active"


def test_a_change_needs_re_approval(service, deal):
    saved = service.save_version(deal)
    for p in deal["parties"]:
        service.approve(saved["deal_id"], 1, p["id"])
    deal["price"] = "16000.00"
    v2 = service.save_version(deal, saved["deal_id"])
    assert v2["version"] == 2
    service.approve(saved["deal_id"], 2, "artist-a")
    with pytest.raises(Rejected) as exc:
        service.lock(saved["deal_id"], 2)
    old = {e["data"]["party"] for e in exc.value.report["errors"] if e["rule"] == "approval-for-old-version"}
    assert old == {"basix-market", "broker-c", "studio-d"}


def test_saving_unchanged_terms_does_not_make_a_version(service, deal):
    saved = service.save_version(deal)
    again = service.save_version(deal, saved["deal_id"])
    assert again["version"] == 1 and again["unchanged"]


def test_invalid_deal_cannot_be_saved(service, deal):
    deal["shares"][0]["value"] = "70"
    with pytest.raises(Rejected) as exc:
        service.save_version(deal)
    assert "shares-not-100" in lock_errors(exc)


def test_approval_from_someone_not_in_the_deal_is_refused(service, deal):
    saved = service.save_version(deal)
    with pytest.raises(Rejected) as exc:
        service.approve(saved["deal_id"], 1, "collector-1")
    assert exc.value.code == "approval-from-non-party"


def test_only_the_newest_version_can_be_approved(service, deal):
    saved = service.save_version(deal)
    deal["price"] = "16000.00"
    service.save_version(deal, saved["deal_id"])
    with pytest.raises(Rejected) as exc:
        service.approve(saved["deal_id"], 1, "artist-a")
    assert exc.value.code == "version-not-latest"


def test_approving_twice_is_harmless(service, deal):
    saved = service.save_version(deal)
    service.approve(saved["deal_id"], 1, "artist-a")
    view = service.approve(saved["deal_id"], 1, "artist-a")
    assert [a["party_id"] for a in view["approvals"]] == ["artist-a"]


def test_a_version_locks_once(service, deal):
    deal_id = lock_deal(service, deal)
    with pytest.raises(Rejected) as exc:
        service.lock(deal_id, 1)
    assert "version-already-locked" in lock_errors(exc)


# The next three rules can't be broken through the API (the service stamps
# times and rejects outsiders), so they're checked on hand-written facts,
# as they would be on imported records.

def _lock_findings(engine, registry, deal, approvals, created_at=2000):
    terms = F.normalize_terms(deal)
    facts = (F.registry_facts(registry.data) + F.terms_facts(1, terms, created_at=created_at)
             + [fact("editions-sold", "0"), fact("latest-version", "1")]
             + [fact("approval", number(v), quote(p), number(t), quote(h)) for v, p, t, h in approvals])
    return {(f[2], dict(f[4]).get("party")) for f in engine.query_one(facts, "(collapse (lock-rule 1))")}


def test_rule_approval_before_version(engine, registry, deal):
    h = F.terms_hash(F.normalize_terms(deal))
    approvals = [(1, p["id"], 3000, h) for p in deal["parties"]]
    approvals[0] = (1, "artist-a", 1999, h)
    assert ("approval-before-version", "artist-a") in _lock_findings(engine, registry, deal, approvals)


def test_rule_approval_from_non_party(engine, registry, deal):
    h = F.terms_hash(F.normalize_terms(deal))
    approvals = [(1, p["id"], 3000, h) for p in deal["parties"]] + [(1, "collector-9", 3000, h)]
    assert ("approval-from-non-party", "collector-9") in _lock_findings(engine, registry, deal, approvals)


def test_rule_terms_changed_after_approval(engine, registry, deal):
    h = F.terms_hash(F.normalize_terms(deal))
    approvals = [(1, p["id"], 3000, h) for p in deal["parties"]]
    approvals[1] = (1, "basix-market", 3000, "hash-of-other-terms")
    assert ("terms-changed-after-approval", "basix-market") in _lock_findings(engine, registry, deal, approvals)


# -------------------------------------------------------- immutability

def test_locked_terms_cannot_be_edited_in_place(service, deal):
    deal_id = lock_deal(service, deal)
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        service.store.conn.execute(
            "UPDATE deal_versions SET terms_json = '{}' WHERE deal_id = ?", (deal_id,))


def test_tampered_terms_are_caught_at_sale_time(service, deal):
    deal_id = lock_deal(service, deal)
    conn = service.store.conn
    conn.execute("DROP TRIGGER deal_versions_no_update")
    conn.execute("UPDATE deal_versions SET terms_json = replace(terms_json, '1500000', '1') WHERE deal_id = ?",
                 (deal_id,))
    with pytest.raises(Rejected) as exc:
        service.record_sale(primary(deal_id, 1))
    assert "locked-terms-changed" in lock_errors(exc)


def test_ledger_is_append_only(service, locked):
    service.record_sale(primary(locked, 1))
    for sql in ("UPDATE sales SET price_minor = 1", "DELETE FROM payout_lines"):
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            service.store.conn.execute(sql)


# ----------------------------------------------------------------- time

def test_sale_before_the_lock_is_refused(service, deal):
    deal_id = lock_deal(service, deal)
    with pytest.raises(Rejected) as exc:
        service.record_sale(primary(deal_id, 1, timestamp="2026-01-01T00:00:00Z"))
    assert "sale-before-lock" in lock_errors(exc)


def test_sale_must_use_the_version_active_at_the_time(service, deal, clock):
    deal_id = lock_deal(service, deal)
    deal["price"] = "16000.00"
    service.save_version(deal, deal_id)
    for p in deal["parties"]:
        service.approve(deal_id, 2, p["id"])
    service.lock(deal_id, 2)
    with pytest.raises(Rejected) as exc:
        service.record_sale(primary(deal_id, 1, deal_version=1))
    assert "sale-version-not-active" in lock_errors(exc)
    sale = service.record_sale(primary(deal_id, 1, event_id="p1-v2", deal_version=2, price="16000.00"))
    assert sale["deal_version"] == 2


def test_sales_already_paid_keep_their_version(service, deal):
    deal_id = lock_deal(service, deal)
    first = service.record_sale(primary(deal_id, 1))
    deal["price"] = "16000.00"
    service.save_version(deal, deal_id)
    for p in deal["parties"]:
        service.approve(deal_id, 2, p["id"])
    service.lock(deal_id, 2)
    assert service.store.sale(first["sale_id"])["deal_version"] == 1
    assert service.list_sales(deal_id)[0]["lines"] == first["lines"]


def test_sale_without_a_locked_deal(service, deal):
    saved = service.save_version(deal)
    with pytest.raises(Rejected) as exc:
        service.record_sale(primary(saved["deal_id"], 1))
    assert "deal-not-locked" in lock_errors(exc)


# ----------------------------------------------------------- sale guards

def test_each_edition_has_one_primary_sale(service, locked):
    service.record_sale(primary(locked, 1))
    with pytest.raises(Rejected) as exc:
        service.record_sale(primary(locked, 1, event_id="again"))
    assert "edition-already-sold" in lock_errors(exc)


def test_edition_outside_the_count(service, locked):
    with pytest.raises(Rejected) as exc:
        service.record_sale(primary(locked, 11))
    assert "edition-out-of-range" in lock_errors(exc)


def test_resale_seller_must_hold_the_edition(service, locked):
    service.record_sale(primary(locked, 1))
    with pytest.raises(Rejected) as exc:
        service.record_sale({"event_id": "r1", "deal_id": locked, "type": "resale", "edition": 1,
                             "price": "20000.00", "seller": wallet("collector-2"),
                             "buyer": wallet("collector-3")})
    assert "seller-not-holder" in lock_errors(exc)


def test_resale_of_an_unsold_edition(service, locked):
    with pytest.raises(Rejected) as exc:
        service.record_sale({"event_id": "r1", "deal_id": locked, "type": "resale", "edition": 4,
                             "price": "20000.00", "seller": wallet("collector-2"),
                             "buyer": wallet("collector-3")})
    assert "resale-of-unsold-edition" in lock_errors(exc)


def test_primary_sale_must_come_from_the_mint(service, locked):
    with pytest.raises(Rejected) as exc:
        service.record_sale(primary(locked, 1, seller=wallet("collector-2")))
    assert "primary-seller-not-mint" in lock_errors(exc)


# ---------------------------------------------------------- exactly once

def test_replaying_an_event_never_pays_twice(service, locked):
    first = service.record_sale(primary(locked, 1))
    again = service.record_sale(primary(locked, 1))
    assert again["replayed"] and not first["replayed"]
    assert again["lines"] == first["lines"] and again["tx"] == first["tx"]
    assert len(service.list_sales(locked)) == 1
    assert len(service.chain.read_transfers(locked)) == 1


def test_reusing_an_event_id_for_a_different_sale_is_refused(service, locked):
    service.record_sale(primary(locked, 1))
    with pytest.raises(Conflict):
        service.record_sale(primary(locked, 2, event_id="p1"))
