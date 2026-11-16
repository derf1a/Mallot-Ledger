"""Mallot 고르기 화면 — 맨 도메인(예: mallot-ai.com)으로 들어오면 가계부 · 투자 중 하나를 고른다. 휴대폰 홈 화면에 'Mallot' 앱으로 설치된다.

- .env 의 MLG_PORTAL_HOST 에 맨 도메인을 넣으면 켜진다 (비우면 꺼짐). 터널이 그 주소를 이 서버로 보내야 한다 (docs/share.md).
- 데이터 · 로그인 없이 링크 두 개만 보여 준다. 그 호스트로 온 다른 요청(API 포함)은 모두 이 화면으로 — 가계부 API 가 맨 도메인에서 열리지 않게.
- 앱 설치(PWA): /manifest.webmanifest (이름 Mallot, 시작 / ), 아이콘(빌드된 frontend/dist 의 favicon · apple-touch-icon · icon-192/512).
  홈 화면 앱을 열면 이 화면에서 시작한다. 가계부 · 투자는 다른 하위 도메인이라 휴대폰이 앱 안의 브라우저 화면으로 연다.
- 링크는 ledger.<도메인> · invest.<도메인>. 로그인은 앱마다 따로다 (쿠키가 하위 도메인에만 붙는다).
"""

import html
import json
import os
from pathlib import Path

from fastapi import Request
from fastapi.responses import FileResponse, HTMLResponse, Response

DIST = Path(__file__).resolve().parents[3] / "frontend" / "dist"
FILES = {"/favicon.svg": "image/svg+xml", "/apple-touch-icon.png": "image/png", "/icon-192.png": "image/png", "/icon-512.png": "image/png"}
APPS = (("ledger", "가계부", "Mallot Ledger", "지출 · 고정비 · 급여 · 소비 분석"),
        ("invest", "투자", "Mallot Invest", "에이전트 운용 · 포트폴리오 · 거래"))
THEME = "#0d3b3a"


def portal_host() -> str:
    return os.environ.get("MLG_PORTAL_HOST", "").strip().lower().rstrip(".")


def manifest() -> dict:
    return {"name": "Mallot", "short_name": "Mallot", "description": "가계부 · 투자", "id": "/", "start_url": "/", "scope": "/",
            "display": "standalone", "background_color": "#f6f8f7", "theme_color": THEME, "lang": "ko",
            "icons": [{"src": "/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
                      {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
                      {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
                      {"src": "/favicon.svg", "sizes": "any", "type": "image/svg+xml"}]}


def render(host: str) -> str:
    cards = "".join(
        f'<a class="app" href="https://{key}.{html.escape(host)}/"><b>{ko}</b><span>{name}</span><small>{desc}</small></a>'
        for key, ko, name, desc in APPS)
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Mallot</title><meta name="robots" content="noindex"><meta name="theme-color" content="{THEME}">
<link rel="manifest" href="/manifest.webmanifest"><link rel="icon" type="image/svg+xml" href="/favicon.svg">
<link rel="apple-touch-icon" href="/apple-touch-icon.png"><meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes"><meta name="apple-mobile-web-app-title" content="Mallot">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent"><style>
:root{{--bg:#f6f8f7;--card:#fff;--fg:#17211e;--muted:#5b6863;--line:#d9e1de;--accent:#1f6f5c}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0f1614;--card:#16201d;--fg:#e3ebe8;--muted:#93a39d;--line:#2a3733;--accent:#5cc4a4}}}}
*{{box-sizing:border-box}}body{{margin:0;min-height:100dvh;display:grid;place-items:center;background:var(--bg);color:var(--fg);
font-family:Pretendard,'Apple SD Gothic Neo','Malgun Gothic',system-ui,sans-serif;
padding:max(16px,env(safe-area-inset-top)) max(16px,env(safe-area-inset-right)) max(16px,env(safe-area-inset-bottom)) max(16px,env(safe-area-inset-left))}}
main{{width:min(560px,100%);display:flex;flex-direction:column;gap:16px}}
.brand{{display:flex;align-items:center;gap:12px}}.brand img{{width:44px;height:44px}}h1{{margin:0;font-size:1.6rem}}
p{{margin:0;color:var(--muted)}}.apps{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}}
.app{{display:flex;flex-direction:column;gap:4px;padding:20px;border:1px solid var(--line);border-radius:14px;background:var(--card);
color:inherit;text-decoration:none}}.app:hover,.app:focus-visible{{border-color:var(--accent);outline:none}}
.app b{{font-size:1.25rem}}.app span{{color:var(--accent);font-weight:600}}.app small{{color:var(--muted)}}
</style></head><body><main><div class="brand"><img src="/favicon.svg" alt=""><h1>Mallot</h1></div>
<p>어디로 갈까요? 로그인은 앱마다 따로예요.</p><div class="apps">{cards}</div>
<p style="font-size:.8rem">휴대폰: 공유 → 홈 화면에 추가 하면 'Mallot' 앱으로 이 화면에서 시작해요.</p></main></body></html>"""


async def portal(request: Request, call_next):
    """맨 도메인으로 온 요청이면 고르기 화면 · 앱 설치 파일, 아니면 그대로."""
    host = portal_host()
    if host:
        got = (request.headers.get("x-forwarded-host") or request.headers.get("host") or "").split(":")[0].lower()
        if got == host:
            path = request.url.path
            if path == "/manifest.webmanifest":
                return Response(json.dumps(manifest(), ensure_ascii=False), media_type="application/manifest+json")
            if path in FILES and (DIST / path.lstrip("/")).is_file():
                return FileResponse(DIST / path.lstrip("/"), media_type=FILES[path], headers={"Cache-Control": "public, max-age=86400"})
            return HTMLResponse(render(host), headers={"Cache-Control": "no-store"})
    return await call_next(request)
