"""The service layer: the agent's three jobs, backed by storage and the chain.

  1. check_deal / save_version / approve / lock   - check the deal, then lock it
  2. record_sale / explain                        - pay out by the deal
  3. scan / flags                                 - watch that the deal is honoured

Every decision is made by the MeTTa rules. This layer gathers the facts,
asks the rules, re-checks the money independently, and stores the result.
"""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from typing import Any, Callable

from . import facts as F
from .chain import mint_address
from .chain.simulator import SimulatedChain
from .engine import Engine, EngineError, fact, number, pairs, quote
from .explain import explain_flag, explain_line, normalize_steps, step_rows
from .messages import FIELD_LABELS, detail
from .money import format_bps, format_minor, to_minor, to_number
from .registry import Registry
from .store import Store

FLAGGED = ("SALE_ROYALTY_MISSING", "TRANSFER_UNVERIFIED")
FLAG_STATUSES = ("OPEN", "RESOLVED", "DISMISSED")
FIELD_ORDER = ["artwork_id", "currency", "edition_count", "price", "royalty", "parties", "shares",
               "approvals", "version", "sale"]


class ServiceError(Exception):
    status = 400

    def __init__(self, message: str, code: str, report: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.report = report

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"error": self.code, "message": self.message}
        if self.report is not None:
            out["report"] = self.report
        return out


class NotFound(ServiceError):
    status = 404


class Rejected(ServiceError):
    """The agent's rules (or a basic input check) refused the request."""
    status = 422


class Conflict(ServiceError):
    status = 409


def iso(ts: int | None) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat().replace("+00:00", "Z")


def parse_time(value: Any, default: int) -> int:
    if value is None or value == "":
        return default
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return int(value)
    text = str(value).strip()
    if text.isdigit():
        return int(text)
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise Rejected(f"'{value}' isn't a timestamp.", "timestamp-unreadable") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


