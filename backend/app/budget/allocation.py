"""변동비 관리(가계부 > Budget) 화면 자료 — 카테고리 월 예산과, 예산을 정할 때 참고할 사용액.

- 할당 가능액 = 월 주수입 − 이번 기간 정기지출 (가계부 요약과 같은 값). 예산 합계가 이걸 넘으면 초과.
- 카테고리마다 이번 기간 사용액·건수, 지난 기간 사용액, 최근 끝난 3개 기간 평균.
  평균에서는 100만 원 이상 한 건(일회성 큰 지출, 소비 습관 분석과 같은 기준)을 빼고, 데이터가 시작되기 전에 걸친 기간도 뺀다.
변동비 정의는 요약과 같다(ledger.VARIABLE_WHERE).
"""

import sqlite3
from datetime import date

from app.core.periods import Period
from app.insights.facts import ONE_OFF, label, periods_before
from app.ledger.rules import VARIABLE_WHERE
from app.ledger.settings import current_period, get_settings
from app.ledger.summary import summary

REFERENCE_PERIODS = 3


def _count(conn: sqlite3.Connection, p: Period) -> dict[int | None, int]:
    rows = conn.execute(
        f"SELECT category_id, COUNT(*) FROM transactions WHERE occurred_on BETWEEN ? AND ? AND {VARIABLE_WHERE} GROUP BY category_id",
        (p.start.isoformat(), p.end.isoformat()),
    ).fetchall()
    return {r[0]: r[1] for r in rows}


def _spent(conn: sqlite3.Connection, p: Period, skip_one_off: bool = False) -> dict[int | None, int]:
    one_off = " AND NOT (type != 'refund' AND amount >= ?)" if skip_one_off else ""
    rows = conn.execute(
        "SELECT category_id, SUM(CASE WHEN type = 'refund' THEN -amount ELSE amount END) AS spent FROM transactions "
        f"WHERE occurred_on BETWEEN ? AND ? AND {VARIABLE_WHERE}{one_off} GROUP BY category_id",
        (p.start.isoformat(), p.end.isoformat(), *((ONE_OFF,) if skip_one_off else ())),
    ).fetchall()
    return {r["category_id"]: r["spent"] for r in rows}


def overview(conn: sqlite3.Connection, today: date | None = None) -> dict:
    today = today or date.today()
    period = current_period(conn, today)
    s = summary(conn, period, today)
    before = periods_before(period, int(get_settings(conn)["payday"]), REFERENCE_PERIODS)
    first = conn.execute("SELECT MIN(occurred_on) FROM transactions").fetchone()[0]
    full = [p for p in before if first and p.start.isoformat() >= first]  # 데이터가 처음부터 있는 기간만 평균에
    now, last, counts = _spent(conn, period), _spent(conn, before[-1]), _count(conn, period)
    recent = [_spent(conn, p, skip_one_off=True) for p in full]

    def reference(key: int | None) -> dict:
        return {
            "spent": now.get(key, 0),
            "count": counts.get(key, 0),
            "last": last.get(key, 0),
            "average": round(sum(r.get(key, 0) for r in recent) / len(recent)) if recent else None,
            "history": [r.get(key, 0) for r in recent],
        }

    categories = [{**dict(c), "is_system": bool(c["is_system"]), **reference(c["id"])}
                  for c in conn.execute("SELECT * FROM categories ORDER BY sort_order, id")]
    return {
        "period": period.to_dict(),
        "today": today.isoformat(),
        "income": s["income"]["planned"],
        "recurring_total": s["recurring"]["total"],
        "pool": s["variable"]["pool"],
        "categories": categories,
        "uncategorized": reference(None),
        "reference": {"last": label(before[-1]), "periods": [label(p) for p in full], "one_off": ONE_OFF},
    }


def set_budgets(conn: sqlite3.Connection, budgets: dict[int, int]) -> None:
    """여러 카테고리의 월 예산을 한 번에 (없는 카테고리가 있으면 아무것도 바꾸지 않는다)."""
    known = {r[0] for r in conn.execute("SELECT id FROM categories")}
    missing = set(budgets) - known
    if missing:
        raise KeyError(sorted(missing))
    conn.executemany("UPDATE categories SET budget = ? WHERE id = ?", [(b, i) for i, b in budgets.items()])
    conn.commit()
