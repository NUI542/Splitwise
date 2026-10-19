"""Python side of the Edition Deal Agent plugin for Omega.

Each function calls the Edition Deal Agent's HTTP API and returns a plain
string for the Omega agent to read back in chat. The skills can look and
watch, but never act: none of them approves, locks, records a sale or
resets anything. Explanations are the deal agent's own trace-based text,
passed through unchanged, so the numbers quoted in chat are the numbers
that were paid.

The first argument of every skill is the API's base URL. The plugin
passes Omega's `edaApiBase` setting, because Omega starts its agent with
a scrubbed environment where ordinary environment variables don't
arrive. Outside Omega, an empty value falls back to $EDA_API_BASE.

Only the Python standard library is used, so nothing needs installing in
Omega's container.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

DEFAULT_API = "http://host.docker.internal:8000"
TIMEOUT = 30


class SkillError(Exception):
    def __init__(self, message: str, detail: dict) -> None:
        super().__init__(message)
        self.detail = detail


def _base(api: Any) -> str:
    text = str(api or "").strip().strip('"')
    return (text or os.environ.get("EDA_API_BASE") or DEFAULT_API).rstrip("/")


def _call(api: str, method: str, path: str, body: Any = None) -> Any:
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(api + path, data=data, method=method,
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
        raise SkillError(f"The Edition Deal Agent isn't reachable at {api} ({err.reason}).", {}) from None


def _safe(fn):
    """Return errors as text the agent can relay, instead of raising into the loop."""
    def wrapped(api: Any = "", *args: Any) -> str:
        try:
            return fn(_base(api), *[str(a).strip().strip('"') for a in args])
        except SkillError as err:
            report = err.detail.get("report") or {}
            reasons = "; ".join(f"{e['detail']} [{e['rule']}]" for e in report.get("errors", []))
            return f"{err}" + (f" Reasons: {reasons}" if reasons else "")
    wrapped.__name__ = fn.__name__
    wrapped.__doc__ = fn.__doc__
    return wrapped


@_safe
def deal_status(api: str) -> str:
    """Every deal, its newest version and the version in force."""
    deals = _call(api, "GET", "/deals")
    if not deals:
        return "There are no deals yet."
    lines = []
    for d in deals:
        active = (f"version {d['active_version']} is locked and in force" if d["active_version"]
                  else "nothing locked yet")
        lines.append(f"{d['deal_id']} for {d['artwork_title'] or d['artwork_id']}: "
                     f"newest version {d['latest_version']}, {active}.")
    return "\n".join(lines)


@_safe
def recent_sales(api: str, limit: str = "5") -> str:
    """The latest sales in the ledger, with who was paid what."""
    sales = _call(api, "GET", "/sales")[-int(limit or 5):]
    if not sales:
        return "No sales have been paid out yet."
    out = []
    for s in reversed(sales):
        paid = ", ".join(f"{l['name']} {l['amount_display']}" for l in s["lines"])
        out.append(f"{s['sale_id']}: {s['type']} of edition {s['edition']} for {s['price_display']} "
                   f"(deal {s['deal_id']} v{s['deal_version']}). Paid: {paid}.")
    return "\n".join(out)


@_safe
def explain_payout(api: str, sale_id: str, party: str = "") -> str:
    """Why did <party> get <amount> for <sale>? Party is an ID (e.g. artist-a) or a wallet."""
    query = f"?party={urllib.parse.quote(party)}" if party else ""
    answer = _call(api, "GET", f"/sales/{urllib.parse.quote(sale_id)}/explain{query}")
    return answer["explanation"]


@_safe
def scan_royalties(api: str) -> str:
    """Run the watch: classify every transfer on the chain and report what needs a look."""
    rows = _call(api, "POST", "/watch/scan")
    if not rows:
        return "Nothing is on the chain yet."
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["classification"]] = counts.get(r["classification"], 0) + 1
    summary = ", ".join(f"{n} {c}" for c, n in counts.items())
    lines = [f"Scanned {len(rows)} transfers: {summary}."]
    for r in rows:
        if r["status"] != "OPEN":
            continue
        owed = f" {r['total_owed_display']} is owed." if r.get("total_owed_display") else " No royalty is claimed."
        lines.append(f"Open: {r['tx']} (edition {r['edition']}) is {r['classification']}: "
                     f"{r['statement']}{owed}")
    return "\n".join(lines)


@_safe
def open_flags(api: str) -> str:
    """The open flags, each with the deal agent's own explanation."""
    flags = _call(api, "GET", "/flags?status=OPEN")
    if not flags:
        return "There are no open flags."
    return "\n\n".join(f"{f['flag_id']} [{f['classification']}]: {f['explanation']}" for f in flags)


@_safe
def check_deal(api: str, deal_json: str) -> str:
    """Check a draft deal (JSON in the deal builder's shape) without saving anything."""
    try:
        draft = json.loads(deal_json)
    except ValueError:
        return "That isn't valid JSON for a deal."
    report = _call(api, "POST", "/deals/check", draft)
    if report["valid"]:
        warnings = "; ".join(f"{w['detail']} [{w['rule']}]" for w in report["warnings"])
        return f"Every rule holds. {' '.join(report['summary']['text'])}" + (
            f" Warnings: {warnings}" if warnings else "")
    return "The deal breaks these rules: " + "; ".join(f"{e['detail']} [{e['rule']}]" for e in report["errors"])
