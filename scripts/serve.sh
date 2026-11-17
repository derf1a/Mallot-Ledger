#!/usr/bin/env bash
# 프론트를 빌드한 뒤 백엔드 하나로 서빙한다. 기본은 이 컴퓨터에서만 (127.0.0.1).
# 같은 네트워크의 폰에서 열려면 HOST=0.0.0.0 — 로그인이 없는 앱이라 믿는 네트워크에서만.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${PORT:-8200}"
HOST="${HOST:-127.0.0.1}"

# .env 의 값 (셸 환경 변수가 없을 때) — 프론트 빌드와 백엔드가 같은 경로 접두사 · 홈 로그인 설정을 보게
dotenv() { { grep -E "^$1=" "$ROOT/.env" 2>/dev/null || true; } | tail -1 | cut -d= -f2- | sed -e "s/^[\"']//" -e "s/[\"']\$//"; }
export MLG_BASE_PATH="${MLG_BASE_PATH:-$(dotenv MLG_BASE_PATH)}"
export MLG_HOME_AUTH_URL="${MLG_HOME_AUTH_URL:-$(dotenv MLG_HOME_AUTH_URL)}"

if [ -d "$ROOT/frontend" ]; then (cd "$ROOT/frontend" && npm run build); fi
echo "[serve] http://localhost:$PORT"
cd "$ROOT/backend" && exec uv run uvicorn app.main:app --host "$HOST" --port "$PORT"
