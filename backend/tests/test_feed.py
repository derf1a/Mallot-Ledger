"""홈 대시보드용 요약 — 열쇠가 맞는 이 컴퓨터 안 GET /api/feed/* 만 로그인 없이, 숫자만 준다."""

import pytest

from app.auth import security

TOKEN = "t" * 40


@pytest.fixture
def locked(monkeypatch):
    monkeypatch.setenv("MLG_ADMIN_PASSWORD_HASH", security.hash_password("correct horse battery"))
    monkeypatch.setenv("MLG_FEED_TOKEN", TOKEN)


def test_token_reads_feed_from_local(client, locked):
    r = client.get("/api/feed/resources", headers={"X-Mallot-Feed": TOKEN})
    assert r.status_code == 200
    body = r.json()
    assert body["version"] not in ("0", "?") and body["app"] == "ledger" and len(body["llm"]["daily"]) == 30 and "runs" in body
    s = client.get("/api/feed/summary", headers={"X-Mallot-Feed": TOKEN}).json()
    assert s["app"] == "ledger" and "period" in s and "spent_total" in s["variable"]


@pytest.mark.parametrize("headers", [
    {"X-Mallot-Feed": "wrong" * 10},
    {"X-Mallot-Feed": TOKEN, "Cf-Connecting-IP": "203.0.113.1"},   # 터널을 거쳐 온 요청
    {},
])
def test_feed_refused_without_right_local_token(client, locked, headers):
    assert client.get("/api/feed/resources", headers=headers).status_code == 401


def test_token_opens_nothing_else(client, locked):
    assert client.get("/api/transactions", headers={"X-Mallot-Feed": TOKEN}).status_code == 401


def test_short_token_is_off(client, monkeypatch):
    monkeypatch.setenv("MLG_ADMIN_PASSWORD_HASH", security.hash_password("correct horse battery"))
    monkeypatch.setenv("MLG_FEED_TOKEN", "short")
    assert client.get("/api/feed/resources", headers={"X-Mallot-Feed": "short"}).status_code == 401


def test_admin_can_read_feed(client, locked):
    assert client.post("/api/auth/login", json={"password": "correct horse battery"}).status_code == 200
    assert client.get("/api/feed/summary").status_code == 200
