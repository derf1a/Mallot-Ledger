"""개인설정(이름·월 주수입·수입일·빌린 돈 상대·검색 범위)과 내 계좌."""

import json
import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.core.db import get_conn
from app.ledger.schemas import AccountIn, SettingsIn
from app.ledger.settings import get_settings

router = APIRouter(prefix="/api", tags=["settings"])
Conn = Annotated[sqlite3.Connection, Depends(get_conn)]


def _row_or_404(conn: sqlite3.Connection, table: str, item_id: int) -> dict:
    row = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (item_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "항목을 찾을 수 없습니다")
    return dict(row)


# ---- 개인설정 ----
@router.get("/settings")
def read_settings(conn: Conn) -> dict:
    return get_settings(conn)


@router.put("/settings")
def update_settings(body: SettingsIn, conn: Conn) -> dict:
    for key, value in body.model_dump(exclude_none=True).items():
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(value, ensure_ascii=False)),
        )
    conn.commit()
    return get_settings(conn)


# ---- 내 계좌 ----
@router.get("/accounts")
def list_accounts(conn: Conn) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM accounts ORDER BY id")]


@router.post("/accounts", status_code=201)
def create_account(body: AccountIn, conn: Conn) -> dict:
    cur = conn.execute("INSERT INTO accounts (name, keyword) VALUES (?, ?)", (body.name, body.keyword))
    conn.commit()
    return _row_or_404(conn, "accounts", cur.lastrowid)


@router.put("/accounts/{item_id}")
def update_account(item_id: int, body: AccountIn, conn: Conn) -> dict:
    _row_or_404(conn, "accounts", item_id)
    conn.execute("UPDATE accounts SET name = ?, keyword = ? WHERE id = ?", (body.name, body.keyword, item_id))
    conn.commit()
    return _row_or_404(conn, "accounts", item_id)


@router.delete("/accounts/{item_id}", status_code=204)
def delete_account(item_id: int, conn: Conn) -> None:
    _row_or_404(conn, "accounts", item_id)
    conn.execute("DELETE FROM accounts WHERE id = ?", (item_id,))
    conn.commit()
