"""Mallot 고르기 화면 — 맨 도메인(예: mallot-ai.com)으로 들어오면 가계부 · 투자 중 하나를 고른다.

- .env 의 MLG_PORTAL_HOST 에 맨 도메인을 넣으면 켜진다 (비우면 꺼짐). 터널이 그 주소를 이 서버로 보내야 한다 (docs/share.md).
- 데이터 · 로그인 없이 링크 두 개만 보여 준다. 그 호스트로 온 다른 요청(API 포함)은 모두 이 화면으로 — 가계부 API 가 맨 도메인에서 열리지 않게.
- 링크는 ledger.<도메인> · invest.<도메인>. 로그인은 앱마다 따로다 (쿠키가 하위 도메인에만 붙는다).
"""

import html
import os

from fastapi import Request
from fastapi.responses import HTMLResponse

APPS = (("ledger", "가계부", "Mallot Ledger", "지출 · 고정비 · 급여 · 소비 분석"),
        ("invest", "투자", "Mallot Invest", "에이전트 운용 · 포트폴리오 · 거래"))


def portal_host() -> str:
    return os.environ.get("MLG_PORTAL_HOST", "").strip().lower().rstrip(".")


def render(host: str) -> str:
    cards = "".join(
        f'<a class="app" href="https://{key}.{html.escape(host)}/"><b>{ko}</b><span>{name}</span><small>{desc}</small></a>'
        for key, ko, name, desc in APPS)
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Mallot</title><meta name="robots" content="noindex"><style>
:root{{--bg:#f6f8f7;--card:#fff;--fg:#17211e;--muted:#5b6863;--line:#d9e1de;--accent:#1f6f5c}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0f1614;--card:#16201d;--fg:#e3ebe8;--muted:#93a39d;--line:#2a3733;--accent:#5cc4a4}}}}
*{{box-sizing:border-box}}body{{margin:0;min-height:100dvh;display:grid;place-items:center;background:var(--bg);color:var(--fg);
font-family:Pretendard,'Apple SD Gothic Neo','Malgun Gothic',system-ui,sans-serif;padding:16px}}
main{{width:min(560px,100%);display:flex;flex-direction:column;gap:16px}}h1{{margin:0;font-size:1.5rem}}h1 i{{color:var(--accent)}}
p{{margin:0;color:var(--muted)}}.apps{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}}
.app{{display:flex;flex-direction:column;gap:4px;padding:18px;border:1px solid var(--line);border-radius:14px;background:var(--card);
color:inherit;text-decoration:none}}.app:hover,.app:focus-visible{{border-color:var(--accent);outline:none}}
.app b{{font-size:1.2rem}}.app span{{color:var(--accent);font-weight:600}}.app small{{color:var(--muted)}}
</style></head><body><main><h1><i>M</i>allot</h1><p>어디로 갈까요? 로그인은 앱마다 따로예요.</p>
<div class="apps">{cards}</div></main></body></html>"""


async def portal(request: Request, call_next):
    """맨 도메인으로 온 요청이면 고르기 화면, 아니면 그대로."""
    host = portal_host()
    if host:
        got = (request.headers.get("x-forwarded-host") or request.headers.get("host") or "").split(":")[0].lower()
        if got == host:
            return HTMLResponse(render(host), headers={"Cache-Control": "no-store"})
    return await call_next(request)
