"""Plain-language details for each finding, filled in from the values the
rules returned. The rule statements themselves live in deal_schema.metta."""
from __future__ import annotations

from typing import Any, Callable

from .money import format_bps, format_minor
from .registry import Registry

FIELD_LABELS = {
    "artwork_id": "artwork", "currency": "currency", "edition_count": "edition count",
    "price": "price", "royalty": "royalty", "shares": "shares", "parties": "co-owners",
}


def _fmt_time(ts: Any) -> str:
    from datetime import datetime, timezone
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    except (TypeError, ValueError, OverflowError):
        return str(ts)


def detail(rule: str, data: dict[str, Any], registry: Registry, currency: str, field_label: str = "term") -> str:
    def name(x: Any) -> str:
        if x in (None, ""):
            return "A co-owner with no ID"
        return f"{registry.name(x)} ({x})" if x in registry.parties else str(x)

    def money(x: Any) -> str:
        return format_minor(int(x), currency) if isinstance(x, (int, float)) else str(x)

    def pct(x: Any) -> str:
        return format_bps(x) if isinstance(x, (int, float)) else str(x)

    d = data
    templates: dict[str, Callable[[], str]] = {
        "field-missing": lambda: f"The {field_label} has no value yet.",
        "field-unreadable": lambda: f"The {field_label} \"{d.get('raw')}\" isn't a number.",
        "party-duplicate-id": lambda: f"{name(d['party'])} is listed on rows {', '.join(map(str, d['rows']))}.",
        "party-duplicate-wallet": lambda: (
            f"{name(d['parties'][0])} and {name(d['parties'][1])} both use wallet {d['wallet']}."),
        "party-duplicate-name": lambda: (
            f"\"{d['name']}\" appears under two IDs: {d['parties'][0]} and {d['parties'][1]}."),
        "artist-missing": lambda: "No co-owner is marked as the artist.",
        "artist-multiple": lambda: f"{len(d['artists'])} co-owners are marked as the artist: "
                                   + ", ".join(name(a) for a in d["artists"]) + ".",
        "share-without-party": lambda: f"Row {d['row']} gives a share to {d['party']}, who isn't a co-owner.",
        "party-without-share": lambda: f"{name(d['party'])} is a co-owner but has no share.",
        "share-duplicate": lambda: f"{name(d['party'])} has shares on rows {', '.join(map(str, d['rows']))}.",
        "wallet-missing": lambda: f"{name(d['party'])} has no payout wallet.",
        "wallet-owned-by-other": lambda: (
            f"Wallet {d['wallet']} is registered to {name(d['owner'])}, not {name(d['party'])}."),
        "wallet-unregistered": lambda: f"Wallet {d['wallet']} for {name(d['party'])} isn't in the registry.",
        "shares-not-100": lambda: f"The shares add up to {pct(d['total-bps'])}, not 100.00%.",
        "share-not-positive": lambda: f"{name(d['party'])} has a share of {d['value']}.",
        "share-not-whole-bps": lambda: f"{name(d['party'])}'s share of {d['bps'] / 100}% is finer than 0.01%.",
        "share-fixed-amount": lambda: (
            f"{name(d['party'])} has a fixed amount ({money(d['amount-minor'])}) instead of a percentage."),
        "share-mixed-forms": lambda: (
            f"{name(d['party'])} has a fixed amount ({money(d['amount-minor'])}) while the others have percentages."),
        "edition-count-invalid": lambda: f"The edition count is {d['edition-count']}.",
        "editions-sold-exceeds-count": lambda: (
            f"{d['sold']} editions are already sold, but the count is {d['edition-count']}."),
        "price-not-positive": lambda: f"The price is {money(d['price-minor'])}.",
        "price-out-of-range": lambda: f"{money(d['price-minor'])} is above the limit of {money(d['max-minor'])}.",
        "price-currency-mismatch": lambda: (
            f"The price is in {d['price-currency']} but the deal is in {d['deal-currency']}."),
        "currency-unknown": lambda: f"{d['currency']} isn't a supported currency.",
        "price-too-small-to-split": lambda: (
            f"{pct(d['bps'])} of {money(d['price-minor'])} rounds down to {money(0)} for {name(d['party'])}."),
        "royalty-out-of-range": lambda: f"The royalty is {pct(d['bps'])}.",
        "royalty-not-whole-bps": lambda: f"A royalty of {d['bps'] / 100}% is finer than 0.01%.",
        "royalty-above-10": lambda: f"The royalty is {pct(d['bps'])}.",
        "royalty-too-small": lambda: (
            f"At a resale price of {money(d['reference-price-minor'])} the royalty is "
            f"{money(d['royalty-minor'])}, and every co-owner except the artist would get {money(0)}."),
        "artwork-unknown": lambda: f"There is no recorded artwork {d['artwork']}.",
        "artwork-has-other-active-deal": lambda: f"{d['artwork']} is already governed by {d['other-deal']}.",
        "artist-not-rights-holder": lambda: (
            f"The artwork's rights holder is {name(d['rights-holder'])}, not {name(d['artist'])}."),
        "editions-exceed-consent": lambda: (
            f"The rights holder consented to {d['consented']} editions; the deal has {d['edition-count']}."),
        "approval-missing": lambda: f"{name(d['party'])} hasn't approved version {d['version']}.",
        "approval-for-old-version": lambda: (
            f"{name(d['party'])} approved version {d['approved-version']}, not version {d['version']}."),
        "terms-changed-after-approval": lambda: (
            f"{name(d['party'])} approved different terms than version {d['version']} now has."),
        "approval-from-non-party": lambda: f"{d['party']} approved version {d['version']} but isn't a co-owner.",
        "approval-before-version": lambda: (
            f"{name(d['party'])}'s approval is dated {_fmt_time(d['approved-at'])}, before the version was "
            f"created at {_fmt_time(d['version-created-at'])}."),
        "version-already-locked": lambda: f"Version {d['version']} was locked at {_fmt_time(d['locked-at'])}.",
        "version-not-latest": lambda: f"Version {d['version']} isn't the newest (version {d['latest']} is).",
        "deal-not-locked": lambda: "The deal has no locked version yet.",
        "sale-before-lock": lambda: (
            f"The sale is dated {_fmt_time(d['sale-at'])}; the deal was first locked at "
            f"{_fmt_time(d['first-locked-at'])}."),
        "sale-version-not-active": lambda: (
            f"The sale names version {d['named-version']}, but version {d['active-version']} was active."),
        "locked-terms-changed": lambda: f"The stored terms of version {d['version']} no longer match the lock.",
        "edition-out-of-range": lambda: f"Edition {d['edition']} is outside 1 to {d['edition-count']}.",
        "edition-already-sold": lambda: f"Edition {d['edition']} already belongs to {name(d['holder'])}.",
        "resale-of-unsold-edition": lambda: f"Edition {d['edition']} has never been sold.",
        "seller-not-holder": lambda: (
            f"Edition {d['edition']} is held by {registry.name(d['holder'])}, not {registry.name(d['seller'])}."),
        "primary-seller-not-mint": lambda: f"A primary sale must come from {d['mint']}, not {d['seller']}.",
        "sale-price-invalid": lambda: f"The sale price is {money(d['price-minor'])}.",
        "sale-currency-mismatch": lambda: (
            f"The sale is in {d['sale-currency']} but the deal is in {d['deal-currency']}."),
    }
    make = templates.get(rule)
    if make is None:
        return ", ".join(f"{k}: {v}" for k, v in d.items())
    try:
        return make()
    except (KeyError, IndexError, TypeError):
        return ", ".join(f"{k}: {v}" for k, v in d.items())
