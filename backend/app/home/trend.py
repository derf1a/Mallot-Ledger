"""홈 화면의 추세·세부 자료 — 요약(ledger.summary)에 없는 것만.

- 날마다 쓴 변동비(이번 기간·바로 앞 기간)와 그날 큰 결제 몇 건: 누적 그림과 날짜별 설명
- 카테고리마다 지난 기간 사용액·결제 수·많이 쓴 곳: 예산 줄에 마우스를 올리면 보이는 설명
- 최근 기간들의 변동비·수입·정기지출 흐름

변동비는 가계부 요약과 같은 정의(ledger.VARIABLE_WHERE)라 홈의 숫자끼리 어긋나지 않는다.
"""

import sqlite3
from collections import defaultdict
from datetime import date, timedelta

from app.core.periods import Period
from app.insights.facts import label, periods_before
from app.ledger.rules import VARIABLE_WHERE
from app.ledger.settings import get_settings

TOP_PER_DAY = 3
TOP_MERCHANTS = 3
HISTORY = 6  # 이번 기간 포함


def _rows(conn: sqlite3.Connection, p: Period) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT occurred_on, amount, type, merchant, merchant_key, category_id FROM transactions "
        f"WHERE occurred_on BETWEEN ? AND ? AND {VARIABLE_WHERE} ORDER BY occurred_on, id",
        (p.start.isoformat(), p.end.isoformat()),
    ).fetchall()


def _signed(r: sqlite3.Row) -> int:
    return -r["amount"] if r["type"] == "refund" else r["amount"]


def _days(p: Period) -> list[date]:
    return [p.start + timedelta(days=i) for i in range((p.end - p.start).days + 1)]


def _daily(rows: list[sqlite3.Row], p: Period, icons: dict[int, str]) -> list[dict]:
    by_day: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for r in rows:
        by_day[r["occurred_on"]].append(r)
    out = []
    for d in _days(p):
        day_rows = by_day.get(d.isoformat(), [])
        spends = sorted((r for r in day_rows if r["type"] != "refund"), key=lambda r: -r["amount"])
        out.append({
            "date": d.isoformat(),
            "spent": sum(_signed(r) for r in day_rows),
            "count": len(spends),
            "top": [{"merchant": r["merchant"], "amount": r["amount"], "icon": icons.get(r["category_id"], "")}
                    for r in spends[:TOP_PER_DAY]],
        })
    return out


def _cat_key(r: sqlite3.Row) -> str:
    return str(r["category_id"]) if r["category_id"] is not None else "none"


def _category_details(rows: list[sqlite3.Row], previous: list[sqlite3.Row]) -> dict[str, dict]:
    """카테고리 id(미분류는 'none') → 결제 수·지난 기간 사용액·많이 쓴 곳."""
    out: dict[str, dict] = defaultdict(lambda: {"count": 0, "previous_spent": 0, "merchants": []})
    merchants: dict[str, dict[str, dict]] = defaultdict(dict)
    for r in rows:
        if r["type"] == "refund":
            continue
        k = _cat_key(r)
        out[k]["count"] += 1
        m = merchants[k].setdefault(r["merchant_key"] or r["merchant"], {"name": r["merchant"], "amount": 0, "count": 0})
        m["amount"] += r["amount"]
        m["count"] += 1
    for r in previous:
        out[_cat_key(r)]["previous_spent"] += _signed(r)
    for k, ms in merchants.items():
        out[k]["merchants"] = sorted(ms.values(), key=lambda m: -m["amount"])[:TOP_MERCHANTS]
    return dict(out)


def _history(conn: sqlite3.Connection, periods: list[Period], today: date) -> list[dict]:
    out = []
    for p in periods:
        start, end = p.start.isoformat(), p.end.isoformat()
        variable = conn.execute(
            "SELECT COALESCE(SUM(CASE WHEN type = 'refund' THEN -amount ELSE amount END), 0) FROM transactions "
            f"WHERE occurred_on BETWEEN ? AND ? AND {VARIABLE_WHERE}", (start, end)).fetchone()[0]
        income = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE type = 'income' AND occurred_on BETWEEN ? AND ?",
            (start, end)).fetchone()[0]
        recurring = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE recurring_id IS NOT NULL "
            "AND occurred_on BETWEEN ? AND ?", (start, end)).fetchone()[0]
        out.append({**p.to_dict(), "label": label(p), "variable": variable, "income": income,
                    "recurring": recurring, "current": p.contains(today)})
    return out


def overview(conn: sqlite3.Connection, period: Period, today: date | None = None) -> dict:
    today = today or date.today()
    payday = int(get_settings(conn)["payday"])
    before = periods_before(period, payday, HISTORY - 1)
    previous = before[-1]
    icons = {r["id"]: r["icon"] for r in conn.execute("SELECT id, icon FROM categories")}
    rows, prev_rows = _rows(conn, period), _rows(conn, previous)
    return {
        "period": period.to_dict(),
        "today": today.isoformat(),
        "daily": _daily(rows, period, icons),
        "previous": {**previous.to_dict(), "daily": [d["spent"] for d in _daily(prev_rows, previous, icons)]},
        "categories": _category_details(rows, prev_rows),
        "history": _history(conn, [*before, period], today),
    }