class DealService:
    def __init__(self, store: Store, engine: Engine, registry: Registry,
                 clock: Callable[[], float] | None = None) -> None:
        self.store = store
        self.chain = SimulatedChain(store.conn)
        self.engine = engine
        self.registry = registry
        self.clock = clock or time.time
        self.docs = engine.rule_docs()

    def now(self) -> int:
        return int(self.clock())

    def reset(self) -> None:
        self.store.reset()
        self.chain = SimulatedChain(self.store.conn)

    # ============================================================ job 1

    def check_deal(self, draft: dict[str, Any], deal_id: str | None = None) -> dict[str, Any]:
        """Live check of a draft. Nothing is stored."""
        if deal_id and not self.store.deal_exists(deal_id):
            raise NotFound(f"There is no deal {deal_id}.", "deal-not-found")
        terms = F.normalize_terms(draft)
        version = self.store.latest_version(deal_id) + 1 if deal_id else 1
        facts = self._deal_context(deal_id) + F.terms_facts(version, terms, created_at=self.now())
        findings = self.engine.query_one(facts, f"(collapse (draft-rule {version}))")
        report = self._report(findings, terms.get("currency") or "KES")
        report["version"] = version
        report["terms"] = F.jsonable_terms(terms)
        report["terms_hash"] = F.terms_hash(terms)
        report["facts"] = facts
        report["summary"] = self._summary(facts, version, terms) if report["valid"] else None
        return report

    def save_version(self, draft: dict[str, Any], deal_id: str | None = None) -> dict[str, Any]:
        """Store a checked draft as the deal's next version, ready for approval."""
        report = self.check_deal(draft, deal_id)
        terms = F.normalize_terms(draft)
        if not report["valid"] or not F.is_clean(terms):
            raise Rejected("The deal has errors. Fix them before saving a version.", "deal-invalid", report)
        now = self.now()
        terms_hash = F.terms_hash(terms)
        with self.store.transaction() as conn:
            if deal_id is None:
                deal_id = self.store.new_deal_id(conn, now)
            latest = self.store.version(deal_id, self.store.latest_version(deal_id))
            if latest and latest["terms_hash"] == terms_hash:
                return {"deal_id": deal_id, "version": latest["version"], "terms_hash": terms_hash,
                        "created_at": iso(latest["created_at"]), "unchanged": True, "check": report}
            version = self.store.add_version(conn, deal_id, F.jsonable_terms(terms), terms_hash, now)
        return {"deal_id": deal_id, "version": version, "terms_hash": terms_hash,
                "created_at": iso(now), "unchanged": False, "check": report}

    def approve(self, deal_id: str, version: int, party_id: str) -> dict[str, Any]:
        """Record one co-owner's in-app approval of one exact version."""
        ver = self._version_or_404(deal_id, version)
        if version != self.store.latest_version(deal_id):
            raise Rejected(self._statement("version-not-latest"), "version-not-latest")
        if any(l["version"] == version for l in self.store.locks(deal_id)):
            raise Rejected(self._statement("version-already-locked"), "version-already-locked")
        party = next((p for p in ver["terms"]["parties"] if p["id"] == party_id), None)
        if party is None:
            raise Rejected(f"{party_id}: {self._statement('approval-from-non-party')}", "approval-from-non-party")
        existing = [a for a in self.store.approvals(deal_id)
                    if a["version"] == version and a["party_id"] == party_id]
        if not existing:
            with self.store.transaction() as conn:
                self.store.add_approval(conn, deal_id, version, party_id, party["name"],
                                        ver["terms_hash"], self.now())
        return self.version_view(deal_id, version)

    def lock(self, deal_id: str, version: int) -> dict[str, Any]:
        """Run the lock-stage rules and, if they all hold, lock the version."""
        ver = self._version_or_404(deal_id, version)
        terms = ver["terms"]
        facts = (self._deal_context(deal_id)
                 + F.terms_facts(version, terms, created_at=ver["created_at"])
                 + F.approval_facts(self.store.approvals(deal_id))
                 + F.lock_facts(self.store.locks(deal_id))
                 + [fact("latest-version", number(self.store.latest_version(deal_id)))])
        findings = self.engine.query_one(facts, f"(collapse (lock-rule {version}))")
        report = self._report(findings, terms.get("currency") or "KES")
        report["facts"] = facts
        if not report["valid"]:
            raise Rejected(f"Version {version} can't be locked yet.", "lock-refused", report)
        now = self.now()
        with self.store.transaction() as conn:
            self.store.add_lock(conn, deal_id, version, ver["terms_hash"], now)
        return {"deal_id": deal_id, "version": version, "locked_at": iso(now),
                "terms_hash": ver["terms_hash"], "check": report}

    def versions(self, deal_id: str) -> list[dict[str, Any]]:
        if not self.store.deal_exists(deal_id):
            raise NotFound(f"There is no deal {deal_id}.", "deal-not-found")
        return [self.version_view(deal_id, v["version"]) for v in self.store.versions(deal_id)]

    def version_view(self, deal_id: str, version: int) -> dict[str, Any]:
        ver = self._version_or_404(deal_id, version)
        locks = {l["version"]: l for l in self.store.locks(deal_id)}
        active = max(locks) if locks else None
        if version in locks:
            status = "active" if version == active else "superseded"
        elif active is not None and version < active:
            status = "never locked"
        else:
            status = "draft"
        terms = ver["terms"]
        approvals = [a for a in self.store.approvals(deal_id) if a["version"] == version]
        approved = {a["party_id"] for a in approvals}
        return {
            "deal_id": deal_id,
            "version": version,
            "status": status,
            "terms": terms,
            "terms_hash": ver["terms_hash"],
            "created_at": iso(ver["created_at"]),
            "locked_at": iso(locks[version]["locked_at"]) if version in locks else None,
            "approvals": [{"party_id": a["party_id"], "party_name": a["party_name"],
                           "approved_at": iso(a["approved_at"])} for a in approvals],
            "pending_approvals": [p["id"] for p in terms["parties"] if p["id"] not in approved],
            "display": self._terms_display(terms),
            "draft": F.terms_to_draft(terms),
        }

    def list_deals(self) -> list[dict[str, Any]]:
        out = []
        for deal_id in self.store.deal_ids():
            versions = self.store.versions(deal_id)
            locks = self.store.locks(deal_id)
            latest = versions[-1]
            art = self.registry.artworks.get(latest["terms"].get("artwork_id"), {})
            out.append({
                "deal_id": deal_id,
                "latest_version": latest["version"],
                "active_version": max(l["version"] for l in locks) if locks else None,
                "artwork_id": latest["terms"].get("artwork_id"),
                "artwork_title": art.get("title"),
                "mint_address": mint_address(deal_id),
            })
        return out

    # ============================================================ job 2

    def record_sale(self, event: dict[str, Any]) -> dict[str, Any]:
        """Check a sale against the deal, pay it out, settle it, and append it to the ledger."""
        deal_id = event.get("deal_id")
        if not deal_id or not self.store.deal_exists(deal_id):
            raise NotFound(f"There is no deal {deal_id}.", "deal-not-found")
        sale = self._normalize_sale(deal_id, event)
        # The event's own content identifies it. A timestamp the client left out
        # defaults to "now" and must not make a replay look like a new event.
        basis = {"deal_id": deal_id, **sale}
        if event.get("timestamp") in (None, ""):
            basis.pop("ts")
        payload_hash = hashlib.sha256(json.dumps(basis, sort_keys=True).encode("utf-8")).hexdigest()

        existing = self.store.sale(sale["event_id"])
        if existing:
            if existing["payload_hash"] == payload_hash:
                return self._sale_view(existing, replayed=True)
            raise Conflict(f"Event {sale['event_id']} was already processed with different details; "
                           "an event ID is processed exactly once.", "event-id-reused")

        facts = self._sale_facts(deal_id) + [F.sale_fact(sale)]
        findings = self.engine.query_one(facts, f"(collapse (sale-rule {quote(sale['event_id'])}))")
        currency = sale["currency"]
        report = self._report(findings, currency)
        if not report["valid"]:
            report["facts"] = facts
            raise Rejected("The agent refused this sale.", "sale-refused", report)

        result = self.engine.query_one(facts, f"(payout {quote(sale['event_id'])})")
        if not (isinstance(result, list) and result and result[0] == "payout-result"):
            raise EngineError(f"unexpected payout result: {result!r}")
        _, version, sale_type, raw_lines, raw_steps = result
        lines = [{"party": l[1], "role": str(l[2]), "wallet": l[3], "amount_minor": l[4]} for l in raw_lines]
        lines = self._order_lines(lines, version, deal_id)
        steps = normalize_steps(raw_steps)
        self._verify_payout(sale, sale_type, lines, steps)

        ver = self.store.version(deal_id, version)
        now = self.now()
        with self.store.transaction() as conn:
            transfer = self.chain.settle(
                deal_id, sale["edition"], sale["seller"], sale["buyer"],
                [(sale["buyer"], l["wallet"], l["amount_minor"]) for l in lines], currency, sale["ts"])
            record = {
                "sale_id": sale["event_id"], "payload_hash": payload_hash, "deal_id": deal_id,
                "deal_version": version, "terms_hash": ver["terms_hash"], "type": str(sale_type),
                "edition": sale["edition"], "price_minor": sale["price_minor"], "currency": currency,
                "seller": sale["seller"], "buyer": sale["buyer"], "sale_ts": sale["ts"], "tx": transfer.tx,
            }
            trace = {"version": version, "type": str(sale_type), "steps": steps}
            self.store.add_sale(conn, record, lines, trace, now)
        return self._sale_view(self.store.sale(sale["event_id"]), replayed=False)

    def list_sales(self, deal_id: str | None = None) -> list[dict[str, Any]]:
        return [self._sale_view(s) for s in self.store.sales(deal_id)]

    def explain(self, sale_id: str, party: str | None = None) -> dict[str, Any]:
        """Why did <party> get <amount> for <sale>? Answered from the stored trace."""
        sale = self.store.sale(sale_id)
        if sale is None:
            raise NotFound(f"There is no sale {sale_id}.", "sale-not-found")
        lines = sale["lines"]
        if party:
            lines = [l for l in lines if party in (l["party"], l["wallet"])]
            if not lines:
                raise NotFound(f"{party} received nothing from sale {sale_id}.", "party-not-in-sale")
        return {
            "sale_id": sale_id,
            "party": party,
            "deal_id": sale["deal_id"],
            "deal_version": sale["deal_version"],
            "lines": [self._line_view(l, sale["currency"]) for l in lines],
            "trace": {"version": sale["trace"]["version"], "type": sale["trace"]["type"],
                      "steps": step_rows(sale["trace"]["steps"], sale["currency"], self.registry, self.docs)},
            "explanation": "\n\n".join(explain_line(sale, l, self.registry) for l in lines),
        }

    # ============================================================ job 3

    def scan(self, deal_id: str | None = None) -> list[dict[str, Any]]:
        """Classify every transfer on the chain and raise flags for the ones that need a look."""
        deal_ids = [deal_id] if deal_id else [d for d in self.store.deal_ids() if self.store.locks(d)]
        results: list[dict[str, Any]] = []
        for d in deal_ids:
            transfers = self.chain.read_transfers(d)
            if not transfers:
                continue
            payments = self.chain.read_payments([t.tx for t in transfers])
            facts = (self._sale_facts(d, transfers=transfers)
                     + F.chain_facts([], payments)
                     + F.ledger_facts(self.store.sales(d)))
            classified = self.engine.query_one(facts, "(classify-all)")
            by_tx = {t.tx: t for t in transfers}
            currency = self._deal_currency(d)
            for item in classified:
                row = self._watch_row(d, item, currency)
                row["seq"] = by_tx[row["tx"]].seq
                row["at"] = iso(by_tx[row["tx"]].ts)
                if row["classification"] in FLAGGED:
                    flag = self.store.flag_for_tx(row["tx"])
                    if flag is None:
                        with self.store.transaction() as conn:
                            self.store.add_flag(conn, {**row, "flag_id": f"flag-{row['tx']}",
                                                       "trace": row["steps"]}, self.now())
                        flag = self.store.flag_for_tx(row["tx"])
                    row["flag_id"] = flag["flag_id"]
                    row["status"] = flag["status"]
                else:
                    row["flag_id"] = None
                    row["status"] = None
                results.append(row)
        results.sort(key=lambda r: (r["deal_id"], r["seq"]))
        return results

    def list_flags(self, status: str | None = None) -> list[dict[str, Any]]:
        return [self._flag_view(f) for f in self.store.flags(status)]

    def update_flag(self, flag_id: str, status: str, reason: str) -> dict[str, Any]:
        flag = self.store.flag(flag_id)
        if flag is None:
            raise NotFound(f"There is no flag {flag_id}.", "flag-not-found")
        status = (status or "").upper()
        if status not in FLAG_STATUSES:
            raise Rejected(f"Status must be one of {', '.join(FLAG_STATUSES)}.", "flag-status-unknown")
        if status == flag["status"]:
            raise Rejected(f"The flag is already {status}.", "flag-status-unchanged")
        if not (reason or "").strip():
            raise Rejected("Give a reason; every change to a flag is recorded.", "flag-reason-missing")
        with self.store.transaction() as conn:
            self.store.set_flag_status(conn, flag_id, status, reason.strip(), self.now())
        return self._flag_view(self.store.flag(flag_id))

    # ===================================================== fact building

    def _deal_context(self, deal_id: str | None) -> list[str]:
        out = F.registry_facts(self.registry.data)
        for other, artwork in self.store.locked_artworks():
            if other != deal_id and artwork:
                out.append(fact("other-active-deal", quote(other), quote(artwork)))
        sold = self.store.primary_sales_count(deal_id) if deal_id else 0
        out.append(fact("editions-sold", number(sold)))
        return out

    def _sale_facts(self, deal_id: str, transfers=None) -> list[str]:
        """Locked versions, their locks, the mint, the registry and the edition transfers."""
        out = F.registry_facts(self.registry.data)
        out.append(fact("deal-id", quote(deal_id)))
        out.append(fact("mint-address", quote(mint_address(deal_id))))
        locks = self.store.locks(deal_id)
        for lock in locks:
            ver = self.store.version(deal_id, lock["version"])
            out += F.terms_facts(lock["version"], ver["terms"], created_at=ver["created_at"])
        out += F.lock_facts(locks)
        if transfers is None:
            transfers = self.chain.read_transfers(deal_id)
        out += F.chain_facts(transfers, [])
        return out

    def _normalize_sale(self, deal_id: str, event: dict[str, Any]) -> dict[str, Any]:
        event_id = str(event.get("event_id") or "").strip()
        if not event_id:
            raise Rejected("A sale needs an event ID; it is what makes replays safe.", "event-id-missing")
        sale_type = str(event.get("type") or "").strip().lower()
        if sale_type not in ("primary", "resale"):
            raise Rejected("A sale's type is primary or resale.", "sale-type-unknown")
        currency = (event.get("currency") or self._deal_currency(deal_id) or "KES").strip()
        if event.get("price_minor") is not None:
            price = to_number(event.get("price_minor"))
        else:
            price = to_minor(event.get("price"), currency)
        edition = to_number(event.get("edition"))
        for label, value in (("price", price), ("edition", edition)):
            if not isinstance(value, (int, float)):
                raise Rejected(f"The sale's {label} isn't a number.", "field-unreadable")
        seller = str(event.get("seller") or (mint_address(deal_id) if sale_type == "primary" else "")).strip()
        buyer = str(event.get("buyer") or "").strip()
        if not seller or not buyer:
            raise Rejected("A sale needs a seller and a buyer wallet.", "party-missing")
        named = event.get("deal_version")
        named = to_number(named) if named not in (None, "") else None
        if named is not None and not isinstance(named, int):
            raise Rejected("The deal version isn't a whole number.", "field-unreadable")
        return {"event_id": event_id, "type": sale_type, "edition": edition, "price_minor": price,
                "currency": currency, "seller": seller, "buyer": buyer,
                "ts": parse_time(event.get("timestamp"), self.now()), "deal_version": named}

    # ============================================================ checks

    def _verify_payout(self, sale: dict[str, Any], sale_type: str, lines: list[dict[str, Any]],
                       steps: list[dict[str, Any]]) -> None:
        """An independent check of the rules' arithmetic before anything is written."""
        price = sale["price_minor"]
        for line in lines:
            if not isinstance(line["amount_minor"], int) or line["amount_minor"] < 0:
                raise EngineError(f"payout line is not a whole, non-negative amount: {line}")
        total = sum(l["amount_minor"] for l in lines)
        if total != price:
            raise EngineError(f"payout lines add up to {total}, not the price {price}")
        if sale_type == "resale":
            royalty = next(s for s in steps if s["rule"] == "royalty-amount")["values"]["result-minor"]
            to_owners = sum(l["amount_minor"] for l in lines if l["role"] != "seller")
            seller = [l for l in lines if l["role"] == "seller"]
            if to_owners != royalty or len(seller) != 1 or seller[0]["amount_minor"] != price - royalty:
                raise EngineError("resale lines don't match the royalty step")

    # ============================================================= views

    def _report(self, findings: list[Any], currency: str) -> dict[str, Any]:
        seen = set()
        errors, warnings = [], []
        for item in findings:
            if not (isinstance(item, list) and len(item) == 5 and item[0] == "violation"):
                raise EngineError(f"unexpected finding: {item!r}")
            _, severity, rule, field, data = item
            data = pairs(data)
            key = (str(severity), str(rule), str(field), json.dumps(data, sort_keys=True, default=str))
            if key in seen:
                continue
            seen.add(key)
            entry = {
                "rule": str(rule),
                "severity": str(severity),
                "field": str(field),
                "field_label": FIELD_LABELS.get(str(field), str(field)),
                "statement": self._statement(str(rule)),
                "detail": detail(str(rule), data, self.registry, currency,
                                 FIELD_LABELS.get(str(field), str(field))),
                "data": data,
            }
            (errors if severity == "error" else warnings).append(entry)
        order = {f: i for i, f in enumerate(FIELD_ORDER)}
        sort_key = lambda e: (order.get(e["field"], 99), e["rule"], e["detail"])  # noqa: E731
        return {"valid": not errors, "errors": sorted(errors, key=sort_key),
                "warnings": sorted(warnings, key=sort_key)}

    def _summary(self, facts: list[str], version: int, terms: dict[str, Any]) -> dict[str, Any]:
        preview = self.engine.query_one(facts, f"(preview-split {version})")
        _, price, raw_lines, leftover_step = preview
        cur = terms["currency"]
        m = lambda x: format_minor(int(x), cur)  # noqa: E731
        shares = {s["party_id"]: s["value"] for s in terms["shares"]}
        names = {p["id"]: p["name"] for p in terms["parties"]}
        lines = [{"party": l[1], "name": names.get(l[1], l[1]), "role": str(l[2]),
                  "share_bps": shares.get(l[1]), "share_display": format_bps(shares.get(l[1], 0)),
                  "amount_minor": l[4], "amount_display": m(l[4])}
                 for l in raw_lines]
        order = {p["id"]: i for i, p in enumerate(terms["parties"])}
        lines.sort(key=lambda l: order.get(l["party"], 99))
        leftover = pairs(leftover_step[2])
        art = self.registry.artworks.get(terms["artwork_id"], {})
        artist = next(p for p in terms["parties"] if p["role"] == "artist")
        split_text = "; ".join(f"{l['name']} {format_bps(l['share_bps'])} = {l['amount_display']}" for l in lines)
        text = [
            f"{terms['edition_count']} digital editions of {art.get('title', terms['artwork_id'])}, "
            f"each sold at {m(price)}.",
            f"Each primary sale is split by share: {split_text}.",
            f"Each resale pays a {format_bps(terms['royalty_bps'])} royalty, split in the same proportions; "
            "the seller keeps the rest. BASIX.MARKET charges no separate resale fee.",
            f"Every share is rounded down to the cent, and any leftover goes to {artist['name']} "
            f"(at this price the leftover is {m(leftover['leftover-minor'])}).",
            f"All {len(terms['parties'])} co-owners must approve this exact version before it can be locked.",
        ]
        return {"text": text, "price_minor": price, "lines": lines}

    def _terms_display(self, terms: dict[str, Any]) -> dict[str, Any]:
        cur = terms.get("currency") or "KES"
        return {
            "price": format_minor(terms["price_minor"], cur) if isinstance(terms.get("price_minor"), int) else None,
            "royalty": format_bps(terms["royalty_bps"]) if isinstance(terms.get("royalty_bps"), (int, float)) else None,
            "shares": {s["party_id"]: format_bps(s["value"]) for s in terms.get("shares", [])
                       if s["kind"] == "bps" and isinstance(s["value"], (int, float))},
            "artwork_title": self.registry.artworks.get(terms.get("artwork_id"), {}).get("title"),
        }

    def _order_lines(self, lines: list[dict[str, Any]], version: int, deal_id: str) -> list[dict[str, Any]]:
        parties = self.store.version(deal_id, version)["terms"]["parties"]
        order = {p["id"]: i for i, p in enumerate(parties)}
        return sorted(lines, key=lambda l: (0 if l["role"] == "seller" else 1, order.get(l["party"], 99)))

    def _line_view(self, line: dict[str, Any], currency: str) -> dict[str, Any]:
        return {"party": line["party"], "name": self.registry.name(line["party"]), "role": line["role"],
                "wallet": line["wallet"], "amount_minor": line["amount_minor"],
                "amount_display": format_minor(line["amount_minor"], currency)}

    def _sale_view(self, sale: dict[str, Any], replayed: bool | None = None) -> dict[str, Any]:
        cur = sale["currency"]
        view = {
            "sale_id": sale["sale_id"],
            "deal_id": sale["deal_id"],
            "deal_version": sale["deal_version"],
            "type": sale["type"],
            "edition": sale["edition"],
            "price_minor": sale["price_minor"],
            "price_display": format_minor(sale["price_minor"], cur),
            "currency": cur,
            "seller": sale["seller"],
            "seller_name": self.registry.name(sale["seller"]),
            "buyer": sale["buyer"],
            "buyer_name": self.registry.name(sale["buyer"]),
            "sale_at": iso(sale["sale_ts"]),
            "tx": sale["tx"],
            "lines": [self._line_view(l, cur) for l in sale["lines"]],
            "trace": sale["trace"],
        }
        if replayed is not None:
            view["replayed"] = replayed
        return view

    def _watch_row(self, deal_id: str, item: list[Any], currency: str) -> dict[str, Any]:
        if not (isinstance(item, list) and len(item) == 9 and item[0] == "watch-result"):
            raise EngineError(f"unexpected watch result: {item!r}")
        _, tx, edition, classification, rule, version, evidence, owed, steps = item
        owed_rows = [{"party": o[1], "name": self.registry.name(o[1]), "wallet": o[2], "due_minor": o[3],
                      "received_minor": o[4], "short_minor": o[5], "amount_minor": o[5],
                      "due_display": format_minor(o[3], currency),
                      "received_display": format_minor(o[4], currency),
                      "amount_display": format_minor(o[5], currency)} for o in owed]
        if version != -1:  # list co-owners in the deal's own order, artist first
            parties = self.store.version(deal_id, version)["terms"]["parties"]
            order = {p["id"]: i for i, p in enumerate(parties)}
            owed_rows.sort(key=lambda o: order.get(o["party"], 99))
        total_owed = sum(o["short_minor"] for o in owed_rows)
        return {
            "deal_id": deal_id,
            "tx": tx,
            "edition": edition,
            "classification": str(classification),
            "rule": str(rule),
            "statement": self._statement(str(rule)),
            "deal_version": version if version != -1 else None,
            "evidence": pairs(evidence),
            "evidence_display": {k: format_minor(v, currency) for k, v in pairs(evidence).items()
                                 if k.endswith("-minor") and isinstance(v, int)},
            "owed": owed_rows,
            "total_owed_minor": total_owed,
            "total_owed_display": format_minor(total_owed, currency) if owed_rows else None,
            "steps": normalize_steps(steps),
        }

    def _flag_view(self, flag: dict[str, Any]) -> dict[str, Any]:
        currency = self._deal_currency(flag["deal_id"])
        view = dict(flag)
        view["statement"] = self._statement(flag["rule"])
        view["explanation"] = explain_flag(flag, self.registry, currency)
        view["steps"] = step_rows(flag["trace"], currency, self.registry, self.docs)
        view["created_at"] = iso(flag["created_at"])
        view["updated_at"] = iso(flag["updated_at"])
        view["history"] = [{**h, "at": iso(h["at"])} for h in flag["history"]]
        view["total_owed_minor"] = sum(o["short_minor"] for o in flag["owed"])
        view["total_owed_display"] = format_minor(view["total_owed_minor"], currency)
        view["evidence_display"] = {k: format_minor(v, currency) for k, v in flag["evidence"].items()
                                    if k.endswith("-minor") and isinstance(v, int)}
        return view

    # =========================================================== helpers

    def _statement(self, rule: str) -> str:
        return self.docs.get(rule, {}).get("statement", rule)

    def _version_or_404(self, deal_id: str, version: int) -> dict[str, Any]:
        ver = self.store.version(deal_id, int(version)) if self.store.deal_exists(deal_id) else None
        if ver is None:
            raise NotFound(f"There is no version {version} of {deal_id}.", "version-not-found")
        return ver

    def _deal_currency(self, deal_id: str) -> str:
        latest = self.store.version(deal_id, self.store.latest_version(deal_id))
        return (latest or {}).get("terms", {}).get("currency") or "KES"
