"""기간 요약 — 수입·정기지출·변동비(카테고리 예산 대비)·분류 필요."""

import sqlite3
from datetime import date

from app.core.periods import Period
from app.ledger.rules import VARIABLE_WHERE
from app.ledger.settings import get_settings
from app.recurring.matching import recurring_status


def summary(conn: sqlite3.Connection, period: Period, today: date | None = None) -> dict:
    settings = get_settings(conn)
    start, end = period.start.isoformat(), period.end.isoformat()
    income_planned = int(settings["monthly_income"])
    income_actual = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE type = 'income' AND occurred_on BETWEEN ? AND ?",
        (start, end),
    ).fetchone()[0]

    all_items = recurring_status(conn, period, today)
    items = [i for i in all_items if i["status"] != "skipped"]  # 이번 기간 합계·그룹 금액에서 뺀다
    recurring_total = sum(i["amount"] for i in items)
    groups: dict[int, dict] = {}
    for i in items:
        g = groups.setdefault(
            i["group_id"],
            {"group_id": i["group_id"], "group_name": i["group_name"], "kind": i["group_kind"],
             "icon": i["group_icon"], "amount": 0, "paid": 0},
        )
        g["amount"] += i["amount"]
        if i["status"] == "paid":
            g["paid"] += i["amount"]

    # 변동비: 정기지출에 매칭되지 않은 지출 + 타 계좌 이체 − 정산·환불 입금
    spent_rows = conn.execute(
        "SELECT category_id, SUM(CASE WHEN type = 'refund' THEN -amount ELSE amount END) AS spent FROM transactions "
        f"WHERE occurred_on BETWEEN ? AND ? AND {VARIABLE_WHERE} GROUP BY category_id",
        (start, end),
    ).fetchall()
    refund_total = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE type = 'refund' AND occurred_on BETWEEN ? AND ?",
        (start, end),
    ).fetchone()[0]
    spent_by_cat = {r["category_id"]: r["spent"] for r in spent_rows}
    categories = []
    for c in conn.execute("SELECT * FROM categories ORDER BY sort_order, id"):
        spent = spent_by_cat.pop(c["id"], 0)
        categories.append(
            {"id": c["id"], "name": c["name"], "icon": c["icon"], "budget": c["budget"], "spent": spent,
             "remaining": c["budget"] - spent}
        )
    uncategorized = sum(spent_by_cat.values())

    variable_pool = income_planned - recurring_total
    budget_total = sum(c["budget"] for c in categories)
    needs_review = conn.execute(
        "SELECT COUNT(*) FROM transactions WHERE needs_review = 1 AND occurred_on BETWEEN ? AND ?", (start, end)
    ).fetchone()[0]

    return {
        "period": period.to_dict(),
        "income": {"planned": income_planned, "actual": income_actual},
        "recurring": {
            "total": recurring_total,
            "saving_total": sum(i["amount"] for i in items if i["group_kind"] == "saving"),
            "expense_total": sum(i["amount"] for i in items if i["group_kind"] == "expense"),
            "groups": list(groups.values()),
            "missed": sum(1 for i in items if i["status"] == "missed"),
            "skipped_total": sum(i["amount"] for i in all_items if i["status"] == "skipped"),
            "items": all_items,
        },
        "variable": {
            "pool": variable_pool,
            "budget_total": budget_total,
            "unallocated": variable_pool - budget_total,
            "spent_total": sum(c["spent"] for c in categories) + uncategorized,
            "refund_total": refund_total,  # 정산·환불로 돌려받아 변동비에서 뺀 금액
            "uncategorized": uncategorized,
            "categories": categories,
        },
        "needs_review": needs_review,
    }
