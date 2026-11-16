"""OCR — Unlimited-OCR-2 (baidu/Unlimited-OCR-2, MIT, 2026-10) 를 OpenAI 호환 서버로 부른다.

- 모델은 GPU 가 있는 곳에서 SGLang(권장) · vLLM 으로 띄운다 (docs/ocr.md). 이 앱은 /v1/chat/completions 로 이미지를 보내
  글자(마크다운 비슷한 판독 결과)만 받는다. 거래 · 급여 칸으로 나누는 일은 LLM 이 판독 글을 보고 한다 (capture.extractor).
- 주소 · 키는 .env 로만 (MLG_OCR_URL · MLG_OCR_API_KEY) — 화면에서 바꿀 수 있으면 캡쳐 이미지(카드 내역 · 급여명세서)를 다른 서버로
  보내게 만들 수 있어서다. 집 안 네트워크 · 내 GPU 서버를 쓰므로 공인 주소 검사는 하지 않는다.
- 판독 방식 MLG_OCR_MODE: auto(주소가 있으면 OCR, 없으면 Vision) · ocr(OCR 만, 주소가 없으면 실패) · vision(OCR 안 씀).
- crop_mode(MLG_OCR_CROP_MODE, 기본 1): 모델 카드의 서버 요청 플래그 — 켜면 한 쪽을 잘게 나눠 읽는다(gundam). 휴대폰 캡쳐처럼
  세로로 긴 이미지에 맞다. omit 이면 요청에 넣지 않는다(서버 빌드가 이 칸을 모를 때).
"""

import base64
import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Callable

TIMEOUT = 180
MODES = ("auto", "ocr", "vision")
DEFAULT_MODEL = "Unlimited-OCR-2"
DEFAULT_PROMPT = "Parse this page."


class OcrError(Exception):
    pass


def base_url() -> str:
    return os.environ.get("MLG_OCR_URL", "").strip().rstrip("/")


def model() -> str:
    return os.environ.get("MLG_OCR_MODEL", "").strip() or DEFAULT_MODEL


def mode() -> str:
    m = os.environ.get("MLG_OCR_MODE", "").strip().lower()
    return m if m in MODES else "auto"


def enabled() -> bool:
    """캡쳐 판독에 OCR 을 쓰는가."""
    return mode() != "vision" and bool(base_url())


def crop_mode() -> bool | None:
    """True · False · None(요청에 넣지 않음 — 서버 빌드가 이 칸을 모를 때 MLG_OCR_CROP_MODE=omit)."""
    v = os.environ.get("MLG_OCR_CROP_MODE", "1").strip().lower()
    if v == "omit":
        return None
    return v not in ("0", "false", "no", "off")


# ---------- HTTP (테스트에서 바꿔 끼운다) ----------

def _http(method: str, url: str, body: dict | None = None, timeout: float = TIMEOUT) -> tuple[int, bytes]:
    headers = {"Content-Type": "application/json"}
    if key := os.environ.get("MLG_OCR_API_KEY", "").strip():
        headers["Authorization"] = f"Bearer {key}"
    data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — 주소는 .env 의 사용자 값뿐
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except (urllib.error.URLError, OSError, ValueError) as e:
        return 0, str(e).encode()


HTTP: Callable[..., tuple[int, bytes]] = _http


def _call(path: str, body: dict | None = None, method: str = "POST", timeout: float = TIMEOUT) -> dict:
    url = base_url()
    if not url:
        raise OcrError("OCR 서버 주소가 없어요 — .env 에 MLG_OCR_URL 을 넣으세요 (예: http://gpu-box:10000/v1)")
    status, raw = HTTP(method, url + path, body, timeout)
    if status == 0:
        raise OcrError(f"OCR 서버 연결 실패: {raw.decode(errors='replace')[:200]}")
    try:
        data = json.loads(raw or b"{}")
    except ValueError:
        data = {}
    if status >= 400:
        err = data.get("error") if isinstance(data, dict) else None
        msg = (err.get("message") if isinstance(err, dict) else err) or raw.decode(errors="replace")
        raise OcrError(f"OCR 서버 오류 {status}: {str(msg)[:300]}")
    return data


def read_text(image: bytes, media_type: str, prompt: str | None = None) -> dict:
    """이미지 한 장 → {"text", "model", "duration_ms", "tokens"}. 실패하면 OcrError."""
    url = "data:%s;base64,%s" % (media_type, base64.b64encode(image).decode())
    body = {
        "model": model(),
        "messages": [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": url}},
            {"type": "text", "text": prompt or os.environ.get("MLG_OCR_PROMPT", "").strip() or DEFAULT_PROMPT},
        ]}],
        "temperature": 0,
        "max_tokens": 8192,
    }
    if (crop := crop_mode()) is not None:
        body["crop_mode"] = crop
    started = time.perf_counter()
    data = _call("/chat/completions", body)
    try:
        text = data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        raise OcrError("OCR 서버 응답에 글이 없어요 (choices[0].message.content)") from None
    if isinstance(text, list):  # 일부 서버는 content 를 조각 목록으로 준다
        text = "".join(p.get("text", "") for p in text if isinstance(p, dict))
    text = str(text).strip()
    if not text:
        raise OcrError("OCR 이 아무 글자도 읽지 못했어요")
    usage = data.get("usage") or {}
    return {"text": text, "model": data.get("model") or model(), "duration_ms": int((time.perf_counter() - started) * 1000),
            "tokens": usage.get("completion_tokens")}


def status(timeout: float = 5) -> dict:
    """설정 화면용 — 주소가 있으면 /models 로 살아 있는지 본다."""
    out = {"mode": mode(), "model": model(), "configured": bool(base_url()), "enabled": enabled(), "crop_mode": crop_mode(),
           "reachable": None, "error": None}
    if not base_url():
        return out
    try:
        data = _call("/models", method="GET", timeout=timeout)
        names = [m.get("id") for m in data.get("data") or [] if isinstance(m, dict)]
        out.update(reachable=True, served=names)
    except OcrError as e:
        out.update(reachable=False, error=str(e))
    return out
