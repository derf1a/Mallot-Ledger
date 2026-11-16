"""정기지출: 정기지출 카테고리(칸)·항목 추가·수정·삭제·순서, 이번 기간 상태, 이번 기간만 건너뛰기."""

import sqlite3
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.db import get_conn
from app.ledger.settings import current_period
from app.recurring.matching import RECURRING_COLS, RECURRING_SELECT, recurring_status
from app.recurring.schemas import RecurringGroupIn, RecurringIn, RecurringOrderGroup

router = APIRouter(prefix="/api", tags=["recurring"])
Conn = Annotated[sqlite3.Connection, Depends(get_conn)]
On = Annotated[date | None, Query(description="이 날짜가 속한 기간 (기본: 오늘)")]


def _row_or_404(conn: sqlite3.Connection, table: str, item_id: int) -> dict:
    row = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (item_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "항목을 찾을 수 없습니다")
    return dict(row)


# ---- 정기지출 카테고리 (칸) ----
GROUP_COLS = ("name", "kind", "icon", "sort_order")


@router.get("/recurring-groups")
def list_groups(conn: Conn) -> list[dict]:
    rows = conn.execute(
        "SELECT g.*, (SELECT COUNT(*) FROM recurring_items r WHERE r.group_id = g.id) AS item_count "
        "FROM recurring_groups g ORDER BY g.sort_order, g.id"
    )
    return [dict(r) for r in rows]


@router.post("/recurring-groups", status_code=201)
def create_group(body: RecurringGroupIn, conn: Conn) -> dict:
    try:
        cur = conn.execute(
            f"INSERT INTO recurring_groups ({', '.join(GROUP_COLS)}) VALUES (?, ?, ?, ?)",
            [getattr(body, c) for c in GROUP_COLS],
        )
    except sqlite3.IntegrityError:
        raise HTTPException(409, "같은 이름의 정기지출 카테고리가 있습니다") from None
    conn.commit()
    return _row_or_404(conn, "recurring_groups", cur.lastrowid)


# '/recurring-groups/{item_id}' 보다 먼저 등록해야 'order' 가 id 로 해석되지 않는다
@router.put("/recurring-groups/order")
def reorder_groups(body: list[int], conn: Conn) -> list[dict]:
    """정기지출 카테고리(칸) 순서 저장 — 화면 위에서부터의 id 목록."""
    existing = {r[0] for r in conn.execute("SELECT id FROM recurring_groups")}
    if len(set(body)) != len(body) or set(body) != existing:
        raise HTTPException(400, "모든 정기지출 카테고리를 한 번씩 보내야 합니다")
    for pos, gid in enumerate(body, start=1):
        conn.execute("UPDATE recurring_groups SET sort_order = ? WHERE id = ?", (pos, gid))
    conn.commit()
    return list_groups(conn)


@router.put("/recurring-groups/{item_id}")
def update_group(item_id: int, body: RecurringGroupIn, conn: Conn) -> dict:
    _row_or_404(conn, "recurring_groups", item_id)
    try:
        conn.execute(
            f"UPDATE recurring_groups SET {', '.join(f'{c} = ?' for c in GROUP_COLS)} WHERE id = ?",
            [*(getattr(body, c) for c in GROUP_COLS), item_id],
        )
    except sqlite3.IntegrityError:
        raise HTTPException(409, "같은 이름의 정기지출 카테고리가 있습니다") from None
    conn.commit()
    return _row_or_404(conn, "recurring_groups", item_id)


@router.delete("/recurring-groups/{item_id}", status_code=204)
def delete_group(item_id: int, conn: Conn) -> None:
    _row_or_404(conn, "recurring_groups", item_id)
    if conn.execute("SELECT 1 FROM recurring_items WHERE group_id = ?", (item_id,)).fetchone():
        raise HTTPException(409, "이 카테고리를 쓰는 정기지출 항목이 있습니다. 항목을 먼저 옮기거나 삭제하세요")
    conn.execute("DELETE FROM recurring_groups WHERE id = ?", (item_id,))
    conn.commit()


