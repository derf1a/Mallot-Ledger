"""홈 통합 로그인(MLG_HOME_AUTH_URL) — 역할은 Mallot 홈에 묻고, 앱 자체 로그인 · 공유 링크는 닫는다. 홈 호출은 가짜."""

import io
import json
import urllib.error

import pytest

from app.auth import security

PROXY = {"Cf-Connecting-IP": "203.0.113.7"}
HOME = "http://127.0.0.1:8300"


@pytest.fixture
def home(monkeypatch):
    """홈 모드 + 가짜 home_role — 세션 값이 곧 역할 ('admin' · 'viewer' · 'down' 이면 장애)."""
    monkeypatch.setenv("MLG_HOME_AUTH_URL", HOME)
    asked: list = []

    def fake(session):
        asked.append(session)
        if session == "down":
            raise security.HomeUnavailable("연결 실패")
        return session if session in ("admin", "viewer") else None

    monkeypatch.setattr(security, "home_role", fake)
    return asked


def _as(client, session):
    client.cookies.set(security.HOME_COOKIE, session)


def test_home_admin_opens_everything(client, home):
    _as(client, "admin")
    assert client.get("/api/settings", headers=PROXY).status_code == 200
    assert client.put("/api/settings", json={"payday": 1}, headers=PROXY).status_code == 200
    assert client.get("/api/auth/access", headers=PROXY).status_code == 200
    assert home and home[-1] == "admin"


def test_home_viewer_reads_only(client, home):
    _as(client, "viewer")
    assert client.get("/api/home", headers=PROXY).status_code == 200
    r = client.put("/api/settings", json={"payday": 1}, headers=PROXY)
    assert r.status_code == 403 and "읽기 전용" in r.json()["detail"]
    for path in ("/api/auth/access", "/api/system/backup", "/docs"):
        assert client.get(path, headers=PROXY).status_code == 403, path


def test_home_no_role_gets_login_url(client, home):
    r = client.get("/api/home", headers=PROXY)  # 쿠키 없음
    assert r.status_code == 401 and r.json() == {"detail": "로그인해 주세요", "login_url": "/login"}
    _as(client, "stranger")
    assert client.get("/api/home", headers=PROXY).status_code == 401


def test_home_down_fails_closed(client, home):
    _as(client, "down")
    r = client.get("/api/home", headers=PROXY)
    assert r.status_code == 503 and r.json()["detail"] == "Mallot 홈 로그인 서버에 연결하지 못했어요"
    assert client.get("/api/auth/me", headers=PROXY).status_code == 503
    assert client.get("/api/health", headers=PROXY).status_code == 200


def test_home_not_proxied_is_admin(client, home):
    """터널 · 프록시를 거치지 않은 요청(이 컴퓨터 안 127.0.0.1)은 홈에 묻지 않고 관리자."""
    assert client.get("/api/settings").status_code == 200
    assert client.get("/api/auth/me").json()["role"] == "admin"
    assert home == []


def test_home_mode_closes_app_login_and_share(client, home, monkeypatch):
    monkeypatch.setenv("MLG_ADMIN_PASSWORD", "correct horse battery")
    _as(client, "admin")
    for method, path, body in (("POST", "/api/auth/login", {"password": "correct horse battery"}),
                               ("POST", "/api/auth/logout", None), ("POST", "/api/auth/share/enter", {"key": "x"}),
                               ("GET", "/api/auth/share", None), ("PUT", "/api/auth/share", {"enabled": True})):
        for headers in ({}, PROXY):
            r = client.request(method, path, json=body, headers=headers)
            assert r.status_code == 409 and r.json()["detail"] == "Mallot 홈에서 로그인 · 관리해요", (method, path)


def test_home_me_shape(client, home):
    _as(client, "viewer")
    assert client.get("/api/auth/me", headers=PROXY).json() == {
        "auth": True, "public": False, "has_password": False, "role": "viewer", "share_enabled": False,
        "home": True, "login_url": "/login", "logout_url": "/logout"}
    client.cookies.clear()
    assert client.get("/api/auth/me", headers=PROXY).json()["role"] is None


def test_home_mode_keeps_cross_site_check(client, home):
    _as(client, "admin")
    r = client.put("/api/settings", json={"payday": 1}, headers={**PROXY, "Origin": "https://evil.example"})
    assert r.status_code == 403


def test_home_mode_keeps_feed_token(client, home, monkeypatch):
    monkeypatch.setenv("MLG_FEED_TOKEN", "f" * 40)
    assert client.get("/api/feed/resources", headers={"X-Mallot-Feed": "f" * 40}).status_code == 200


# ---- home_role 자체 (urllib 를 가짜로) ----

class _Res(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


@pytest.fixture
def urlopen(monkeypatch):
    monkeypatch.setenv("MLG_HOME_AUTH_URL", HOME + "/")
    monkeypatch.setenv("MLG_FEED_TOKEN", "k" * 40)
    calls: list = []
    answer: dict = {"role": "admin"}

    def fake(req, timeout):
        calls.append((req.full_url, dict(req.header_items()), timeout))
        if isinstance(answer.get("error"), Exception):
            raise answer["error"]
        return _Res(json.dumps({"role": answer["role"]}).encode())

    monkeypatch.setattr(security.urllib.request, "urlopen", fake)
    return calls, answer


def test_home_role_asks_home_with_key_and_session(urlopen):
    calls, _ = urlopen
    assert security.home_role("sess-1") == "admin"
    url, headers, timeout = calls[0]
    assert url == f"{HOME}/internal/auth/check?app=ledger" and timeout == 2.0
    assert headers["X-mallot-feed"] == "k" * 40 and headers["X-mallot-session"] == "sess-1"


def test_home_role_caches_and_skips_missing_cookie(urlopen):
    calls, answer = urlopen
    assert security.home_role(None) is None and security.home_role("") is None and calls == []
    assert security.home_role("sess-1") == "admin"
    answer["role"] = "viewer"
    assert security.home_role("sess-1") == "admin"  # 10초 캐시
    assert security.home_role("sess-2") == "viewer"
    assert len(calls) == 2
    assert all("sess" not in k for k in security._home_cache)  # 세션 값 대신 sha256 을 키로


def test_home_role_unknown_role_is_none(urlopen):
    _, answer = urlopen
    answer["role"] = "root"
    assert security.home_role("sess-x") is None


@pytest.mark.parametrize("error", [urllib.error.URLError("refused"), TimeoutError("slow"),
                                   urllib.error.HTTPError(HOME, 401, "bad key", {}, None)])
def test_home_role_errors_raise(urlopen, error):
    _, answer = urlopen
    answer["error"] = error
    with pytest.raises(security.HomeUnavailable):
        security.home_role("sess-err")
