"""소비 분석 · 급여가 같이 쓰는 입력 스키마."""

from typing import Annotated

from pydantic import BaseModel, Field

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
