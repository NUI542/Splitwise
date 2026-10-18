"""Plain-language explanations, filled in from the agent's trace.

Nothing here calculates a payout. Every number shown comes from a trace
step the rules produced, so the numbers explained are the numbers paid.
The only arithmetic is formatting: showing the exact (unrounded) value a
step rounded down from, using the step's own product.
"""
from __future__ import annotations

from typing import Any

from .engine import pairs
from .money import BPS_PER_WHOLE, format_bps, format_exact, format_minor
from .registry import Registry


def normalize_steps(raw: Any) -> list[dict[str, Any]]:
    """Nested (step name ((k v) ...)) lists from MeTTa -> [{"rule": name, "values": {...}}]."""
    out: list[dict[str, Any]] = []

    def walk(node: Any) -> None:
        if isinstance(node, list) and len(node) == 3 and node[0] == "step" and isinstance(node[2], list):
            out.append({"rule": str(node[1]), "values": pairs(node[2])})
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(raw)
    return out


def step_rows(steps: list[dict[str, Any]], currency: str, registry: Registry,
              docs: dict[str, dict[str, str]]) -> list[dict[str, Any]]:
    """One row per step for the Explain screen: rule, statement, inputs, calculation, result."""
    rows = []
    for step in steps:
        v = step["values"]
        rule = step["rule"]
        m = lambda x: format_minor(int(x), currency)  # noqa: E731
        calc, inputs, result = "", {}, ""
        if rule == "primary-split":
            inputs = {"price": m(v["price-minor"]), "deal version": v["version"]}
            calc = f"split {m(v['price-minor'])} by share"
        elif rule == "royalty-amount":
            exact = format_exact(v["product"], BPS_PER_WHOLE, currency)
            inputs = {"price": m(v["price-minor"]), "royalty rate": format_bps(v["royalty-bps"])}
            calc = f"{format_bps(v['royalty-bps'])} × {m(v['price-minor'])} = {exact}"
            result = m(v["result-minor"])
            if v["dropped"]:
                calc += f", rounded down to {result}"
        elif rule == "seller-proceeds":
            inputs = {"price": m(v["price-minor"]), "royalty": m(v["royalty-minor"])}
            calc = f"{m(v['price-minor'])} − {m(v['royalty-minor'])}"
            result = m(v["result-minor"])
        elif rule == "share-split":
            exact = format_exact(v["product"], BPS_PER_WHOLE, currency)
            inputs = {"co-owner": registry.name(v["party"]), "share": format_bps(v["share-bps"]),
                      "of": m(v["base-minor"])}
            calc = f"{format_bps(v['share-bps'])} × {m(v['base-minor'])} = {exact}"
            result = m(v["result-minor"])
            if v["dropped"]:
                calc += f", rounded down to {result}"
        elif rule == "leftover-to-artist":
            inputs = {"amount split": m(v["base-minor"]), "allocated": m(v["allocated-minor"])}
            calc = f"{m(v['base-minor'])} − {m(v['allocated-minor'])} = {m(v['leftover-minor'])}"
            result = f"{m(v['leftover-minor'])} to {registry.name(v['artist'])}"
        elif rule == "sum-check":
            inputs = {"lines total": m(v["total-minor"]), "amount paid": m(v["expected-minor"])}
            ok = v["total-minor"] == v["expected-minor"]
            calc = f"{m(v['total-minor'])} {'=' if ok else '≠'} {m(v['expected-minor'])}"
            result = "exact" if ok else "MISMATCH"
        rows.append({
            "rule": rule,
            "statement": docs.get(rule, {}).get("statement", ""),
            "party": v.get("party"),
            "inputs": inputs,
            "calculation": calc,
            "result": result,
            "values": v,
        })
    return rows


def _find(steps: list[dict[str, Any]], rule: str, party: str | None = None) -> dict[str, Any] | None:
    for step in steps:
        if step["rule"] == rule and (party is None or step["values"].get("party") == party):
            return step["values"]
    return None


