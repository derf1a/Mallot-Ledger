"""급여 관리 (/api/salary) — 급여명세서 기록 · 분석 · 명세서 이미지 판독."""

import json
import re
import sqlite3
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field, field_validator

from app.core.db import get_conn
from app.salary import analysis, extract, rules

router = APIRouter(prefix="/api/salary", tags=["salary"])
Conn = Annotated[sqlite3.Connection, Depends(get_conn)]
MAX_IMAGE = 10 * 1024 * 1024
IMAGE_TYPES = ("image/png", "image/jpeg", "image/webp")
_MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


class Item(BaseModel):
    label: str = Field(max_length=60)
    amount: int
    kind: Literal["pay_taxable", "pay_nontaxable", "deduction"]


class SlipIn(BaseModel):
    pay_month: str
    paid_on: date | None = None
    kind: Literal["regular", "bonus", "retro", "other"] = "regular"
    employer: str = Field("", max_length=60)
    taxable_pay: int = Field(0, ge=0)
    nontaxable_pay: int = Field(0, ge=0)
    national_pension: int = Field(0, ge=0)
    health_insurance: int = Field(0, ge=0)
    long_term_care: int = Field(0, ge=0)
    employment_insurance: int = Field(0, ge=0)
    income_tax: int = 0   # 연말정산 환급 달은 음수일 수 있다
    local_income_tax: int = 0
    other_deductions: int = 0
    net_pay: int | None = None
    items: list[Item] = Field(default_factory=list, max_length=80)
    memo: str = Field("", max_length=500)
    source: Literal["manual", "image"] = "manual"

    @field_validator("pay_month")
    @classmethod
    def _month(cls, v: str) -> str:
        if not _MONTH.match(v):
            raise ValueError("귀속 월은 YYYY-MM")
        return v


def _values(body: SlipIn) -> dict:
    d = body.model_dump()
    d["paid_on"] = d["paid_on"].isoformat() if d["paid_on"] else None
    d["items_json"] = json.dumps(d.pop("items"), ensure_ascii=False)
    return d


@router.get("")
def read(conn: Conn, year: Annotated[int | None, Query(ge=2000, le=2100)] = None) -> dict:
    y = year or date.today().year
    out = analysis.summary(conn, y)
    out["years"] = [int(r[0]) for r in conn.execute("SELECT DISTINCT substr(pay_month, 1, 4) FROM salary_slips ORDER BY 1 DESC")]
    return out


@router.get("/rules")
def read_rules() -> dict:
    return {"year": rules.RULES_YEAR, "pension": rules.PENSION, "health": rules.HEALTH, "care_of_health": rules.CARE_OF_HEALTH,
            "employment": rules.EMPLOYMENT, "local_of_income": rules.LOCAL_OF_INCOME, "labels": rules.LABELS}


@router.post("", status_code=201)
def create(body: SlipIn, conn: Conn) -> dict:
    v = _values(body)
    cur = conn.execute(f"INSERT INTO salary_slips ({', '.join(v)}) VALUES ({', '.join('?' * len(v))})", tuple(v.values()))
    conn.commit()
    return analysis.view(conn, analysis.get_slip(conn, cur.lastrowid))


@router.put("/{slip_id}")
def update(slip_id: int, body: SlipIn, conn: Conn) -> dict:
    if not analysis.get_slip(conn, slip_id):
        raise HTTPException(404, "명세서를 찾을 수 없어요")
    v = _values(body)
    conn.execute(f"UPDATE salary_slips SET {', '.join(f'{k} = ?' for k in v)} WHERE id = ?", (*v.values(), slip_id))
    conn.commit()
    return analysis.view(conn, analysis.get_slip(conn, slip_id))


@router.delete("/{slip_id}", status_code=204)
def delete(slip_id: int, conn: Conn) -> None:
    if not conn.execute("DELETE FROM salary_slips WHERE id = ?", (slip_id,)).rowcount:
        raise HTTPException(404, "명세서를 찾을 수 없어요")
    conn.commit()


@router.post("/extract")
async def extract_image(file: UploadFile) -> dict:
    """급여명세서 이미지 → 초안 (저장 안 함)."""
    if file.content_type not in IMAGE_TYPES:
        raise HTTPException(415, "PNG · JPEG · WEBP 이미지만 읽어요")
    image = await file.read()
    if len(image) > MAX_IMAGE:
        raise HTTPException(413, "이미지가 10MB 를 넘어요")
    try:
        return await extract.extract(image, file.content_type, date.today().isoformat())
    except extract.SalaryExtractError as e:
        raise HTTPException(502, str(e)) from None
