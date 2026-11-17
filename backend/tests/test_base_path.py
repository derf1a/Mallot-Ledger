"""경로 접두사(MLG_BASE_PATH) — 한 도메인의 /ledger/ 아래에서 돌 때 앞을 떼고, 없으면 지금 그대로."""

import pytest

from app.core.base_path import base_path


@pytest.fixture
def based(monkeypatch):
    monkeypatch.setenv("MLG_BASE_PATH", "/ledger")


def test_base_path_is_normalized(monkeypatch):
    assert base_path() == ""
    for raw in ("/ledger", "ledger", "/ledger/", " /ledger/ "):
        monkeypatch.setenv("MLG_BASE_PATH", raw)
        assert base_path() == "/ledger", raw
    monkeypatch.setenv("MLG_BASE_PATH", "/")
    assert base_path() == ""


def test_prefix_is_stripped(client, based):
    r = client.get("/ledger/api/health")
    assert r.status_code == 200 and r.json()["ok"] is True
    assert client.get("/ledger/api/settings").status_code == 200  # guard 도 뗀 경로(/api/...)를 본다


def test_bare_base_redirects_with_query(client, based):
    r = client.get("/ledger", params={"a": "1"}, follow_redirects=False)
    assert r.status_code == 307 and r.headers["location"] == "/ledger/?a=1"
    r = client.get("/ledger", follow_redirects=False)
    assert r.status_code == 307 and r.headers["location"] == "/ledger/"


def test_requests_without_prefix_pass_through(client, based):
    """127.0.0.1:포트 로 직접 연 요청 · 홈의 /api/feed/* 는 접두사 없이 그대로 된다."""
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/settings").status_code == 200


def test_guard_still_applies_after_stripping(client, based):
    r = client.get("/ledger/api/settings", headers={"Cf-Connecting-IP": "203.0.113.7"})
    assert r.status_code == 403  # 비밀번호 없이 터널로 온 요청은 접두사가 있어도 막는다


def test_without_base_path_nothing_changes(client):
    assert client.get("/api/health").status_code == 200
    r = client.get("/ledger", follow_redirects=False)
    assert r.status_code != 307  # 접두사가 없으면 /ledger 는 화면 경로일 뿐


async def _run(scope):
    from app.core.base_path import BasePathMiddleware

    seen: dict = {}

    async def inner(s, receive, send):
        seen.update(s)

    async def receive():
        return {"type": "websocket.connect"}

    async def send(_):
        pass

    await BasePathMiddleware(inner)(scope, receive, send)
    return seen


def test_raw_path_and_websocket_are_stripped(based):
    import asyncio

    seen = asyncio.run(_run({"type": "http", "path": "/ledger/api/x", "raw_path": b"/ledger/api/x", "query_string": b""}))
    assert seen["path"] == "/api/x" and seen["raw_path"] == b"/api/x"
    seen = asyncio.run(_run({"type": "websocket", "path": "/ledger/ws", "raw_path": b"/ledger/ws", "query_string": b""}))
    assert seen["path"] == "/ws" and seen["raw_path"] == b"/ws"
    seen = asyncio.run(_run({"type": "http", "path": "/ledgerx/a", "raw_path": b"/ledgerx/a", "query_string": b""}))
    assert seen["path"] == "/ledgerx/a"  # 이름만 비슷하면 그대로
    seen = asyncio.run(_run({"type": "http", "path": "/api/feed/summary", "raw_path": None, "query_string": b""}))
    assert seen["path"] == "/api/feed/summary"