def explain_line(sale: dict[str, Any], line: dict[str, Any], registry: Registry) -> str:
    """Why did this party get this amount for this sale?"""
    steps = sale["trace"]["steps"]
    cur = sale["currency"]
    m = lambda x: format_minor(int(x), cur)  # noqa: E731
    who = registry.name(line["party"])
    amount = m(line["amount_minor"])
    sentences = [f"Why did {who} get {amount} for sale {sale['sale_id']}?"]
    kind = "primary sale" if sale["type"] == "primary" else "resale"
    sentences.append(
        f"This was a {kind} of edition {sale['edition']} for {m(sale['price_minor'])}, "
        f"paid under deal {sale['deal_id']}, version {sale['deal_version']}.")

    royalty = _find(steps, "royalty-amount")
    if royalty:
        exact = format_exact(royalty["product"], BPS_PER_WHOLE, cur)
        text = (f"The deal's resale royalty is {format_bps(royalty['royalty-bps'])}. "
                f"{format_bps(royalty['royalty-bps'])} of {m(royalty['price-minor'])} is {exact}")
        text += (f", rounded down to {m(royalty['result-minor'])}." if royalty["dropped"]
                 else ", so the royalty is exactly that.")
        sentences.append(text)

    if line["role"] == "seller":
        proceeds = _find(steps, "seller-proceeds")
        sentences.append(
            f"As the seller, {who} receives the price minus the royalty: "
            f"{m(proceeds['price-minor'])} − {m(proceeds['royalty-minor'])} = {m(proceeds['result-minor'])}.")
    else:
        share = _find(steps, "share-split", line["party"])
        if share:
            base_label = "the royalty" if royalty else "the price"
            exact = format_exact(share["product"], BPS_PER_WHOLE, cur)
            text = (f"{who} holds {format_bps(share['share-bps'])} of the deal, so their share of {base_label} "
                    f"({m(share['base-minor'])}) is {exact}")
            text += (f", rounded down to {m(share['result-minor'])}." if share["dropped"]
                     else f", which is exactly {m(share['result-minor'])}.")
            sentences.append(text)
        leftover = _find(steps, "leftover-to-artist")
        if leftover and leftover["artist"] == line["party"]:
            if leftover["leftover-minor"]:
                sentences.append(
                    f"Rounding every share down left {m(leftover['leftover-minor'])} unallocated "
                    f"({m(leftover['base-minor'])} − {m(leftover['allocated-minor'])}). "
                    f"The deal gives leftovers to the artist, so {who} also receives it.")
            else:
                sentences.append("Nothing was left over after rounding, so there is no leftover to add.")
    total = _find(steps, "sum-check")
    if total:
        sentences.append(
            f"Total to {who}: {amount}. All {len(sale['lines'])} payout lines add up to "
            f"{m(total['total-minor'])}, exactly the {m(total['expected-minor'])} paid.")
    return "\n".join(sentences)


def explain_flag(flag: dict[str, Any], registry: Registry, currency: str) -> str:
    m = lambda x: format_minor(int(x), currency)  # noqa: E731
    ev = flag["evidence"]
    head = f"Transaction {flag['tx']} moved edition {flag['edition']} from " \
           f"{registry.name(ev.get('from'))} to {registry.name(ev.get('to'))}."
    if flag["classification"] == "SALE_ROYALTY_MISSING":
        owed = "; ".join(f"{registry.name(o['party'])} is owed {m(o['short_minor'])}"
                         + (f" (received {m(o['received_minor'])} of {m(o['due_minor'])})" if o["received_minor"] else "")
                         for o in flag["owed"])
        return (f"{head} In the same transaction the new holder paid {m(ev['buyer-paid-minor'])}, so this was a sale. "
                f"The royalty due on that price is {m(ev['royalty-due-minor'])}, but the co-owners received "
                f"{m(ev['royalty-received-minor'])}. {owed}.")
    if flag["rule"] == "no-payment-evidence":
        return (f"{head} The new holder paid nothing inside the transaction, so the chain can't show "
                "whether this was a gift, a move between someone's own wallets, or a sale settled elsewhere. "
                "No royalty is claimed; it needs a human look.")
    if flag["rule"] == "mint-without-ledger-sale":
        return f"{head} It is a mint, but no primary sale was recorded for it on BASIX.MARKET."
    if flag["rule"] == "no-active-deal":
        return f"{head} No locked deal was in force at that time, so it can't be checked."
    return head
