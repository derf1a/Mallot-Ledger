"""소비 습관 분석 — 코드가 계산한 통계(LLM 없이 바로)와 LLM 보고서(실험실 spending_report 실행), 절세 계산에 쓰는 내 정보."""

import json
import sqlite3
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.db import data_dir, get_conn
from app.insights import facts, tax, tax_rules
from app.insights.facts import InsightsError
from app.runs.runner import JobError, load_run, run_dict, start_run

router = APIRouter(prefix="/api/spending", tags=["spending"])
Conn = Annotated[sqlite3.Connection, Depends(get_conn)]


def _run(conn: sqlite3.Connection, run_id: int) -> dict:
    run = load_run(conn, run_id)
    if run is None:
        raise HTTPException(404, "실행을 찾을 수 없습니다")
    return run


KIND = "spending_report"


@router.get("/stats")
def read_stats(conn: Conn, months: int = 3) -> dict:
    """LLM 에게 줄 사실과 화면용 통계 — LLM 호출 없이 바로 계산한다."""
    try:
        return facts.compute(conn, months)
    except InsightsError as e:
        raise HTTPException(400, str(e)) from None


Won = Annotated[int, Field(ge=0, le=10_000_000_000)]


class SalaryIn(BaseModel):
    """총급여 계산기 입력 — 월 금액은 세전, 나머지는 한 해 합계."""
    months: int = Field(default=12, ge=0, le=12)     # 올해 근무 개월 수
    base_monthly: Won = 0
    meal_monthly: Won = 0
    meal_provided: bool = False                       # 회사 식사를 제공받으면 식대 비과세 없음
    car_monthly: Won = 0
    childcare_monthly: Won = 0
    young_children: int = Field(default=0, ge=0, le=20)  # 6세 이하 자녀 수
    bonus: Won = 0
    retro_pay: Won = 0
    settlement: Won = 0
    welfare_points: Won = 0
    welfare_public: bool = False                      # 공무원 복지점수
    other_taxable: Won = 0
    other_taxfree: Won = 0


@router.post("/salary")
def estimate_salary(body: SalaryIn) -> dict:
    """총급여 계산 — 저장하지 않는다. 숫자는 세법 숫자와 같은 곳(tax_rules)에서."""
    return tax_rules.salary_lines(body.model_dump())


class TaxProfileIn(BaseModel):
    gross_salary: int = Field(default=0, ge=0, le=10_000_000_000)  # 세전 총급여(비과세 뺀 것), 0 = 모름
    salary_parts: SalaryIn | None = None                            # 총급여 계산기 입력값 (다시 열 때 그대로)
    homeless_head: bool | None = None                               # 무주택 세대주, None = 모름
    children: int = Field(default=0, ge=0, le=20)                   # 카드 공제 한도에 쓰는 자녀 수
    payment_kinds: dict[str, Literal["credit", "debit", "none"]] = Field(default_factory=dict, max_length=300)


@router.put("/tax-profile")
def save_tax_profile(body: TaxProfileIn, conn: Conn) -> dict:
    """절세 계산에 쓰는 내 정보를 저장하고 새로 계산한 절세 분석을 돌려준다."""
    conn.execute("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                 (tax.PROFILE_KEY, json.dumps(body.model_dump(), ensure_ascii=False)))
    conn.commit()
    return tax.compute(conn)


class ReportIn(BaseModel):
    months: Literal[1, 3, 6, 12] = 3
    model: str = ""


@router.get("/reports")
def list_reports(conn: Conn, limit: Annotated[int, Query(ge=1, le=100)] = 20) -> list[dict]:
    rows = conn.execute("SELECT r.*, NULL AS dataset_name, NULL AS parent_name FROM runs r WHERE kind = ? "
                        "ORDER BY id DESC LIMIT ?", (KIND, limit)).fetchall()
    return [run_dict(r) for r in rows]


@router.post("/reports", status_code=201)
def create_report(body: ReportIn, conn: Conn) -> dict:
    try:
        facts.compute(conn, body.months)  # 분석할 수 없으면 실행을 만들기 전에 알려 준다
        run_id = start_run(conn, KIND, body.model_dump(), name=f"소비 습관 분석 · 최근 {body.months}개월")
    except (InsightsError, JobError) as e:
        raise HTTPException(400, str(e)) from None
    return _run(conn, run_id)


@router.get("/reports/{run_id}")
def read_report(run_id: int, conn: Conn) -> dict:
    run = _run(conn, run_id)
    if run["kind"] != KIND:
        raise HTTPException(404, "소비 습관 분석이 아닙니다")
    report = None
    if run.get("artifact_path"):
        try:
            report = json.loads((data_dir() / run["artifact_path"] / "report.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            report = None
    return {**run, "report": report}
