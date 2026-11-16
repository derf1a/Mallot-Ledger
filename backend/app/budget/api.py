"""변동비 관리(가계부 > Budget): 할당 가능액·카테고리 예산·참고 사용액, 예산 한꺼번에 저장, 변동비 카테고리 추가·수정·삭제."""

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.budget import allocation as budget
from app.core.db import get_conn

router = APIRouter(prefix="/api", tags=["budget"])
Conn = Annotated[sqlite3.Connection, Depends(get_conn)]


class CategoryIn(BaseModel):
    name: str = Field(min_length=1)
    icon: str = ""
    description: str = ""
    budget: int = Field(default=0, ge=0)
    sort_order: int = 0


class BudgetIn(BaseModel):
    id: int
    budget: int = Field(ge=0)


class BudgetsIn(BaseModel):
    budgets: list[BudgetIn] = Field(min_length=1)


@router.get("/budget")
def read_budget(conn: Conn) -> dict:
    return budget.overview(conn)


@router.put("/budget")
def save_budgets(body: BudgetsIn, conn: Conn) -> dict:
    try:
        budget.set_budgets(conn, {b.id: b.budget for b in body.budgets})
    except KeyError as e:
        raise HTTPException(404, f"없는 카테고리예요: {e.args[0]}") from None
    return budget.overview(conn)


def _row_or_404(conn: sqlite3.Connection, table: str, item_id: int) -> dict:
    row = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (item_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "항목을 찾을 수 없습니다")
    return dict(row)


# ---- 카테고리 ----
@router.get("/categories")
def list_categories(conn: Conn) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM categories ORDER BY sort_order, id")]


@router.post("/categories", status_code=201)
def create_category(body: CategoryIn, conn: Conn) -> dict:
    try:
        cur = conn.execute(
            "INSERT INTO categories (name, icon, description, budget, sort_order) VALUES (?, ?, ?, ?, ?)",
            (body.name, body.icon, body.description, body.budget, body.sort_order),
        )
    except sqlite3.IntegrityError:
        raise HTTPException(409, "같은 이름의 카테고리가 있습니다") from None
    conn.commit()
    return _row_or_404(conn, "categories", cur.lastrowid)


@router.put("/categories/{item_id}")
def update_category(item_id: int, body: CategoryIn, conn: Conn) -> dict:
    _row_or_404(conn, "categories", item_id)
    try:
        conn.execute(
            "UPDATE categories SET name = ?, icon = ?, description = ?, budget = ?, sort_order = ? WHERE id = ?",
            (body.name, body.icon, body.description, body.budget, body.sort_order, item_id),
        )
    except sqlite3.IntegrityError:
        raise HTTPException(409, "같은 이름의 카테고리가 있습니다") from None
    conn.commit()
    return _row_or_404(conn, "categories", item_id)


@router.delete("/categories/{item_id}", status_code=204)
def delete_category(item_id: int, conn: Conn) -> None:
    if _row_or_404(conn, "categories", item_id)["is_system"]:
        raise HTTPException(400, "기본 카테고리(기타)는 삭제할 수 없습니다")
    conn.execute("DELETE FROM categories WHERE id = ?", (item_id,))
    conn.commit()
