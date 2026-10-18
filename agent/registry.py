"""The placeholder registry of artworks, parties and wallets (data/registry.json)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REGISTRY_PATH = Path(__file__).resolve().parent.parent / "data" / "registry.json"


class Registry:
    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data
        self.parties = {p["id"]: p for p in data.get("parties", [])}
        self.artworks = {a["id"]: a for a in data.get("artworks", [])}
        self.wallet_owner = {w: p["id"] for p in data.get("parties", []) for w in p.get("wallets", [])}

    @classmethod
    def load(cls, path: Path = REGISTRY_PATH) -> "Registry":
        return cls(json.loads(path.read_text(encoding="utf-8")))

    def name(self, party_or_wallet: str | None) -> str:
        """A display name for a party ID or a wallet."""
        if not party_or_wallet:
            return "unknown"
        if party_or_wallet in self.parties:
            return self.parties[party_or_wallet]["name"]
        owner = self.wallet_owner.get(party_or_wallet)
        if owner:
            return self.parties[owner]["name"]
        if party_or_wallet.startswith("mint:"):
            return f"the mint for {party_or_wallet[5:]}"
        return party_or_wallet

    def first_wallet(self, party_id: str) -> str | None:
        wallets = self.parties.get(party_id, {}).get("wallets") or []
        return wallets[0] if wallets else None

    def collectors(self) -> list[dict[str, Any]]:
        return [p for p in self.parties.values() if p.get("kind") == "collector"]
