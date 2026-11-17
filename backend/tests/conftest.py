import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def runs_sync(monkeypatch):
    """작업(보고서 · 재평가)을 백그라운드 스레드 대신 즉시 실행한다."""
    from app.runs import runner

    monkeypatch.setattr(runner, "SYNC", True)


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    """테스트는 실제 data/ledger.db 대신 임시 DB를 쓴다."""
    path = tmp_path / "test.db"
    monkeypatch.setenv("MLG_DB_PATH", str(path))
    return path


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    """실제 .env·셸의 키를 테스트에 끌어오지 않는다."""
    monkeypatch.setenv("MLG_ENV_FILE", str(tmp_path / ".env"))
    monkeypatch.setenv("MLG_SERVICES", "0")  # 백그라운드 서비스를 띄우지 않는다
    for key in ("ANTHROPIC_API_KEY", "MLG_VLLM_URL", "MLG_VLLM_API_KEY", "LANGSMITH_API_KEY", "MLG_MODELS_DIR",
                "MLG_ADMIN_PASSWORD", "MLG_ADMIN_PASSWORD_HASH", "MLG_FEED_TOKEN", "MLG_PUBLIC", "MLG_SESSION_SECRET",
                "MLG_OCR_URL", "MLG_OCR_API_KEY", "MLG_OCR_MODE", "MLG_OCR_MODEL", "MLG_BASE_PATH", "MLG_HOME_AUTH_URL"):
        monkeypatch.delenv(key, raising=False)
    from app.auth import security

    security.reset_failures()
    security.reset_home_cache()
    yield


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """테스트는 바깥 HTTP(net.HTTP_REQUEST)로 나가지 않는다 — 연결 실패처럼 답한다. 필요한 테스트는 가짜로 바꿔 끼운다."""
    from app.core import net
    monkeypatch.setattr(net, "HTTP_REQUEST", lambda *a, **kw: (0, b"blocked in tests"))


@pytest.fixture
def client():
    from app.main import app

    with TestClient(app) as c:
        yield c