# ---- 정기지출 항목 ----
def _recurring(conn: sqlite3.Connection, item_id: int) -> dict:
    row = conn.execute(f"{RECURRING_SELECT} WHERE r.id = ?", (item_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "항목을 찾을 수 없습니다")
    return {**dict(row), "active": bool(row["active"])}


def _check_group(conn: sqlite3.Connection, group_id: int) -> None:
    if not conn.execute("SELECT 1 FROM recurring_groups WHERE id = ?", (group_id,)).fetchone():
        raise HTTPException(400, "없는 정기지출 카테고리입니다")


@router.get("/recurring-items")
def list_recurring(conn: Conn) -> list[dict]:
    rows = conn.execute(f"{RECURRING_SELECT} ORDER BY g.sort_order, r.sort_order, r.id")
    return [{**dict(r), "active": bool(r["active"])} for r in rows]


@router.post("/recurring-items", status_code=201)
def create_recurring(body: RecurringIn, conn: Conn) -> dict:
    _check_group(conn, body.group_id)
    cur = conn.execute(
        f"INSERT INTO recurring_items ({', '.join(RECURRING_COLS)}) VALUES ({', '.join('?' * len(RECURRING_COLS))})",
        [getattr(body, c) for c in RECURRING_COLS],
    )
    conn.commit()
    return _recurring(conn, cur.lastrowid)


# '/recurring-items/{item_id}' 보다 먼저 등록해야 'order' 가 id 로 해석되지 않는다
@router.put("/recurring-items/order")
def reorder_recurring(body: list[RecurringOrderGroup], conn: Conn) -> list[dict]:
    """드래그 앤 드롭 결과 저장. 다른 카테고리로 옮긴 항목은 카테고리도 바뀐다."""
    seen: set[int] = set()
    for g in body:
        _check_group(conn, g.group_id)
        for item_id in g.item_ids:
            if item_id in seen:
                raise HTTPException(400, f"항목 {item_id}가 두 번 들어 있습니다")
            seen.add(item_id)
    existing = {r[0] for r in conn.execute("SELECT id FROM recurring_items")}
    if unknown := seen - existing:
        raise HTTPException(400, f"없는 항목입니다: {sorted(unknown)}")
    for g in body:
        for pos, item_id in enumerate(g.item_ids, start=1):
            conn.execute(
                "UPDATE recurring_items SET group_id = ?, sort_order = ? WHERE id = ?", (g.group_id, pos, item_id)
            )
    conn.commit()
    return list_recurring(conn)


@router.put("/recurring-items/{item_id}")
def update_recurring(item_id: int, body: RecurringIn, conn: Conn) -> dict:
    _recurring(conn, item_id)
    _check_group(conn, body.group_id)
    conn.execute(
        f"UPDATE recurring_items SET {', '.join(f'{c} = ?' for c in RECURRING_COLS)} WHERE id = ?",
        [*(getattr(body, c) for c in RECURRING_COLS), item_id],
    )
    conn.commit()
    return _recurring(conn, item_id)


@router.delete("/recurring-items/{item_id}", status_code=204)
def delete_recurring(item_id: int, conn: Conn) -> None:
    _recurring(conn, item_id)
    conn.execute("DELETE FROM recurring_items WHERE id = ?", (item_id,))
    conn.commit()


# ---- 이번 기간 상태·건너뛰기 ----
@router.get("/recurring-status")
def read_recurring_status(conn: Conn, on: On = None) -> dict:
    period = current_period(conn, on)
    return {"period": period.to_dict(), "items": recurring_status(conn, period)}


def _skip_target(conn: sqlite3.Connection, item_id: int, on: date | None) -> str:
    if not conn.execute("SELECT 1 FROM recurring_items WHERE id = ?", (item_id,)).fetchone():
        raise HTTPException(404, "정기지출 항목을 찾을 수 없습니다")
    return current_period(conn, on).start.isoformat()


@router.post("/recurring-items/{item_id}/skip")
def skip_recurring(item_id: int, conn: Conn, on: On = None) -> dict:
    """이번 기간(on 이 속한 기간)만 이 정기지출을 건너뛴다."""
    start = _skip_target(conn, item_id, on)
    conn.execute("INSERT OR IGNORE INTO recurring_skips (item_id, period_start) VALUES (?, ?)", (item_id, start))
    conn.commit()
    return {"item_id": item_id, "period_start": start, "skipped": True}


@router.delete("/recurring-items/{item_id}/skip")
def unskip_recurring(item_id: int, conn: Conn, on: On = None) -> dict:
    start = _skip_target(conn, item_id, on)
    conn.execute("DELETE FROM recurring_skips WHERE item_id = ? AND period_start = ?", (item_id, start))
    conn.commit()
    return {"item_id": item_id, "period_start": start, "skipped": False}
