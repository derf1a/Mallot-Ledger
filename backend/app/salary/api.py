"""급여 관리 (/api/salary) — 급여명세서 기록 · 분석 · 명세서 이미지 판독."""

import json
import re
import sqlite3
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field, field_validator

from app.core.db import get_conn
from app.insights.schemas import SalaryIn
from app.salary import analysis, contract, extract, rules

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
    source: Literal["manual", "image", "estimate"] = "manual"

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


@router.get("/contract")
def read_contract(conn: Conn) -> dict:
    """연봉 구성(소비 분석 > 절세의 총급여 계산기와 같은 값)과 한 달 정기 급여 추정."""
    return contract.view(conn)


@router.put("/contract")
def write_contract(body: SalaryIn, conn: Conn) -> dict:
    return contract.save_parts(conn, body.model_dump())


@router.get("/plan")
def read_plan(conn: Conn, year: Annotated[int | None, Query(ge=2000, le=2100)] = None) -> dict:
    """연봉 기준 명세서 초안 — 명세서가 없는 달만, 가계부 정기 급여 입금으로 세금을 거꾸로 낸다 (저장 안 함)."""
    return contract.plan(conn, year or date.today().year)


class ApplyIn(BaseModel):
    year: int = Field(ge=2000, le=2100)
    months: list[str] = Field(min_length=1, max_length=12)


@router.post("/plan", status_code=201)
def apply_plan(body: ApplyIn, conn: Conn) -> dict:
    """고른 달의 초안을 명세서로 저장한다 (source='estimate')."""
    drafts = {d["pay_month"]: d for d in contract.plan(conn, body.year)["drafts"]}
    made = []
    for m in body.months:
        d = drafts.get(m)
        if not d:
            continue
        v = _values(SlipIn(**{k: d[k] for k in SlipIn.model_fields if k in d}))
        cur = conn.execute(f"INSERT INTO salary_slips ({', '.join(v)}) VALUES ({', '.join('?' * len(v))})", tuple(v.values()))
        made.append(cur.lastrowid)
    conn.commit()
    return {"created": len(made), "ids": made}


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
