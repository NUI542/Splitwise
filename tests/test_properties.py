"""Property-based tests (Hypothesis): exact sums, leftover to the artist,
no double payment on replay, and locked deals never change."""
from __future__ import annotations

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from agent import facts as F
from agent.engine import Engine
from agent.registry import Registry
from agent.service import DealService
from agent.store import Store
from conftest import Clock, lock_deal, wallet

ENGINE = Engine()
REGISTRY = Registry.load()
def slow(examples: int):
    """The engine takes ~0.3-2 s per query, so examples are few and deadlines off."""
    return settings(max_examples=examples, deadline=None,
                    suppress_health_check=[HealthCheck.function_scoped_fixture])
PARTY_IDS = ["artist-a", "basix-market", "broker-c", "studio-d"]


@st.composite
def share_splits(draw):
    """2 to 4 positive basis-point shares adding up to exactly 10000."""
    n = draw(st.integers(min_value=2, max_value=4))
    cuts = sorted(draw(st.lists(st.integers(min_value=1, max_value=9999), min_size=n - 1, max_size=n - 1,
                                unique=True)))
    bounds = [0] + cuts + [10000]
    return [bounds[i + 1] - bounds[i] for i in range(n)]


def deal_with(shares: list[int], price_minor: int = 1_500_000, royalty_bps: int = 1000) -> dict:
    ids = PARTY_IDS[: len(shares)]
    return {
        "artwork_id": "aw-placeholder-001", "currency": "KES", "edition_count": 10,
        "price_minor": price_minor, "royalty_bps": royalty_bps,
        "parties": [{"id": p, "name": p, "role": "artist" if i == 0 else "co-owner", "wallet": wallet(p)}
                    for i, p in enumerate(ids)],
        "shares": [{"party_id": p, "kind": "percent", "value": str(b / 100)} for p, b in zip(ids, shares)],
    }


def split(shares: list[int], base: int):
    terms = F.normalize_terms(deal_with(shares))
    facts = F.registry_facts(REGISTRY.data) + F.terms_facts(1, terms)
    result = ENGINE.query_one(facts, f"(split 1 {base})")
    lines = {l[1]: l[4] for l in result[1]}
    leftover = dict(result[3][2])["leftover-minor"]
    return lines, leftover


@slow(30)
@given(shares=share_splits(), base=st.integers(min_value=0, max_value=10**12))
def test_split_is_exact_and_leftover_goes_to_the_artist(shares, base):
    lines, leftover = split(shares, base)
    ids = PARTY_IDS[: len(shares)]
    assert sum(lines.values()) == base
    for pid, bps in zip(ids, shares):
        floor_share = base * bps // 10000
        if pid == "artist-a":
            assert lines[pid] == floor_share + leftover
        else:
            assert lines[pid] == floor_share
    # Each rounded-down share loses less than one cent.
    assert 0 <= leftover < len(shares)


@slow(8)
@given(price=st.integers(min_value=1_000, max_value=10**9), replays=st.integers(min_value=1, max_value=3))
def test_replaying_a_sale_never_pays_twice(price, replays):
    service = DealService(Store(":memory:"), ENGINE, REGISTRY, clock=Clock())
    deal_id = lock_deal(service, deal_with([6000, 1500, 1500, 1000]))
    event = {"event_id": "e1", "deal_id": deal_id, "type": "primary", "edition": 1,
             "price_minor": price, "buyer": wallet("collector-1")}
    first = service.record_sale(event)
    for _ in range(replays):
        assert service.record_sale(event)["lines"] == first["lines"]
    assert len(service.list_sales()) == 1
    payments = service.chain.read_payments([first["tx"]])
    assert sum(p.amount_minor for p in payments) == price
    assert len(service.chain.read_transfers(deal_id)) == 1


@slow(6)
@given(resale_price=st.integers(min_value=1, max_value=10**9), new_price=st.integers(min_value=10_000, max_value=10**8))
def test_locked_deals_never_change(resale_price, new_price):
    service = DealService(Store(":memory:"), ENGINE, REGISTRY, clock=Clock())
    deal = deal_with([6000, 1500, 1500, 1000])
    deal_id = lock_deal(service, deal)
    locked_hash = service.store.locks(deal_id)[0]["terms_hash"]
    before = service.store.version(deal_id, 1)["terms"]

    service.record_sale({"event_id": "p", "deal_id": deal_id, "type": "primary", "edition": 1,
                         "price_minor": 1_500_000, "buyer": wallet("collector-1")})
    resale = service.record_sale({"event_id": "r", "deal_id": deal_id, "type": "resale", "edition": 1,
                                  "price_minor": resale_price, "seller": wallet("collector-1"),
                                  "buyer": wallet("collector-2")})
    deal["price_minor"] = new_price
    service.save_version(deal, deal_id)

    after = service.store.version(deal_id, 1)
    assert after["terms"] == before
    assert after["terms_hash"] == locked_hash == F.terms_hash(after["terms"])
    assert resale["deal_version"] == 1
    royalty = next(s for s in resale["trace"]["steps"] if s["rule"] == "royalty-amount")["values"]["result-minor"]
    assert royalty == resale_price * 1000 // 10000
    assert sum(l["amount_minor"] for l in resale["lines"]) == resale_price
