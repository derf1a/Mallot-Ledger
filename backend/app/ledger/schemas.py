"""가계부 입력 스키마 — 거래·개인설정·내 계좌."""

from typing import Literal

from pydantic import BaseModel, Field

TxType = Literal["expense", "income", "transfer", "refund"]  # refund = 정산·환불 입금 (변동비에서 빠짐)
CategorySource = Literal["user", "llm", "rule", "import"]
TransferKind = Literal["internal", "external"]


class SettingsIn(BaseModel):
    owner_name: str | None = None
    monthly_income: int | None = Field(default=None, ge=0)
    payday: int | None = Field(default=None, ge=1, le=31)
    loan_counterparties: str | None = None  # 빌린 돈을 받는 상대 (쉼표 구분 키워드)
    search_months: int | None = Field(default=None, ge=0, le=600)  # 가계부 검색 기본 범위 (최근 N개월, 0 = 전체)


class AccountIn(BaseModel):
    name: str = Field(min_length=1)
    keyword: str = ""


class TransactionIn(BaseModel):
    occurred_on: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    occurred_time: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}(:\d{2})?$")
    type: TxType
    transfer_kind: TransferKind | None = None
    amount: int = Field(ge=0)
    merchant: str = ""
    category_id: int | None = None
    recurring_id: int | None = None
    payment_method: str = ""
    memo: str = ""
    source: Literal["manual", "image", "import"] = "manual"
    # 분류 출처: user(직접 고름) / llm(AI 제안 그대로) / rule(가맹점 규칙) / import(외부 서비스 분류). 비우면 규칙이 있을 때 자동 적용
    category_source: CategorySource | None = None
    # 사용자가 직접 분류를 확정했으면 True → '분류 필요' 표시를 끈다
    reviewed: bool = False
