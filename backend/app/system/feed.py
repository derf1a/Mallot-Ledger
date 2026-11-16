"""Mallot 홈 통합 대시보드에 주는 요약 (`/api/feed/*`) — mallot-home 이 이 컴퓨터 안에서 부른다.

- 열쇠: .env 의 MLG_FEED_TOKEN (32자 이상). 요청 머리 X-Mallot-Feed 가 같고, 터널 · 프록시를 거치지 않았고(127.0.0.1 직접),
  GET 이고, 경로가 /api/feed/ 이면 로그인 없이 읽는다 (auth/guard). 관리자는 로그인으로도 본다.
- 숫자만 준다: 금액 합계 · 건수 · 크기. 거래 한 줄 한 줄 · 가맹점 · 계좌는 보내지 않는다.
- 모양은 Mallot 앱들(가계부 · 투자 · 실험실)이 같다 — resources 는 공통, summary 만 앱마다 다르다.
"""

import hmac
import os
import resource
import sqlite3
import sys
import time
from datetime import date, datetime, timedelta
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from app.core import metrics
from app.core.db import data_dir, db_path

APP = "ledger"
TOKEN_ENV = "MLG_FEED_TOKEN"
HEADER = "x-mallot-feed"
PREFIX = "/api/feed/"
MIN_TOKEN = 32


def token_ok(headers, method: str, path: str, proxied: bool) -> bool:
    """홈 서버가 보낸 요청인가 — 열쇠가 맞고, 바깥을 거치지 않은 GET /api/feed/*."""
    want = os.environ.get(TOKEN_ENV, "")
    got = headers.get(HEADER, "")
    if len(want) < MIN_TOKEN or not got or proxied or method not in ("GET", "HEAD") or not path.startswith(PREFIX):
        return False
    return hmac.compare_digest(want.encode(), got.encode())


def app_version() -> str:
    try:
        return version("mallot-ledger")
    except PackageNotFoundError:
        return "0"


def _rss_bytes() -> int | None:
    try:
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return rss if sys.platform == "darwin" else rss * 1024
    except (OSError, ValueError):
        return None


def _dir_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def _since(days: int) -> str:
    return (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")


def llm_usage(conn: sqlite3.Connection, days: int = 30) -> dict:
    from app.llm.client import FEATURES, auth_mode

    since = _since(days)
    row = conn.execute(
        "SELECT COUNT(*) AS calls, SUM(ok) AS ok, SUM(1 - ok) AS failed, SUM(input_tokens) AS input_tokens, "
        "SUM(output_tokens) AS output_tokens, SUM(cost_usd) AS cost_usd, AVG(duration_ms) AS avg_duration_ms "
        "FROM llm_usage WHERE created_at >= ?", (since,)).fetchone()
    totals = {k: int(row[k] or 0) for k in ("calls", "ok", "failed", "input_tokens", "output_tokens")}
    totals["cost_usd"] = round(row["cost_usd"] or 0.0, 4)
    totals["avg_duration_ms"] = int(row["avg_duration_ms"]) if row["avg_duration_ms"] is not None else None
    durations = sorted(r[0] for r in conn.execute(
        "SELECT duration_ms FROM llm_usage WHERE created_at >= ? AND duration_ms IS NOT NULL", (since,)))
    totals["p95_duration_ms"] = durations[min(len(durations) - 1, int(len(durations) * 0.95))] if durations else None
    by_feature = [{"feature": r["feature"], "title": FEATURES.get(r["feature"], r["feature"]), "calls": r["calls"],
                   "cost_usd": round(r["cost_usd"] or 0.0, 4)}
                  for r in conn.execute("SELECT feature, COUNT(*) AS calls, SUM(cost_usd) AS cost_usd FROM llm_usage "
                                        "WHERE created_at >= ? GROUP BY feature ORDER BY calls DESC", (since,))]
    rows = {r["day"]: r for r in conn.execute(
        "SELECT substr(created_at, 1, 10) AS day, COUNT(*) AS calls, SUM(cost_usd) AS cost_usd FROM llm_usage "
        "WHERE created_at >= ? GROUP BY day", (since,))}
    daily = []
    for i in range(days - 1, -1, -1):
        d = (date.today() - timedelta(days=i)).isoformat()
        r = rows.get(d)
        daily.append({"day": d, "calls": r["calls"] if r else 0, "cost_usd": round((r["cost_usd"] or 0.0) if r else 0.0, 4)})
    return {"days": days, "auth_mode": auth_mode(), "totals": totals, "by_feature": by_feature, "daily": daily}


def runs_overview(conn: sqlite3.Connection) -> dict:
    running = conn.execute("SELECT COUNT(*) FROM runs WHERE status IN ('queued', 'running')").fetchone()[0]
    failed = conn.execute("SELECT COUNT(*) FROM runs WHERE status = 'failed' AND created_at >= ?", (_since(1),)).fetchone()[0]
    recent = [dict(r) for r in conn.execute(
        "SELECT id, kind, name, status, created_at, finished_at FROM runs ORDER BY id DESC LIMIT 5")]
    return {"running": running, "failed_24h": failed, "recent": recent}


def resources(conn: sqlite3.Connection) -> dict:
    path = db_path()
    return {
        "app": APP,
        "version": app_version(),
        "uptime_s": int(time.time() - metrics.STARTED_AT),
        "rss_bytes": _rss_bytes(),
        "db_bytes": path.stat().st_size if path.exists() else 0,
        "data_bytes": _dir_bytes(data_dir()),
        "llm": llm_usage(conn),
        "requests": metrics.snapshot(),
        "runs": runs_overview(conn),
    }


def summary(conn: sqlite3.Connection) -> dict:
    """이번 기간(월급일 기준) 숫자만 — 수입 · 정기지출 · 변동비 예산 · 쓴 돈."""
    from app.ledger.settings import current_period
    from app.ledger.summary import summary as period_summary

    s = period_summary(conn, current_period(conn))
    v, r = s["variable"], s["recurring"]
    return {
        "app": APP,
        "period": s["period"],
        "income": s["income"],
        "recurring": {"total": r["total"], "saving_total": r["saving_total"], "expense_total": r["expense_total"],
                      "missed": r["missed"]},
        "variable": {"pool": v["pool"], "budget_total": v["budget_total"], "spent_total": v["spent_total"],
                     "uncategorized": v["uncategorized"],
                     "categories": [{"name": c["name"], "icon": c["icon"], "budget": c["budget"], "spent": c["spent"]}
                                    for c in v["categories"]]},
        "transactions": conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0],
    }
