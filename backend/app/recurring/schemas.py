"""정기지출 입력 스키마 — 정기지출 카테고리·항목·순서, 반복 지출 후보 수락."""

from typing import Literal

from pydantic import BaseModel, Field


class RecurringGroupIn(BaseModel):
    """정기지출 카테고리. saving(저금·투자처럼 쌓이는 돈) / expense(나가는 돈)"""

    name: str = Field(min_length=1)
    kind: Literal["saving", "expense"] = "expense"
    icon: str = ""
    sort_order: int = 0


class RecurringIn(BaseModel):
    name: str = Field(min_length=1)
    group_id: int
    icon: str = ""
    amount: int = Field(default=0, ge=0)
    day_of_month: int | None = Field(default=1, ge=1, le=31)  # None = 출금일 미정 (유동적)
    match_keyword: str = ""
    memo: str = ""
    active: bool = True
    sort_order: int = 0


class CandidateAccept(BaseModel):
    """반복 지출 후보 수락: 새 정기지출로 등록하거나(item_id 없음) 기존 항목에 합친다(item = 고친 값)."""

    item: RecurringIn
    item_id: int | None = None
    # 지난 기간 결제도 이 정기지출로 연결 — 지난 달들이 '확인됨'이 되고 그 결제는 변동비에서 빠진다
    link_past: bool = True


class RecurringOrderGroup(BaseModel):
    """정기지출 화면 드래그 결과: 카테고리별 항목 id를 화면 순서대로."""

    group_id: int
    item_ids: list[int]
