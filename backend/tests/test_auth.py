"""관리자 로그인 · 손님 공유 링크 · 요청마다 역할 검사."""

import pytest

from app.auth import security

PASSWORD = "correct horse battery"
PROXY = {"Cf-Connecting-IP": "203.0.113.7"}


@pytest.fixture
def admin_pw(monkeypatch):
    monkeypatch.setenv("MLG_ADMIN_PASSWORD_HASH", security.hash_password(PASSWORD))


def _login(client, pw=PASSWORD):
    return client.post("/api/auth/login", json={"password": pw})


def test_without_password_local_is_open_but_tunnelled_requests_are_refused(client):
    assert client.get("/api/settings").status_code == 200  # 이 컴퓨터에서 쓰는 지금 그대로
    assert client.get("/api/auth/me").json()["role"] == "admin"
    r = client.get("/api/settings", headers=PROXY)
    assert r.status_code == 403 and "비밀번호" in r.json()["detail"]
    assert client.get("/openapi.json", headers=PROXY).status_code == 403


def test_admin_api_needs_login(client, admin_pw):
    assert client.get("/api/settings").status_code == 401
    assert client.get("/api/runs").status_code == 401 and client.get("/api/transactions").status_code == 401
    assert client.get("/docs").status_code == 401 and client.get("/openapi.json").status_code == 401
    assert client.get("/api/health").status_code == 200  # 살아 있는지는 누구나
    assert client.get("/api/auth/me").json() == {"auth": True, "public": False, "has_password": True, "role": None,
                                                 "share_enabled": False}
    assert _login(client, "wrong").status_code == 401
    r = _login(client)
    assert r.status_code == 200 and "httponly" in r.headers["set-cookie"].lower() and "samesite=strict" in r.headers["set-cookie"].lower()
    assert client.get("/api/settings").status_code == 200 and client.get("/api/auth/me").json()["role"] == "admin"
    client.post("/api/auth/logout")
    assert client.get("/api/settings").status_code == 401


def test_login_locks_after_repeated_failures(client, admin_pw):
    for _ in range(security.MAX_FAILS):
        assert _login(client, "nope").status_code == 401
    r = _login(client)  # 맞는 비밀번호도 잠긴 동안은 안 된다
    assert r.status_code == 429 and "분 뒤" in r.json()["detail"]


def test_changing_the_password_ends_old_sessions(client, admin_pw, monkeypatch):
    _login(client)
    assert client.get("/api/settings").status_code == 200
    monkeypatch.setenv("MLG_ADMIN_PASSWORD_HASH", security.hash_password("another long password"))
    assert client.get("/api/settings").status_code == 401


def test_viewer_enters_with_the_share_key_and_reads_everything_but_writes_nothing(client, admin_pw):
    _login(client)
    share = client.get("/api/auth/share").json()
    assert share["enabled"] is False and share["path"] == f"/share?k={share['key']}"
    assert client.post("/api/auth/share/enter", json={"key": share["key"]}).status_code == 403  # 아직 꺼짐
    client.put("/api/auth/share", json={"enabled": True})
    client.post("/api/auth/logout")

    assert client.get("/api/home").status_code == 401
    assert client.post("/api/auth/share/enter", json={"key": "guess"}).status_code == 403
    assert client.post("/api/auth/share/enter", json={"key": share["key"]}).status_code == 200
    assert client.get("/api/auth/me").json()["role"] == "viewer"
    # 관리자 화면을 읽기만 — 홈 · 거래 · 정기지출 · 예산 · 급여 · 소비 분석 · 설정
    for path in ("/api/home", "/api/transactions", "/api/recurring-items", "/api/budget", "/api/salary", "/api/settings",
                 "/api/llm/routes", "/api/runs", "/api/system"):
        assert client.get(path).status_code == 200, path
    # 서버 주소 · 키는 빼고 보낸다
    assert client.get("/api/llm/vllm").json()["url"] is None
    ocr = client.get("/api/ocr").json()
    assert ocr["url"] is None and "api_key" not in ocr
    # 공유 링크 · 키 · 문서 · DB 백업은 읽기도 막는다
    for path in ("/api/auth/share", "/docs", "/openapi.json", "/api/system/backup"):
        assert client.get(path).status_code == 403, path
    # 쓰기는 모두 막는다
    for method, path, body in (("post", "/api/transactions", {}), ("put", "/api/settings", {"payday": 1}),
                               ("put", "/api/auth/share", {"rotate": True}), ("post", "/api/salary", {}),
                               ("delete", "/api/runs/1", None), ("post", "/api/imports", None)):
        r = client.request(method.upper(), path, json=body)
        assert r.status_code == 403 and "읽기 전용" in r.json()["detail"], (method, path)
    assert client.post("/api/auth/logout").status_code == 200


def test_invest_app_cookies_do_not_open_the_ledger(client, admin_pw):
    """Mallot Invest 와 쿠키 이름 · 서명 키가 달라서, 그쪽 로그인 · 손님 쿠키를 들고 와도 가계부는 열리지 않는다."""
    client.cookies.set("mia_admin", "anything.signed")
    client.cookies.set("mia_viewer", "anything.signed")
    assert client.get("/api/home").status_code == 401
    assert security.ADMIN_COOKIE == "mlg_admin" and security.VIEWER_COOKIE == "mlg_viewer"


def test_rotating_the_key_or_turning_share_off_cuts_viewers(client, admin_pw):
    from fastapi.testclient import TestClient

    from app.main import app

    _login(client)
    key = client.put("/api/auth/share", json={"enabled": True}).json()["key"]
    with TestClient(app) as guest:
        assert guest.post("/api/auth/share/enter", json={"key": key}).status_code == 200
        assert guest.get("/api/home").status_code == 200
        new = client.put("/api/auth/share", json={"rotate": True}).json()["key"]
        assert new != key and guest.get("/api/home").status_code == 401
        assert guest.post("/api/auth/share/enter", json={"key": new}).status_code == 200
        client.put("/api/auth/share", json={"enabled": False})
        assert guest.get("/api/home").status_code == 401


def test_cross_site_writes_are_refused(client, admin_pw):
    _login(client)
    r = client.put("/api/auth/share", json={"enabled": True}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    assert client.put("/api/auth/share", json={"enabled": True}, headers={"Origin": "http://testserver"}).status_code == 200


def test_public_mode_without_password_fails_closed(client, monkeypatch):
    monkeypatch.setenv("MLG_PUBLIC", "1")
    assert client.get("/api/settings").status_code == 401
    assert _login(client, "anything").status_code == 403
