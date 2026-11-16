"""가계부 거래: 기간 보기·범위 검색·필터, 결제수단 목록, 추가(한 건·여러 건)·수정·삭제. 캡쳐 판독은 app.capture."""

import calendar
import sqlite3
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.db import get_conn
from app.ledger.merchants import learn, similar_count
from app.ledger.rules import VARIABLE_WHERE, normalize
from app.ledger.schemas import TransactionIn
from app.ledger.settings import current_period
from app.ledger.transactions import COLUMNS, SELECT, get_transaction, insert_transaction

router = APIRouter(prefix="/api/transactions", tags=["transactions"])
Conn = Annotated[sqlite3.Connection, Depends(get_conn)]


def _get(conn: sqlite3.Connection, tx_id: int) -> dict:
    tx = get_transaction(conn, tx_id)
    if tx is None:
        raise HTTPException(404, "거래를 찾을 수 없습니다")
    return tx


def _months_before(d: date, months: int) -> date:
    idx = d.year * 12 + (d.month - 1) - months
    y, m = idx // 12, idx % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


@router.get("")
def list_transactions(
    conn: Conn,
    on: Annotated[date | None, Query(description="이 날짜가 속한 기간(수입일 기준 한 달)의 거래")] = None,
    q: Annotated[str, Query(description="검색어: 가맹점·메모·결제수단·카테고리·정기지출 이름")] = "",
    months: Annotated[int | None, Query(ge=0, le=600, description="최근 N개월 (0 = 전체). 주면 기간 대신 범위로 찾는다")] = None,
    start: date | None = None,
    end: date | None = None,
    type: Annotated[Literal["expense", "income", "transfer", "refund"] | None, Query()] = None,  # noqa: A002
    category_id: Annotated[str | None, Query(description="카테고리 id, 'none' = 미분류")] = None,
    payment_method: str | None = None,
    needs_review: bool | None = None,
    recurring: Annotated[Literal["linked", "unlinked"] | None, Query()] = None,
    source: Annotated[Literal["manual", "image", "import"] | None, Query()] = None,
    variable: Annotated[bool, Query(description="변동비로 잡히는 거래만 (가계부 요약·변동비 관리의 사용액과 같은 정의)")] = False,
    limit: Annotated[int, Query(ge=1, le=5000)] = 1000,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict:
    """기간 보기(on, 기본) 또는 범위 검색(months / start·end). 필터는 둘 다에 적용된다."""
    period = None
    if months is None and start is None and end is None:
        period = current_period(conn, on)
        lo, hi = period.start, period.end
    else:
        hi = end or date.today()
        if start:
            lo = start
        elif months:
            lo = _months_before(hi, months)
        else:  # 전체: 첫 거래 날짜부터
            first = conn.execute("SELECT MIN(occurred_on) FROM transactions").fetchone()[0]
            lo = date.fromisoformat(first) if first else hi

    where, args = ["t.occurred_on BETWEEN ? AND ?"], [lo.isoformat(), hi.isoformat()]
    if q.strip():
        like = f"%{q.strip().lower()}%"
        where.append("(lower(t.merchant) LIKE ? OR lower(t.memo) LIKE ? OR lower(t.payment_method) LIKE ? "
                     "OR lower(COALESCE(c.name, '')) LIKE ? OR lower(COALESCE(r.name, '')) LIKE ?)")
        args += [like] * 5
    if type:
        where.append("t.type = ?")
        args.append(type)
    if category_id == "none":  # 변동비로 볼 때는 카테고리 없는 정산·환불도 미분류 사용액에 들어간다
        where.append("t.category_id IS NULL" if variable else "t.category_id IS NULL AND t.type = 'expense'")
    elif category_id:
        where.append("t.category_id = ?")
        args.append(int(category_id))
    if payment_method:
        where.append("t.payment_method = ?")
        args.append(payment_method)
    if needs_review is not None:
        where.append("t.needs_review = ?")
        args.append(int(needs_review))
    if recurring:
        where.append("t.recurring_id IS NOT NULL" if recurring == "linked" else "t.recurring_id IS NULL")
    if source:
        where.append("t.source = ?")
        args.append(source)
    if variable:
        where.append(f"t.id IN (SELECT id FROM transactions WHERE {VARIABLE_WHERE})")
    cond = " AND ".join(where)
    joins = ("FROM transactions t LEFT JOIN categories c ON c.id = t.category_id "
             "LEFT JOIN recurring_items r ON r.id = t.recurring_id")
    agg = conn.execute(
        f"SELECT COUNT(*) AS total, "
        f"COALESCE(SUM(CASE WHEN t.type = 'income' THEN t.amount END), 0) AS income, "
        f"COALESCE(SUM(CASE WHEN t.type = 'expense' THEN t.amount END), 0) AS expense, "
        f"COALESCE(SUM(CASE WHEN t.transfer_kind = 'external' THEN t.amount END), 0) AS transfer_out, "
        f"COALESCE(SUM(CASE WHEN t.type = 'refund' THEN t.amount END), 0) AS refund "
        f"{joins} WHERE {cond}",
        args,
    ).fetchone()
    rows = conn.execute(
        f"{SELECT} WHERE {cond} ORDER BY t.occurred_on DESC, t.occurred_time DESC, t.id DESC LIMIT ? OFFSET ?",
        (*args, limit, offset),
    ).fetchall()
    return {
        "period": period.to_dict() if period else None,
        "range": {"start": lo.isoformat(), "end": hi.isoformat()},
        "total": agg["total"],
        "sums": {"income": agg["income"], "expense": agg["expense"], "transfer_out": agg["transfer_out"],
                 "refund": agg["refund"]},
        "transactions": [{**dict(r), "needs_review": bool(r["needs_review"])} for r in rows],
    }


@router.get("/payment-methods")
def payment_methods(conn: Conn) -> list[dict]:
    """필터용 결제수단 목록 (많이 쓴 순)."""
    rows = conn.execute(
        "SELECT payment_method AS name, COUNT(*) AS count FROM transactions WHERE payment_method != '' "
        "GROUP BY payment_method ORDER BY count DESC, name"
    )
    return [dict(r) for r in rows]


@router.post("", status_code=201)
def create_transaction(body: TransactionIn, conn: Conn) -> dict:
    tx_id = insert_transaction(conn, body)
    conn.commit()
    return _get(conn, tx_id)


@router.post("/bulk", status_code=201)
def create_transactions(body: list[TransactionIn], conn: Conn) -> list[dict]:
    ids = [insert_transaction(conn, tx) for tx in body]
    conn.commit()
    return [_get(conn, i) for i in ids]


@router.put("/{tx_id}")
def update_transaction(tx_id: int, body: TransactionIn, conn: Conn) -> dict:
    before = _get(conn, tx_id)
    data = normalize(conn, body, tx_id)
    conn.execute(
        f"UPDATE transactions SET {', '.join(f'{c} = ?' for c in COLUMNS)} WHERE id = ?",
        [*(data[c] for c in COLUMNS), tx_id],
    )
    # 메모·날짜만 고친 수정까지 학습하면 같은 규칙의 적용 횟수가 계속 부풀려진다 → 분류나 가맹점이 바뀐 경우만
    if (before["category_id"], before["merchant_key"]) != (data["category_id"], data["merchant_key"]):
        learn(conn, data)
    conn.commit()
    result = _get(conn, tx_id)
    # 사용자가 카테고리를 바꿨으면, 같은 가맹점인데 카테고리가 다른 다른 거래 수를 알려준다 (일괄 변경 안내용)
    result["similar_count"] = (
        similar_count(conn, data["merchant_key"], data["category_id"], tx_id) if data["category_source"] == "user" else 0
    )
    return result


@router.delete("/{tx_id}", status_code=204)
def delete_transaction(tx_id: int, conn: Conn) -> None:
    _get(conn, tx_id)
    conn.execute("DELETE FROM transactions WHERE id = ?", (tx_id,))
    conn.commit()
