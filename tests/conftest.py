from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent.engine import Engine  # noqa: E402
from agent.registry import Registry  # noqa: E402
from agent.service import DealService  # noqa: E402
from agent.store import Store  # noqa: E402

START = 1_792_310_400  # 2026-10-18 00:00:00 UTC


class Clock:
    """A clock that moves forward one second every time it is read."""

    def __init__(self, start: int = START) -> None:
        self.t = start

    def __call__(self) -> int:
        self.t += 1
        return self.t

    def jump(self, seconds: int) -> None:
        self.t += seconds


@pytest.fixture(scope="session")
def engine() -> Engine:
    return Engine()


@pytest.fixture(scope="session")
def registry() -> Registry:
    return Registry.load()


@pytest.fixture(scope="session")
def sample_deal_data() -> dict:
    return json.loads((ROOT / "data" / "sample_deal.json").read_text(encoding="utf-8"))


@pytest.fixture
def deal(sample_deal_data) -> dict:
    return copy.deepcopy(sample_deal_data)


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def service(engine, registry, clock) -> DealService:
    return DealService(Store(":memory:"), engine, registry, clock=clock)


def lock_deal(service: DealService, deal: dict) -> str:
    saved = service.save_version(deal)
    for party in deal["parties"]:
        service.approve(saved["deal_id"], saved["version"], party["id"])
    service.lock(saved["deal_id"], saved["version"])
    return saved["deal_id"]


@pytest.fixture
def locked(service, deal) -> str:
    return lock_deal(service, deal)


def wallet(party_id: str) -> str:
    return f"sim-wallet-{party_id}"
