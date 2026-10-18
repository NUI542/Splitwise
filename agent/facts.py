"""Turns deals, approvals, sales and chain records into MeTTa facts.

This is plumbing only: it parses what was written (text to numbers, major
units to minor units) and states it as facts. It makes no judgement about
whether the values are acceptable; that is the rules' job.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable

from . import money
from .engine import fact, number, quote
from .money import Unreadable

TERM_FIELDS = ("artwork_id", "currency", "edition_count", "price", "royalty")


# ------------------------------------------------------------------ terms

def normalize_terms(draft: dict[str, Any]) -> dict[str, Any]:
    """Draft from the API -> canonical terms (minor units, basis points)."""
    currency = _text(draft.get("currency"))
    price_currency = _text(draft.get("price_currency")) or currency
    if draft.get("price_minor") is not None:
        price = money.to_number(draft.get("price_minor"))
    else:
        price = money.to_minor(draft.get("price"), price_currency)
    if draft.get("royalty_bps") is not None:
        royalty = money.to_number(draft.get("royalty_bps"))
    else:
        royalty = money.percent_to_bps(draft.get("royalty_percent"))

    parties = []
    for p in draft.get("parties") or []:
        role = (_text(p.get("role")) or "").lower()
        parties.append({
            "id": _text(p.get("id")) or "",
            "name": _text(p.get("name")) or "",
            "role": "artist" if role == "artist" else "co-owner",
            "wallet": _text(p.get("wallet")),
        })
    shares = []
    for s in draft.get("shares") or []:
        kind = (_text(s.get("kind")) or "percent").lower()
        if kind == "fixed":
            value = money.to_minor(s.get("value"), currency)
            shares.append({"party_id": _text(s.get("party_id")) or "", "kind": "fixed", "value": value})
        else:
            shares.append({"party_id": _text(s.get("party_id")) or "",
                           "kind": "bps", "value": money.percent_to_bps(s.get("value"))})
    return {
        "artwork_id": _text(draft.get("artwork_id")),
        "currency": currency,
        "edition_count": money.to_number(draft.get("edition_count")),
        "price_minor": price,
        "price_currency": price_currency,
        "royalty_bps": royalty,
        "parties": parties,
        "shares": shares,
    }


def terms_hash(terms: dict[str, Any]) -> str:
    canonical = json.dumps(_jsonable(terms), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def is_clean(terms: dict[str, Any]) -> bool:
    """True when every numeric term was readable (needed before storing a version)."""
    values = [terms["edition_count"], terms["price_minor"], terms["royalty_bps"]]
    values += [s["value"] for s in terms["shares"]]
    return all(isinstance(v, (int, float)) for v in values)


def terms_facts(v: int, terms: dict[str, Any], created_at: int | None = None) -> list[str]:
    out: list[str] = []
    V = number(v)
    if created_at is not None:
        out.append(fact("version-created", V, number(created_at)))
    _text_fact(out, V, "artwork_id", "deal-artwork", terms.get("artwork_id"))
    _text_fact(out, V, "currency", "deal-currency", terms.get("currency"))
    _number_fact(out, V, "edition_count", terms.get("edition_count"),
                 lambda n: fact("deal-edition-count", V, n))
    price_currency = terms.get("price_currency") or terms.get("currency") or ""
    _number_fact(out, V, "price", terms.get("price_minor"),
                 lambda n: fact("deal-price", V, n, quote(price_currency)))
    _number_fact(out, V, "royalty", terms.get("royalty_bps"),
                 lambda n: fact("deal-royalty-bps", V, n))
    for row, p in enumerate(terms.get("parties") or [], start=1):
        wallet = quote(p["wallet"]) if p.get("wallet") else "none"
        out.append(fact("deal-party", V, number(row), quote(p["id"]), quote(p["name"]),
                        p["role"], wallet))
    for row, s in enumerate(terms.get("shares") or [], start=1):
        value = s["value"]
        if isinstance(value, (int, float)):
            out.append(fact("deal-share", V, number(row), quote(s["party_id"]), s["kind"], number(value)))
        elif value is None:
            out.append(fact("missing", V, "shares"))
        else:
            out.append(fact("unreadable", V, "shares", quote(value.raw)))
    out.append(fact("deal-terms-hash", V, quote(terms_hash(terms))))
    return out


# --------------------------------------------------------------- context

def registry_facts(registry: dict[str, Any]) -> list[str]:
    out = [fact("currency", quote(code), number(exp)) for code, exp in money.CURRENCIES.items()]
    for party in registry.get("parties", []):
        for wallet in party.get("wallets", []):
            out.append(fact("wallet-owner", quote(wallet), quote(party["id"])))
    for art in registry.get("artworks", []):
        out.append(fact("artwork", quote(art["id"]), quote(art["rights_holder"]),
                        number(int(art["consented_editions"]))))
    return out


def approval_facts(approvals: Iterable[dict[str, Any]]) -> list[str]:
    return [fact("approval", number(a["version"]), quote(a["party_id"]),
                 number(a["approved_at"]), quote(a["terms_hash"])) for a in approvals]


def lock_facts(locks: Iterable[dict[str, Any]]) -> list[str]:
    return [fact("locked", number(l["version"]), number(l["locked_at"]), quote(l["terms_hash"]))
            for l in locks]


def sale_fact(sale: dict[str, Any]) -> str:
    named = sale.get("deal_version")
    return fact("sale", quote(sale["event_id"]), sale["type"], number(sale["edition"]),
                number(sale["price_minor"]), quote(sale["currency"]), quote(sale["seller"]),
                quote(sale["buyer"]), number(sale["ts"]),
                number(named) if named is not None else "none")


def chain_facts(transfers: Iterable[Any], payments: Iterable[Any]) -> list[str]:
    out = [fact("transfer", quote(t.tx), number(t.edition), quote(t.from_wallet),
                quote(t.to_wallet), number(t.ts), number(t.seq)) for t in transfers]
    out += [fact("payment", quote(p.tx), quote(p.from_wallet), quote(p.to_wallet),
                 number(p.amount_minor), quote(p.currency)) for p in payments]
    return out


def ledger_facts(sales: Iterable[dict[str, Any]]) -> list[str]:
    return [fact("ledger-sale", quote(s["sale_id"]), quote(s["tx"]), number(s["edition"]),
                 s["type"], number(s["price_minor"]), number(s["deal_version"])) for s in sales]


# --------------------------------------------------------------- helpers

def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _text_fact(out: list[str], V: str, field: str, name: str, value: str | None) -> None:
    if value is None:
        out.append(fact("missing", V, field))
    else:
        out.append(fact(name, V, quote(value)))


def _number_fact(out: list[str], V: str, field: str, value: Any, make) -> None:
    if value is None:
        out.append(fact("missing", V, field))
    elif isinstance(value, Unreadable):
        out.append(fact("unreadable", V, field, quote(value.raw)))
    else:
        out.append(make(number(value)))


def _jsonable(value: Any) -> Any:
    if isinstance(value, Unreadable):
        return {"unreadable": value.raw}
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    return value


def jsonable_terms(terms: dict[str, Any]) -> dict[str, Any]:
    return _jsonable(terms)
