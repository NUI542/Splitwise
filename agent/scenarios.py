"""Simulator scenarios behind POST /sim/{scenario}.

Sales on BASIX.MARKET go through the agent (record_sale), which pays them
out and settles them on the simulated chain. Activity elsewhere - a resale
on a marketplace that ignores royalties, or a gift - is written straight to
the simulated chain; the agent only learns about it by watching.

This module picks sensible defaults (which edition, which collector, what
price) so the demo needs one click per step. It makes no payout decisions.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .chain import mint_address
from .money import to_minor
from .service import DealService, NotFound, Rejected

SAMPLE_DEAL = Path(__file__).resolve().parent.parent / "data" / "sample_deal.json"
SCENARIOS = ("primary-sale", "resale-with-royalty", "resale-without-royalty", "resale-partial-royalty",
             "gift-transfer", "seed-locked-deal", "reset")


def run(service: DealService, name: str, params: dict[str, Any]) -> dict[str, Any]:
    if name == "reset":
        service.reset()
        return {"scenario": name, "note": "All deals, sales, flags and chain records were wiped."}
    if name == "seed-locked-deal":
        return _seed(service)
    if name not in SCENARIOS:
        raise NotFound(f"Unknown scenario {name}. Try one of: {', '.join(SCENARIOS)}.", "scenario-unknown")

    deal_id = params.get("deal_id") or _active_deal(service)
    version = service.store.version(deal_id, max(l["version"] for l in service.store.locks(deal_id)))
    terms = version["terms"]
    currency = terms["currency"]
    holders = _holders(service, deal_id)
    collectors = [service.registry.first_wallet(c["id"]) for c in service.registry.collectors()]

    def price(default_minor: int) -> int:
        if params.get("price") not in (None, ""):
            value = to_minor(params["price"], currency)
            if not isinstance(value, int):
                raise Rejected("The price isn't a number.", "field-unreadable")
            return value
        return default_minor

    if name == "primary-sale":
        edition = int(params.get("edition") or _next_unminted(holders, terms["edition_count"]))
        buyer = params.get("buyer") or collectors[(edition - 1) % len(collectors)]
        event = {"event_id": params.get("event_id") or _event_id(service, deal_id), "deal_id": deal_id,
                 "type": "primary", "edition": edition, "price_minor": price(terms["price_minor"]),
                 "currency": currency, "seller": mint_address(deal_id), "buyer": buyer,
                 "timestamp": params.get("timestamp")}
        return {"scenario": name, "sale": service.record_sale(event),
                "note": "Sold on BASIX.MARKET: the agent paid it out and settled it on the chain."}

    edition, holder = _pick_held(holders, params.get("edition"))
    buyer = params.get("buyer") or next(w for w in collectors if w != holder)

    if name == "resale-with-royalty":
        # Default: 20% above the primary price, plus a few cents so the split leaves a leftover.
        event = {"event_id": params.get("event_id") or _event_id(service, deal_id), "deal_id": deal_id,
                 "type": "resale", "edition": edition,
                 "price_minor": price(terms["price_minor"] * 6 // 5 + 57),
                 "currency": currency, "seller": holder, "buyer": buyer, "timestamp": params.get("timestamp")}
        return {"scenario": name, "sale": service.record_sale(event),
                "note": "Resold on BASIX.MARKET: the royalty was paid out by the deal."}

    amount = price(terms["price_minor"] * 3 // 2)
    ts = service.now()
    if name == "resale-without-royalty":
        payments = [(buyer, holder, amount)]
        note = "Resold on a marketplace that ignores royalties: the buyer paid the seller in full."
    elif name == "resale-partial-royalty":
        # params["paid"]: [{"party": "artist-a", "amount": "720.00"}] - what the other marketplace paid.
        paid = []
        for item in params.get("paid") or []:
            wallet = service.registry.first_wallet(item["party"]) or item["party"]
            paid.append((buyer, wallet, to_minor(item["amount"], currency)))
        payments = [(buyer, holder, amount - sum(p[2] for p in paid))] + paid
        note = "Resold elsewhere with only part of the royalty paid."
    else:  # gift-transfer
        payments = []
        note = "Moved to another wallet with no payment: a gift, or a sale settled off the chain."
    with service.store.transaction():
        transfer = service.chain.settle(deal_id, edition, holder, buyer, payments, currency, ts)
    return {"scenario": name, "note": note,
            "transfer": {"tx": transfer.tx, "edition": edition, "from": holder, "to": buyer,
                         "payments": [{"from": a, "to": b, "amount_minor": c} for a, b, c in payments]}}


def _seed(service: DealService) -> dict[str, Any]:
    """Create, approve and lock the sample deal (a shortcut for testing and the OmegaClaw demo)."""
    draft = json.loads(SAMPLE_DEAL.read_text(encoding="utf-8"))
    saved = service.save_version(draft)
    for party in draft["parties"]:
        service.approve(saved["deal_id"], saved["version"], party["id"])
    locked = service.lock(saved["deal_id"], saved["version"])
    return {"scenario": "seed-locked-deal", "deal_id": saved["deal_id"], "version": saved["version"],
            "locked_at": locked["locked_at"], "note": "The sample deal was saved, approved by every co-owner, and locked."}


def _active_deal(service: DealService) -> str:
    locked = [d for d in service.store.deal_ids() if service.store.locks(d)]
    if not locked:
        raise Rejected("Lock a deal first; sales need a locked deal.", "deal-not-locked")
    return locked[-1]


def _holders(service: DealService, deal_id: str) -> dict[int, str]:
    holders: dict[int, str] = {}
    for t in service.chain.read_transfers(deal_id):
        holders[t.edition] = t.to_wallet
    return holders


def _next_unminted(holders: dict[int, str], edition_count: int) -> int:
    for edition in range(1, int(edition_count) + 1):
        if edition not in holders:
            return edition
    raise Rejected("Every edition has been sold.", "editions-sold-out")


def _pick_held(holders: dict[int, str], edition: Any) -> tuple[int, str]:
    if edition not in (None, ""):
        edition = int(edition)
        if edition not in holders:
            raise Rejected(f"Edition {edition} hasn't been sold yet.", "resale-of-unsold-edition")
        return edition, holders[edition]
    if not holders:
        raise Rejected("No edition has been sold yet; simulate a primary sale first.", "resale-of-unsold-edition")
    edition = min(holders)
    return edition, holders[edition]


def _event_id(service: DealService, deal_id: str) -> str:
    return f"evt-{deal_id}-{len(service.store.sales(deal_id)) + 1:04d}"
