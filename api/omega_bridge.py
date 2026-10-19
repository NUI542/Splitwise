"""The server end of Omega's websocket chat channel.

Omega (channels/wschat.py in the Omega repo, selected with
commchannel=websocket) connects *out* to a chat server and swaps small JSON
frames with it. This is that server. People type in the React app's
"Ask the agent" panel; their messages are stored here and passed to Omega as
`user_message` frames; Omega's replies come back as `agent_message` frames and
are stored for the app to show. Nobody sees Telegram or Omega directly.

Frames (from Omega's wschat.py):
  to Omega:    {"type": "user_message", "seq": int, "text": str}
               {"type": "ack", "seq": int, "client_seq": str}
  from Omega:  {"type": "resume", "last_seen_seq": int | null}   on every (re)connect
               {"type": "agent_message", "client_seq": str, "text": str}

Omega authenticates with `Authorization: Bearer <EDA_OMEGA_WS_TOKEN>`; that
channel has no other login, so without a token the endpoint refuses everyone.
"""
from __future__ import annotations

import asyncio
import hmac
import json
import time
from datetime import datetime, timezone
from typing import Any, Callable

from fastapi import WebSocket, WebSocketDisconnect

from agent.store import Store

MAX_TEXT = 2000


class ChatRefused(Exception):
    def __init__(self, message: str, code: str) -> None:
        super().__init__(message)
        self.message = message
        self.code = code


def _iso(ts: int | None) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat().replace("+00:00", "Z")


class OmegaBridge:
    def __init__(self, store: Store, token: str | None, clock: Callable[[], float] | None = None) -> None:
        self.store = store
        self.token = (token or "").strip()
        self.clock = clock or time.time
        self._ws: WebSocket | None = None
        self._send_lock = asyncio.Lock()
        self.connected_at: int | None = None
        self.last_heard_at: int | None = None

    def now(self) -> int:
        return int(self.clock())

    # ----------------------------------------------------------- the app

    def status(self) -> dict[str, Any]:
        connected = self._ws is not None
        if not self.token:
            detail = "Not set up: EDA_OMEGA_WS_TOKEN isn't set, so Omega can't connect."
        elif connected:
            detail = "Omega is connected."
        else:
            detail = "Omega isn't connected. Messages wait here until it connects."
        return {"configured": bool(self.token), "connected": connected,
                "connected_at": _iso(self.connected_at), "last_heard_at": _iso(self.last_heard_at),
                "detail": detail}

    def messages(self, after: int = 0) -> list[dict[str, Any]]:
        return [self._view(m) for m in self.store.assistant_messages(after)]

    async def post(self, text: Any) -> dict[str, Any]:
        """A message typed in the app: stored, then passed to Omega if it's connected."""
        text = str(text or "").strip()
        if not text:
            raise ChatRefused("Type a question first.", "message-empty")
        if len(text) > MAX_TEXT:
            raise ChatRefused(f"Keep it under {MAX_TEXT} characters.", "message-too-long")
        if text.startswith("/"):
            # Omega's channels treat /... as operator commands (e.g. /memory-export).
            raise ChatRefused("Commands for Omega's operator can't be sent from the app.", "message-command")
        message, _ = self.store.add_assistant_message("user", text, self.now())
        ws = self._ws
        if ws is not None:
            try:
                await self._send_user_message(ws, message)
            except Exception:
                pass  # stays undelivered; replayed when Omega reconnects
        return self._view(self.store.assistant_messages(message["id"] - 1, 1)[0])

    # ---------------------------------------------------------- Omega

    async def serve(self, ws: WebSocket) -> None:
        offered = ws.headers.get("authorization", "")
        if not self.token or not hmac.compare_digest(offered.encode(), f"Bearer {self.token}".encode()):
            await ws.close(code=1008)  # refused before the handshake completes
            return
        await ws.accept()
        previous, self._ws = self._ws, ws
        if previous is not None:
            try:
                await previous.close(code=1012)  # a newer Omega connection replaces the old one
            except Exception:
                pass
        self.connected_at = self.last_heard_at = self.now()
        try:
            while True:
                raw = await ws.receive_text()
                self.last_heard_at = self.now()
                await self._handle(ws, raw)
        except WebSocketDisconnect:
            pass
        finally:
            if self._ws is ws:
                self._ws = None
                self.connected_at = None

    async def _handle(self, ws: WebSocket, raw: str) -> None:
        try:
            frame = json.loads(raw)
        except ValueError:
            await self._send(ws, {"type": "error", "code": "bad-json", "message": "Frames are JSON objects."})
            return
        kind = frame.get("type") if isinstance(frame, dict) else None
        if kind == "resume":
            for message in self.store.user_messages_to_replay(frame.get("last_seen_seq")):
                await self._send_user_message(ws, message)
        elif kind == "agent_message":
            text = frame.get("text")
            client_seq = str(frame.get("client_seq") or "") or None
            if not isinstance(text, str) or not text.strip():
                await self._send(ws, {"type": "error", "code": "empty-message", "message": "agent_message needs text."})
                return
            message, _ = self.store.add_assistant_message("agent", text.strip(), self.now(), client_seq)
            await self._send(ws, {"type": "ack", "seq": message["id"], "client_seq": client_seq})
        else:
            await self._send(ws, {"type": "error", "code": "unsupported", "message": f"Unknown frame type {kind!r}."})

    async def _send_user_message(self, ws: WebSocket, message: dict[str, Any]) -> None:
        await self._send(ws, {"type": "user_message", "seq": message["id"], "text": message["text"]})
        self.store.mark_assistant_delivered(message["id"], self.now())

    async def _send(self, ws: WebSocket, payload: dict[str, Any]) -> None:
        async with self._send_lock:
            await ws.send_text(json.dumps(payload))

    @staticmethod
    def _view(m: dict[str, Any]) -> dict[str, Any]:
        return {"id": m["id"], "role": m["role"], "text": m["text"], "at": _iso(m["at"]),
                "delivered": m["delivered_at"] is not None if m["role"] == "user" else None}
