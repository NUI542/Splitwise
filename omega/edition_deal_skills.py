"""OmegaClaw skills for the Edition Deal Agent.

Each function calls the Edition Deal Agent's HTTP API and returns a plain
string for the OmegaClaw agent to read back in chat. The skills can look
and watch, but never act: none of them approves, locks, records a sale or
resets anything. Explanations are the agent's own trace-based text, passed
through unchanged, so the numbers the chat quotes are the numbers paid.

Only the Python standard library is used, so nothing needs installing in
the OmegaClaw container.

EDA_API_BASE sets where the API is. From inside OmegaClaw's Docker
container the host machine is usually http://host.docker.internal:8000.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

API = os.environ.get("EDA_API_BASE", "http://host.docker.internal:8000").rstrip("/")
TIMEOUT = 30


def _call(method: str, path: str, body: Any = None) -> Any:
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(API + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as res:
            return json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        try:
            detail = json.loads(err.read().decode("utf-8"))
        except ValueError:
            detail = {"message": str(err)}
        raise SkillError(detail.get("message", str(err)), detail) from None
    except urllib.error.URLError as err:
        raise SkillError(f"The Edition Deal Agent isn't reachable at {API} ({err.reason}).", {}) from None


class SkillError(Exception):
    def __init__(self, message: str, detail: dict) -> None:
        super().__init__(message)
        self.detail = detail


def _safe(fn):
    def wrapped(*args):
        try:
            return fn(*[str(a).strip().strip('"') for a in args])
        except SkillError as err:
            report = err.detail.get("report") or {}
            reasons = "; ".join(f"{e['detail']} [{e['rule']}]" for e in report.get("errors", []))
            return f"{err}" + (f" Reasons: {reasons}" if reasons else "")
    wrapped.__name__ = fn.__name__
    wrapped.__doc__ = fn.__doc__
    return wrapped


@_safe
def deal_status() -> str:
    """Every deal, its newest version and the version in force."""
    deals = _call("GET", "/deals")
    if not deals:
        return "There are no deals yet."
    lines = []
    for d in deals:
        active = f"version {d['active_version']} is locked and in force" if d["active_version"] else "nothing locked yet"
        lines.append(f"{d['deal_id']} for {d['artwork_title'] or d['artwork_id']}: "
                     f"newest version {d['latest_version']}, {active}.")
    return "\n".join(lines)


@_safe
def recent_sales(limit: str = "5") -> str:
    """The latest sales in the ledger, with who was paid what."""
    sales = _call("GET", "/sales")[-int(limit or 5):]
    if not sales:
        return "No sales have been paid out yet."
    out = []
    for s in reversed(sales):
        paid = ", ".join(f"{l['name']} {l['amount_display']}" for l in s["lines"])
        out.append(f"{s['sale_id']}: {s['type']} of edition {s['edition']} for {s['price_display']} "
                   f"(deal {s['deal_id']} v{s['deal_version']}). Paid: {paid}.")
    return "\n".join(out)


@_safe
def explain_payout(sale_id: str, party: str = "") -> str:
    """Why did <party> get <amount> for <sale>? Party is an ID (e.g. artist-a) or a wallet."""
    query = f"?party={urllib.parse.quote(party)}" if party else ""
    answer = _call("GET", f"/sales/{urllib.parse.quote(sale_id)}/explain{query}")
    return answer["explanation"]


@_safe
def scan_royalties() -> str:
    """Run the watch: classify every transfer on the chain and report what needs a look."""
    rows = _call("POST", "/watch/scan")
    if not rows:
        return "Nothing is on the chain yet."
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["classification"]] = counts.get(r["classification"], 0) + 1
    summary = ", ".join(f"{n} {c}" for c, n in counts.items())
    flagged = [r for r in rows if r["status"] == "OPEN"]
    lines = [f"Scanned {len(rows)} transfers: {summary}."]
    for r in flagged:
        owed = f" {r['total_owed_display']} is owed." if r.get("total_owed_display") else " No royalty is claimed."
        lines.append(f"Open: {r['tx']} (edition {r['edition']}) is {r['classification']} because {r['statement'].lower()}{owed}")
    return "\n".join(lines)


@_safe
def open_flags() -> str:
    """The open flags, each with the agent's own explanation."""
    flags = _call("GET", "/flags?status=OPEN")
    if not flags:
        return "There are no open flags."
    return "\n\n".join(f"{f['flag_id']} [{f['classification']}]: {f['explanation']}" for f in flags)


@_safe
def check_deal(deal_json: str) -> str:
    """Check a draft deal (JSON in the deal builder's shape) without saving anything."""
    try:
        draft = json.loads(deal_json)
    except ValueError:
        return "That isn't valid JSON for a deal."
    report = _call("POST", "/deals/check", draft)
    if report["valid"]:
        warnings = "; ".join(f"{w['detail']} [{w['rule']}]" for w in report["warnings"])
        text = " ".join(report["summary"]["text"])
        return f"Every rule holds. {text}" + (f" Warnings: {warnings}" if warnings else "")
    return "The deal breaks these rules: " + "; ".join(f"{e['detail']} [{e['rule']}]" for e in report["errors"])
