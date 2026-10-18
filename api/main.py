"""FastAPI app: a thin HTTP layer over agent.service.DealService.

Request bodies are deliberately loose (any JSON value per field) so that a
badly written deal reaches the agent, which names the rule it breaks,
instead of being bounced by input validation with a generic message.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict

from agent import scenarios
from agent.engine import Engine, EngineError
from agent.registry import Registry
from agent.service import DealService, ServiceError
from agent.store import Store

ROOT = Path(__file__).resolve().parent.parent
WEB_DIST = ROOT / "web" / "dist"


class DealDraft(BaseModel):
    model_config = ConfigDict(extra="allow")
    deal_id: str | None = None
    artwork_id: Any = None
    currency: Any = None
    edition_count: Any = None
    price: Any = None
    price_currency: Any = None
    royalty_percent: Any = None
    parties: list[dict[str, Any]] = []
    shares: list[dict[str, Any]] = []

    def draft(self) -> dict[str, Any]:
        data = self.model_dump()
        data.pop("deal_id", None)
        return data


class Approval(BaseModel):
    version: int
    party_id: str


class LockRequest(BaseModel):
    version: int


class SaleEvent(BaseModel):
    model_config = ConfigDict(extra="allow")
    event_id: Any = None
    deal_id: Any = None
    deal_version: Any = None
    edition: Any = None
    type: Any = None
    price: Any = None
    price_minor: Any = None
    currency: Any = None
    seller: Any = None
    buyer: Any = None
    timestamp: Any = None


class FlagUpdate(BaseModel):
    status: str
    reason: str = ""


def default_service() -> DealService:
    db_path = os.environ.get("EDA_DB_PATH", str(ROOT / "var" / "edition_deals.db"))
    return DealService(Store(db_path), Engine(), Registry.load())


def create_app(service: DealService | None = None) -> FastAPI:
    svc = service or default_service()
    app = FastAPI(
        title="Edition Deal Agent",
        description="Checks, pays out and watches edition deals for BASIX.MARKET. "
                    "The decisions are made by MeTTa rules (see /rules).",
        version="0.1.0",
    )
    app.state.service = svc
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(ServiceError)
    async def service_error(_: Request, exc: ServiceError) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content=exc.to_dict())

    @app.exception_handler(EngineError)
    async def engine_error(_: Request, exc: EngineError) -> JSONResponse:
        return JSONResponse(status_code=500, content={
            "error": "engine-error",
            "message": "The agent's rules returned something unexpected, so nothing was changed.",
            "detail": str(exc)})

    # ----------------------------------------------------------- context

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"ok": True}

    @app.get("/registry")
    def registry() -> dict[str, Any]:
        return svc.registry.data

    @app.get("/rules")
    def rules() -> dict[str, Any]:
        return {"rules": [{"rule": k, **v} for k, v in svc.docs.items()]}

    # ------------------------------------------------- job 1: the deal

    @app.get("/deals")
    def list_deals() -> list[dict[str, Any]]:
        return svc.list_deals()

    @app.post("/deals/check")
    def check_deal(body: DealDraft) -> dict[str, Any]:
        return svc.check_deal(body.draft(), body.deal_id)

    @app.post("/deals")
    def save_version(body: DealDraft) -> dict[str, Any]:
        return svc.save_version(body.draft(), body.deal_id)

    @app.get("/deals/{deal_id}/versions")
    def versions(deal_id: str) -> list[dict[str, Any]]:
        return svc.versions(deal_id)

    @app.post("/deals/{deal_id}/approve")
    def approve(deal_id: str, body: Approval) -> dict[str, Any]:
        return svc.approve(deal_id, body.version, body.party_id)

    @app.post("/deals/{deal_id}/lock")
    def lock(deal_id: str, body: LockRequest) -> dict[str, Any]:
        return svc.lock(deal_id, body.version)

    # ------------------------------------------------ job 2: pay out

    @app.post("/sales")
    def record_sale(body: SaleEvent) -> dict[str, Any]:
        return svc.record_sale(body.model_dump())

    @app.get("/sales")
    def list_sales(deal_id: str | None = None) -> list[dict[str, Any]]:
        return svc.list_sales(deal_id)

    @app.get("/sales/{sale_id}/explain")
    def explain(sale_id: str, party: str | None = None) -> dict[str, Any]:
        return svc.explain(sale_id, party)

    # -------------------------------------------------- job 3: watch

    @app.post("/watch/scan")
    def scan(deal_id: str | None = None) -> list[dict[str, Any]]:
        return svc.scan(deal_id)

    @app.get("/flags")
    def flags(status: str | None = None) -> list[dict[str, Any]]:
        return svc.list_flags(status.upper() if status else None)

    @app.patch("/flags/{flag_id}")
    def update_flag(flag_id: str, body: FlagUpdate) -> dict[str, Any]:
        return svc.update_flag(flag_id, body.status, body.reason)

    # ------------------------------------------------------ simulator

    @app.post("/sim/{scenario}")
    def simulate(scenario: str, params: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        return scenarios.run(svc, scenario, params or {})

    @app.get("/chain/transfers")
    def chain_transfers(deal_id: str) -> dict[str, Any]:
        transfers = svc.chain.read_transfers(deal_id)
        payments = svc.chain.read_payments([t.tx for t in transfers])
        return {"transfers": [t.__dict__ for t in transfers], "payments": [p.__dict__ for p in payments]}

    if WEB_DIST.exists():
        app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")

    return app


# Run with:  uvicorn api.main:create_app --factory
# (a factory, so importing this module never opens the database)
