"""맨 도메인 고르기 화면 — MLG_PORTAL_HOST 로 온 요청은 링크 두 개만, 가계부 API 는 열리지 않는다."""

from app.auth import security


def test_portal_host_shows_chooser_and_hides_api(client, monkeypatch):
    monkeypatch.setenv("MLG_ADMIN_PASSWORD_HASH", security.hash_password("correct horse battery"))
    monkeypatch.setenv("MLG_PORTAL_HOST", "example.com")
    r = client.get("/", headers={"Host": "example.com"})
    assert r.status_code == 200 and 'href="https://ledger.example.com/"' in r.text and 'href="https://invest.example.com/"' in r.text
    api = client.get("/api/transactions", headers={"Host": "example.com"})
    assert api.status_code == 200 and "Mallot" in api.text and "transactions" not in api.text   # 데이터 대신 고르기 화면
    assert client.get("/api/transactions", headers={"Host": "ledger.example.com"}).status_code == 401  # 앱 주소는 그대로 로그인 필요


def test_portal_off_without_setting(client):
    assert client.get("/api/health", headers={"Host": "example.com"}).json()["ok"] is True
