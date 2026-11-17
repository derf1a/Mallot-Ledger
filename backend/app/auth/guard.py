"""요청마다 역할을 검사하는 미들웨어 (main.py 가 붙인다).

- 권한이 꺼져 있으면(비밀번호 없음 · 공개 아님) 지금처럼 열려 있다. 단, 터널 · 프록시를 거친 API 요청은 막는다.
- 켜져 있으면: 로그인 · 입장 · 상태 확인은 누구나. 관리자는 모두.
  손님(공유 링크)은 관리자 화면을 읽기만 한다 — GET 은 열고, 쓰기(POST · PUT · DELETE)는 모두 403.
  손님에게도 닫는 GET: 공유 링크 · 키(/api/auth/share), /docs. 설정의 키 값은 라우터가 빼고 보낸다 (core/access.is_viewer).
- 쓰기 요청(POST · PUT · DELETE)은 Origin 이 있으면 이 사이트여야 한다 (다른 사이트에서 몰래 보내는 요청 막기).
- Mallot 홈 서버는 열쇠(MLG_FEED_TOKEN)로 /api/feed/* 만 읽는다 (system/feed.token_ok).
- 역할은 request.state.role 에 넣는다 (라우터가 손님용으로 값을 줄일 때).
- 홈 모드(MLG_HOME_AUTH_URL)면 역할을 Mallot 홈에 묻는다 (_home_guard). 앱 자체 로그인 · 공유 링크 API 는 409.
"""

from urllib.parse import urlsplit

from fastapi import Request
from fastapi.responses import JSONResponse

from app.auth import security
from app.system.feed import token_ok

OPEN_API = {"/api/health", "/api/auth/login", "/api/auth/logout", "/api/auth/me", "/api/auth/share/enter"}
DOC_PATHS = ("/docs", "/redoc", "/openapi.json")
VIEWER_CLOSED = ("/api/auth/share", "/api/auth/access", "/api/system/backup", *DOC_PATHS)  # 손님에게는 읽기도 닫는다 (DB 통째 내려받기 포함)
READ_METHODS = ("GET", "HEAD", "OPTIONS")
HOME_OPEN_API = {"/api/health", "/api/auth/me"}
# 홈 모드에서 닫는 앱 자체 로그인 · 손님 공유 API (비밀번호는 .env 로만 정해서 API 가 없다)
HOME_CLOSED = ("/api/auth/login", "/api/auth/logout", "/api/auth/share")


def _same_origin(request: Request) -> bool:
    origin = request.headers.get("origin")
    if not origin:
        return True
    host = (request.headers.get("host") or "").lower()  # Host 만 — X-Forwarded-Host 는 손님이 마음대로 보낼 수 있다
    return urlsplit(origin).netloc.lower() == host


def _deny(status: int, detail: str, **extra) -> JSONResponse:
    return JSONResponse({"detail": detail, **extra}, status_code=status)


async def _viewer_or_deny(request: Request, call_next, role: str | None, path: str, unauthorized: JSONResponse):
    """역할로 열거나 막는다 — 관리자는 모두, 손님은 GET 만(VIEWER_CLOSED 제외), 그 밖은 unauthorized."""
    request.state.role = role
    if role == "admin":
        return await call_next(request)
    if role != "viewer":
        return unauthorized
    if request.method not in READ_METHODS:
        return _deny(403, "읽기 전용이에요 — 손님은 설정 · 주문 · 대화를 바꿀 수 없어요")
    if path.startswith(VIEWER_CLOSED):
        return _deny(403, "관리자만 볼 수 있어요")
    return await call_next(request)


async def _home_guard(request: Request, call_next, path: str):
    """홈 모드 — 로그인 · 손님 공유는 Mallot 홈이 맡고, 여기서는 홈이 알려 준 역할로 연다."""
    if request.method not in READ_METHODS and not _same_origin(request):
        return _deny(403, "다른 사이트에서 온 요청이에요")
    if path.startswith(HOME_CLOSED):
        return _deny(409, "Mallot 홈에서 로그인 · 관리해요")
    if path in HOME_OPEN_API:
        return await call_next(request)  # /api/auth/me 는 라우터가 역할을 직접 묻는다
    try:
        role = security.home_request_role(request.headers, request.cookies)
    except security.HomeUnavailable:
        return _deny(503, "Mallot 홈 로그인 서버에 연결하지 못했어요")
    return await _viewer_or_deny(request, call_next, role, path,
                                 _deny(401, "로그인해 주세요", login_url=security.HOME_LOGIN_URL))


async def guard(request: Request, call_next):
    path = request.url.path
    guarded = path.startswith("/api/") or path.startswith(DOC_PATHS)
    if not guarded:
        return await call_next(request)
    if token_ok(request.headers, request.method, path, security.proxied(request.headers)):
        request.state.role = "feed"  # Mallot 홈 서버 (이 컴퓨터 안, 열쇠 · GET /api/feed/* 만)
        return await call_next(request)
    if security.home_mode():
        return await _home_guard(request, call_next, path)
    if not security.enabled():
        if security.proxied(request.headers):
            return _deny(403, "관리자 비밀번호 없이 외부에서 열 수 없어요 — MLG_ADMIN_PASSWORD_HASH 를 정하세요")
        request.state.role = "admin"
        return await call_next(request)
    reading = request.method in READ_METHODS
    if not reading and not _same_origin(request):
        return _deny(403, "다른 사이트에서 온 요청이에요")
    if path in OPEN_API:
        return await call_next(request)
    return await _viewer_or_deny(request, call_next, security.role_of(request.cookies), path,
                                 _deny(401, "로그인하거나 공유 링크로 들어와 주세요"))
