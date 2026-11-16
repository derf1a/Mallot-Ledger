import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.core.db import get_conn
from app.ledger.merchants import apply_past, find_rule, merchant_key

router = APIRouter(prefix="/api/merchant-rules", tags=["merchant-rules"])
Conn = Annotated[sqlite3.Connection, Depends(get_conn)]

SELECT = """
SELECT r.*, c.name AS category_name, c.icon AS category_icon,
       (SELECT COUNT(*) FROM transactions t WHERE t.merchant_key = r.merchant_key) AS tx_count
FROM merchant_rules r JOIN categories c ON c.id = r.category_id
"""


class RuleUpdate(BaseModel):
    category_id: int


class ApplyPast(BaseModel):
    merchant: str
    category_id: int


def _get(conn: sqlite3.Connection, rule_id: int) -> dict:
    row = conn.execute(f"{SELECT} WHERE r.id = ?", (rule_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "규칙을 찾을 수 없습니다")
    return dict(row)


def _check_category(conn: sqlite3.Connection, category_id: int) -> None:
    if not conn.execute("SELECT 1 FROM categories WHERE id = ?", (category_id,)).fetchone():
        raise HTTPException(400, "없는 카테고리입니다")


@router.get("")
def list_rules(conn: Conn, q: Annotated[str, Query(description="가맹점 검색")] = "") -> list[dict]:
    key = merchant_key(q)
    rows = conn.execute(
        f"{SELECT} WHERE instr(r.merchant_key, ?) > 0 ORDER BY r.source = 'user' DESC, r.hits DESC, r.updated_at DESC",
        (key,),
    )
    return [dict(r) for r in rows]


@router.get("/suggest")
def suggest(conn: Conn, merchant: str) -> dict | None:
    """입력 중인 가맹점에 맞는 규칙 (직접 입력 폼의 카테고리 자동 선택용)."""
    rule = find_rule(conn, merchant_key(merchant))
    return _get(conn, rule["id"]) if rule else None


@router.post("/apply-past")
def apply_to_past(body: ApplyPast, conn: Conn) -> dict:
    """같은 가맹점의 과거 거래 카테고리를 한꺼번에 바꾼다."""
    _check_category(conn, body.category_id)
    key = merchant_key(body.merchant)
    if not key:
        raise HTTPException(400, "가맹점 이름이 비어 있습니다")
    updated = apply_past(conn, key, body.category_id)
    conn.commit()
    return {"updated": updated}


@router.put("/{rule_id}")
def update_rule(rule_id: int, body: RuleUpdate, conn: Conn) -> dict:
    _get(conn, rule_id)
    _check_category(conn, body.category_id)
    conn.execute(
        "UPDATE merchant_rules SET category_id = ?, source = 'user', updated_at = datetime('now', 'localtime') "
        "WHERE id = ?",
        (body.category_id, rule_id),
    )
    conn.commit()
    return _get(conn, rule_id)


@router.delete("/{rule_id}", status_code=204)
def delete_rule(rule_id: int, conn: Conn) -> None:
    _get(conn, rule_id)
    conn.execute("DELETE FROM merchant_rules WHERE id = ?", (rule_id,))
    conn.commit()
