"""OCR(Unlimited-OCR-2) — OpenAI 호환 요청 모양 · 판독 방식 · 캡쳐 판독기 고르기 · OCR → LLM 판독 · 실패 처리."""

import asyncio
import json

from app.capture import extractor as ex
from app.ocr import client as ocr


def _fake_server(monkeypatch, content="2026.10.05 스타벅스 4,500원", status=200):
    calls = []

    def http(method, url, body=None, timeout=0):
        calls.append((method, url, body))
        if url.endswith("/models"):
            return 200, json.dumps({"data": [{"id": "Unlimited-OCR-2"}]}).encode()
        return status, json.dumps({"model": "Unlimited-OCR-2", "choices": [{"message": {"content": content}}],
                                   "usage": {"completion_tokens": 12}}).encode()
    monkeypatch.setattr(ocr, "HTTP", http)
    return calls


def test_read_text_sends_openai_compatible_image_request(monkeypatch):
    monkeypatch.setenv("MLG_OCR_URL", "http://gpu:10000/v1/")
    calls = _fake_server(monkeypatch)
    out = ocr.read_text(b"\x89PNG", "image/png")
    assert out["text"] == "2026.10.05 스타벅스 4,500원" and out["model"] == "Unlimited-OCR-2" and out["tokens"] == 12
    method, url, body = calls[0]
    assert (method, url) == ("POST", "http://gpu:10000/v1/chat/completions") and body["model"] == "Unlimited-OCR-2"
    parts = body["messages"][0]["content"]
    assert parts[0]["image_url"]["url"].startswith("data:image/png;base64,") and body["crop_mode"] is True
    monkeypatch.setenv("MLG_OCR_CROP_MODE", "0")
    ocr.read_text(b"x", "image/png")
    assert calls[-1][2]["crop_mode"] is False
    monkeypatch.setenv("MLG_OCR_CROP_MODE", "omit")
    ocr.read_text(b"x", "image/png")
    assert "crop_mode" not in calls[-1][2]


def test_modes_and_errors(monkeypatch):
    assert ocr.mode() == "auto" and not ocr.enabled()                                   # 주소가 없으면 Vision
    monkeypatch.setenv("MLG_OCR_URL", "http://gpu:10000/v1")
    assert ocr.enabled()
    monkeypatch.setenv("MLG_OCR_MODE", "vision")
    assert not ocr.enabled()
    monkeypatch.setenv("MLG_OCR_MODE", "ocr")
    _fake_server(monkeypatch, content="")
    try:
        ocr.read_text(b"x", "image/png")
        raise AssertionError("빈 글은 실패")
    except ocr.OcrError as e:
        assert "아무 글자도" in str(e)
    monkeypatch.setattr(ocr, "HTTP", lambda *a, **k: (0, b"refused"))
    assert ocr.status()["reachable"] is False


def test_get_extractor_picks_by_mode(monkeypatch):
    assert isinstance(ex.get_extractor(), ex.AgentSdkExtractor)
    monkeypatch.setenv("MLG_OCR_URL", "http://gpu:10000/v1")
    got = ex.get_extractor()
    assert isinstance(got, ex.OcrLlmExtractor) and isinstance(got.fallback, ex.AgentSdkExtractor)
    assert got.model.startswith("Unlimited-OCR-2+")
    monkeypatch.setenv("MLG_OCR_MODE", "ocr")
    assert ex.get_extractor().fallback is None


def _ctx():
    from datetime import date
    return ex.ExtractContext(today=date(2026, 11, 16), categories=[{"name": "커피", "description": "카페"}], own_accounts=[])


def test_ocr_llm_extractor_reads_text_then_structures(monkeypatch):
    monkeypatch.setenv("MLG_OCR_URL", "http://gpu:10000/v1")
    _fake_server(monkeypatch)
    seen = {}

    async def fake_structured(feature, prompt, schema, **kw):
        seen["feature"], seen["prompt"] = feature, prompt
        return {"transactions": [{"occurred_on": "2026-10-05", "type": "expense", "amount": 4500, "merchant": "스타벅스"}]}
    monkeypatch.setattr(ex, "structured", fake_structured)
    e = ex.OcrLlmExtractor()
    out = asyncio.run(e.extract(b"img", "image/png", _ctx()))
    assert out[0]["amount"] == 4500 and seen["feature"] == "ocr_structure"
    assert "[OCR 글]" in seen["prompt"] and "스타벅스 4,500원" in seen["prompt"] and "아래 글은" in seen["prompt"]
    assert e.last_text == "2026.10.05 스타벅스 4,500원" and e.prompt_version == ex.OCR_PROMPT_VERSION


def test_ocr_failure_falls_back_to_vision_and_is_logged(client, monkeypatch):
    """auto: OCR 서버가 죽어 있으면 Vision 으로 읽고, 판독 기록에 그 경로를 남긴다."""
    from app.core.db import connect
    from app.main import app

    monkeypatch.setenv("MLG_OCR_URL", "http://gpu:10000/v1")
    monkeypatch.setattr(ocr, "HTTP", lambda *a, **k: (0, b"connection refused"))

    class FakeVision:
        model = "claude-fake"

        async def extract(self, image, media_type, ctx):
            return [{"occurred_on": "2026-10-05", "type": "expense", "transfer_kind": None, "amount": 4500, "merchant": "스타벅스",
                     "category": "커피", "payment_method": ""}]
    app.dependency_overrides[ex.get_extractor] = lambda: ex.OcrLlmExtractor(fallback=FakeVision())
    try:
        r = client.post("/api/transactions/extract", files={"image": ("a.png", b"\x89PNG", "image/png")})
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 200, r.text
    with connect() as conn:
        row = conn.execute("SELECT model, prompt_version, note, ocr_text FROM extraction_logs").fetchone()
    assert row["model"] == "claude-fake" and row["prompt_version"] == ex.PROMPT_VERSION
    assert row["note"].startswith("OCR 실패 → Vision") and row["ocr_text"] is None


def test_ocr_api_hides_address_from_guests_and_tests_an_image(client, monkeypatch):
    monkeypatch.setenv("MLG_OCR_URL", "http://gpu:10000/v1")
    _fake_server(monkeypatch)
    st = client.get("/api/ocr").json()
    assert st["url"] == "http://gpu:10000/v1" and st["reachable"] is True and st["served"] == ["Unlimited-OCR-2"]
    r = client.post("/api/ocr/test", files={"file": ("a.png", b"\x89PNG", "image/png")})
    assert r.status_code == 200 and "스타벅스" in r.json()["text"]
    assert client.post("/api/ocr/test", files={"file": ("a.txt", b"x", "text/plain")}).status_code == 415
