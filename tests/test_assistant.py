"""The "Ask the agent" chat: the app's messages reach Omega over its websocket
channel, and Omega's replies come back to the app. These tests play Omega's
side of the protocol (channels/wschat.py in the Omega repo)."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from agent.service import DealService
from agent.store import Store
from api.main import create_app
from conftest import Clock

TOKEN = "test-omega-token"


@pytest.fixture
def client(engine, registry):
    app = create_app(DealService(Store(":memory:"), engine, registry, clock=Clock()), omega_token=TOKEN)
    with TestClient(app) as c:  # one event loop for HTTP and websocket
        yield c


def omega(client, token=TOKEN):
    return client.websocket_connect("/omega/ws", headers={"Authorization": f"Bearer {token}"})


def send(ws, frame):
    ws.send_text(json.dumps(frame))


def recv(ws):
    return json.loads(ws.receive_text())


def ask(client, text):
    return client.post("/assistant/messages", json={"text": text})


def test_a_question_reaches_omega_and_the_reply_comes_back(client):
    with omega(client) as ws:
        send(ws, {"type": "resume", "last_seen_seq": None})
        posted = ask(client, "Which deals are in force?").json()
        assert posted["status"]["connected"]
        assert recv(ws) == {"type": "user_message", "seq": posted["message"]["id"],
                            "text": "Which deals are in force?"}
        send(ws, {"type": "agent_message", "client_seq": "c1", "text": "deal-1 version 1 is in force."})
        ack = recv(ws)
        assert ack["type"] == "ack" and ack["client_seq"] == "c1"
    messages = client.get("/assistant/messages").json()["messages"]
    assert [(m["role"], m["text"]) for m in messages] == [
        ("user", "Which deals are in force?"), ("agent", "deal-1 version 1 is in force.")]
    assert messages[0]["delivered"] is True
    assert client.get("/assistant/messages", params={"after": messages[0]["id"]}).json()["messages"][0]["role"] == "agent"


def test_omega_needs_the_token(client):
    with pytest.raises(WebSocketDisconnect):
        with omega(client, token="wrong") as ws:
            ws.receive_text()
    assert not client.get("/assistant/status").json()["connected"]


def test_without_a_token_nobody_can_connect(engine, registry):
    app = create_app(DealService(Store(":memory:"), engine, registry, clock=Clock()), omega_token="")
    with TestClient(app) as c:
        with pytest.raises(WebSocketDisconnect):
            with c.websocket_connect("/omega/ws", headers={"Authorization": "Bearer "}) as ws:
                ws.receive_text()
        status = c.get("/assistant/status").json()
        assert not status["configured"] and "EDA_OMEGA_WS_TOKEN" in status["detail"]


def test_messages_wait_while_omega_is_offline(client):
    posted = ask(client, "Any unpaid royalties?").json()
    assert posted["message"]["delivered"] is False
    assert not posted["status"]["connected"]
    with omega(client) as ws:
        send(ws, {"type": "resume", "last_seen_seq": None})
        assert recv(ws)["text"] == "Any unpaid royalties?"
        send(ws, {"type": "agent_message", "client_seq": "c1", "text": "One."})
        recv(ws)  # ack
    assert client.get("/assistant/messages").json()["messages"][0]["delivered"] is True


def test_a_restarted_omega_is_not_asked_old_questions_again(client):
    store = client.app.state.bridge.store
    with omega(client) as ws:
        send(ws, {"type": "resume", "last_seen_seq": None})
        first = ask(client, "First question").json()["message"]
        recv(ws)
    assert store.user_messages_to_replay(None) == []  # a fresh Omega process: nothing to replay
    second = ask(client, "Second question").json()["message"]
    # A reconnect that says how far it got is sent everything after that point.
    assert [m["id"] for m in store.user_messages_to_replay(first["id"])] == [second["id"]]


def test_a_repeated_reply_is_stored_once(client):
    with omega(client) as ws:
        send(ws, {"type": "resume", "last_seen_seq": None})
        for _ in range(2):
            send(ws, {"type": "agent_message", "client_seq": "same", "text": "Hello."})
            recv(ws)
    assert [m["text"] for m in client.get("/assistant/messages").json()["messages"]] == ["Hello."]


@pytest.mark.parametrize("text, code", [
    ("", "message-empty"),
    ("   ", "message-empty"),
    ("/memory-export both", "message-command"),
    ("x" * 2001, "message-too-long"),
])
def test_some_messages_are_refused(client, text, code):
    res = ask(client, text)
    assert res.status_code == 422 and res.json()["error"] == code


def test_unknown_frames_get_an_error_frame(client):
    with omega(client) as ws:
        send(ws, {"type": "something-else"})
        assert recv(ws)["type"] == "error"
        ws.send_text("not json")
        assert recv(ws)["code"] == "bad-json"


def test_status_while_connected(client):
    with omega(client) as ws:
        send(ws, {"type": "resume", "last_seen_seq": None})
        status = client.get("/assistant/status").json()
        assert status["connected"] and status["connected_at"]
    assert not client.get("/assistant/status").json()["connected"]
