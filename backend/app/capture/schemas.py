"""캡쳐 판독 스키마 — 저장 전 초안, 판독 결과, 사용자 확인."""

from pydantic import BaseModel

from app.ledger.schemas import CategorySource, TransactionIn, TransferKind, TxType


class TransactionDraft(BaseModel):
    """이미지에서 추출한 저장 전 거래 (사용자가 확인 후 저장)."""

    occurred_on: str
    type: TxType
    transfer_kind: TransferKind | None = None
    amount: int
    merchant: str = ""
    category_id: int | None = None
    payment_method: str = ""
    memo: str = ""
    category_source: CategorySource | None = None
    duplicate_of: int | None = None
    warnings: list[str] = []


class ExtractionResult(BaseModel):
    extraction_id: int
    drafts: list[TransactionDraft]


class ConfirmItem(BaseModel):
    draft_index: int
    include: bool
    transaction: TransactionIn | None = None  # include=True 일 때 저장할 값 (사용자가 고친 최종값)


class ExtractionConfirm(BaseModel):
    items: list[ConfirmItem]
