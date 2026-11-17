"""경로 접두사 (MLG_BASE_PATH, 예: /ledger) — 한 도메인의 경로 아래에서 돌 때 앞의 접두사를 뗀다.

- Cloudflare 터널은 `<도메인>/ledger/...` 를 경로 그대로 이 앱 포트로 보낸다 → 앱이 `/ledger` 를 떼고 처리한다.
- 비어 있으면(개발 · 공개 저장소 · 테스트 기본값) 아무것도 하지 않는다 — 지금처럼 루트에서 돈다.
- 맨 바깥 순수 ASGI 미들웨어라 인증 guard 와 라우터는 뗀 경로(`/api/...`)만 본다.
  - 경로가 접두사와 같으면(`/ledger`) `/ledger/` 로 307 (쿼리는 그대로).
  - `/ledger/` 로 시작하면 떼고 `raw_path` 도 맞춘다.
  - 접두사가 없으면 그대로 — 127.0.0.1:포트 로 직접 연 요청, 홈의 `/api/feed/*` 호출.
- root_path 는 건드리지 않는다 (Starlette 가 뗀 경로를 한 번 더 떼지 않게 — 앱 화면 경로 `/ledger/budget` 가 있다).
- 환경 변수는 요청마다 읽는다 (.env 는 시작한 뒤에 읽히고, 테스트가 바꿔 끼운다).
"""

import os

ENV = "MLG_BASE_PATH"


def base_path() -> str:
    """정리한 접두사 — 앞에 '/', 끝 '/' 없음. 없으면 ''."""
    raw = os.environ.get(ENV, "").strip().strip("/")
    return f"/{raw}" if raw else ""


class BasePathMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        base = base_path()
        if not base or scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        path: str = scope["path"]
        if path == base:
            if scope["type"] == "http":
                return await _redirect(scope, send, base + "/")
            path = base + "/"  # 웹소켓은 돌려보낼 수 없으니 화면 첫 경로로 본다
        if path.startswith(base + "/"):
            scope = dict(scope)
            scope["path"] = path[len(base):]
            raw = scope.get("raw_path")
            prefix = base.encode()
            scope["raw_path"] = raw[len(prefix):] if raw and raw.startswith(prefix + b"/") else scope["path"].encode()
        return await self.app(scope, receive, send)


async def _redirect(scope, send, location: str) -> None:
    query = scope.get("query_string") or b""
    target = location.encode() + (b"?" + query if query else b"")
    await send({"type": "http.response.start", "status": 307,
                "headers": [(b"location", target), (b"content-length", b"0")]})
    await send({"type": "http.response.body", "body": b""})
