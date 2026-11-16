"""개인설정 읽기와 설정에 기대는 판단 — 수입일 기준 기간, 내 계좌, 빌린 돈 상대."""

import json
import sqlite3
from datetime import date

from app.core.periods import Period, period_for

DEFAULT_SETTINGS = {"owner_name": "나", "monthly_income": 0, "payday": 25, "loan_counterparties": "",
                    "search_months": 12}


def loan_counterparty(conn: sqlite3.Connection, counterparty: str) -> bool:
    """설정 > '빌린 돈을 받는 상대' 키워드(쉼표 구분)에 맞는지. 이 상대에게서 받은 입금은 수입이 아니라 빌린 돈(±0)이다.
    갚는 출금은 내 계좌 이체가 아니므로 정기지출(예: 부모님 상환) 매칭 대상으로 남는다."""
    text = counterparty.lower()
    return any(k in text for k in split_keywords(str(get_settings(conn).get("loan_counterparties") or "")))


def get_settings(conn: sqlite3.Connection) -> dict:
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    return {**DEFAULT_SETTINGS, **{r["key"]: json.loads(r["value"]) for r in rows}}


def current_period(conn: sqlite3.Connection, on: date | None = None) -> Period:
    return period_for(on or date.today(), int(get_settings(conn)["payday"]))


def split_keywords(raw: str) -> list[str]:
    return [k.strip().lower() for k in raw.split(",") if k.strip()]


def is_own_account(conn: sqlite3.Connection, counterparty: str) -> bool:
    text = counterparty.lower()
    for row in conn.execute("SELECT name, keyword FROM accounts"):
        if any(k in text for k in split_keywords(row["keyword"]) or [row["name"].lower()]):
            return True
    return False
