"""캡쳐 이미지 → 거래내역 추출.

판독기는 TransactionExtractor 인터페이스 뒤에 둔다. 테스트는 가짜 구현체를 주입한다.
- AgentSdkExtractor: Vision LLM(Claude)이 이미지를 직접 보고 거래를 낸다.
- OcrLlmExtractor: Unlimited-OCR-2(app/ocr)가 이미지를 글로 읽고, LLM 은 그 글만 보고 거래로 나눈다 (글만 보내므로 로컬 LLM ·
  vLLM 경로도 된다). 판독 방식 auto 에서 OCR 서버가 안 되면 Vision 으로 한 번 더 읽는다.
get_extractor() 가 .env 의 판독 방식(MLG_OCR_MODE · MLG_OCR_URL)을 부를 때마다 다시 본다.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Protocol

import asyncio

from app.llm.client import LLMError, default_model, image_block, structured
from app.ocr import client as ocr

# 프롬프트를 바꾸면 올린다. 판독 기록에 남아 버전별 정확도를 비교할 수 있다.
PROMPT_VERSION = "2026-10-08.r3"

TX_SCHEMA = {
    "type": "object",
    "properties": {
        "transactions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "occurred_on": {"type": "string", "description": "YYYY-MM-DD"},
                    "type": {"type": "string", "enum": ["expense", "income", "transfer", "refund"]},
                    "transfer_kind": {"type": ["string", "null"], "enum": ["internal", "external", None]},
                    "amount": {"type": "integer", "description": "원 단위 양수"},
                    "merchant": {"type": "string", "description": "가맹점명 또는 이체 상대"},
                    "category": {"type": ["string", "null"], "description": "아래 카테고리 이름 중 하나"},
                    "payment_method": {"type": "string", "description": "카드/계좌 이름, 모르면 빈 문자열"},
                    "memo": {"type": "string"},
                },
                "required": ["occurred_on", "type", "transfer_kind", "amount", "merchant", "category",
                             "payment_method", "memo"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["transactions"],
    "additionalProperties": False,
}


@dataclass
class ExtractContext:
    today: date
    categories: list[dict]  # {"name", "description"}
    own_accounts: list[str]
    rules: list[tuple[str, str]] = field(default_factory=list)  # (가맹점 키, 카테고리) 사용자 분류 규칙


class ExtractionError(Exception):
    pass


class TransactionExtractor(Protocol):
    async def extract(self, image: bytes, media_type: str, ctx: ExtractContext) -> list[dict]: ...


def build_prompt(ctx: ExtractContext) -> str:
    cats = "\n".join(f"- {c['name']}: {c['description']}" for c in ctx.categories)
    accounts = ", ".join(ctx.own_accounts) or "(등록 없음)"
    rules = ""
    if ctx.rules:
        lines = "\n".join(f"- {k} → {c}" for k, c in ctx.rules)
        rules = f"- 사용자가 직접 정한 가맹점 분류입니다. 같거나 비슷한 가맹점이면 이 분류를 따르세요:\n{lines}\n"
    return f"""이 이미지는 한국 사용자의 결제/가계부 앱 화면 캡쳐(뱅크샐러드, 카드사 앱, 결제 완료 화면 등)입니다.
화면에 보이는 거래를 모두 추출하세요. 화면에 없는 거래를 지어내지 마세요.

규칙:
- 오늘은 {ctx.today.isoformat()} 입니다. 연도가 안 보이면 오늘 기준 가장 가까운 과거 날짜로 판단하세요.
- amount는 항상 양수 정수(원). 지출/수입 구분은 type으로 합니다.
- 카드 결제·구매는 expense, 급여 같은 고정 수입은 income, 내가 보낸 계좌 이체는 transfer.
- 친구·지인에게 받은 송금(더치페이 1/n 정산 등)과 결제 환불·부분 취소 입금은 refund (수입이 아님).
- transfer일 때 상대가 사용자 본인 계좌({accounts})면 transfer_kind="internal", 그 외 "external". transfer가 아니면 null.
- 취소된 결제는 제외하세요.
- category는 다음 중 가장 알맞은 이름 하나 (이체는 null):
{cats}
{rules}"""


class AgentSdkExtractor:
    """Claude Agent SDK 판독기. feature 는 사용량 기록용 (판독 재평가는 'ocr_eval')."""

    def __init__(self, model: str | None = None, feature: str = "ocr_extract"):
        self.model = default_model(model)
        self.feature = feature

    async def extract(self, image: bytes, media_type: str, ctx: ExtractContext) -> list[dict]:
        content = [image_block(image, media_type), {"type": "text", "text": build_prompt(ctx)}]
        try:
            out = await structured(self.feature, content, TX_SCHEMA, model=self.model)
        except LLMError as e:
            raise ExtractionError(f"이미지 판독 실패: {e}") from None
        return out["transactions"]


OCR_PROMPT_VERSION = "2026-11-16.ocr1"


def build_text_prompt(ctx: ExtractContext, text: str) -> str:
    """OCR 이 읽은 글 → 거래. 규칙은 Vision 프롬프트와 같고, 이미지 대신 판독 글을 준다."""
    return (build_prompt(ctx).replace("이 이미지는 한국 사용자의", "아래 글은 한국 사용자의", 1)
            .replace("화면에 보이는 거래를 모두 추출하세요.", "OCR(Unlimited-OCR-2)이 화면을 읽은 글입니다. 글에 있는 거래를 모두 추출하세요.", 1)
            + "- OCR 글은 줄 · 칸이 섞이거나 글자가 조금 틀릴 수 있어요. 금액 · 날짜 · 가맹점이 한 줄로 이어지게 맞춰 읽고, "
              "확실하지 않은 거래는 지어내지 마세요.\n\n[OCR 글]\n" + text[:20000])


class OcrLlmExtractor:
    """OCR(글자) → LLM(거래로 나누기). fallback 이 있으면 OCR 실패 때 그 판독기로 읽는다 (판독 방식 auto)."""

    prompt_version = OCR_PROMPT_VERSION

    def __init__(self, model: str | None = None, fallback: TransactionExtractor | None = None):
        self.llm_model = default_model(model)
        self.model = f"{ocr.model()}+{self.llm_model}"
        self.fallback = fallback
        self.last_text: str | None = None
        self.note: str | None = None

    async def extract(self, image: bytes, media_type: str, ctx: ExtractContext) -> list[dict]:
        self.last_text, self.note = None, None
        try:
            got = await asyncio.to_thread(ocr.read_text, image, media_type)
        except ocr.OcrError as e:
            if self.fallback is None:
                raise ExtractionError(f"OCR 판독 실패: {e}") from None
            self.note = f"OCR 실패 → Vision 으로 읽음: {e}"
            self.model = getattr(self.fallback, "model", "vision")
            self.prompt_version = PROMPT_VERSION
            return await self.fallback.extract(image, media_type, ctx)
        self.last_text = got["text"]
        try:
            out = await structured("ocr_structure", build_text_prompt(ctx, got["text"]), TX_SCHEMA, model=self.llm_model)
        except LLMError as e:
            raise ExtractionError(f"OCR 글 정리 실패: {e}") from None
        return out["transactions"]


def get_extractor() -> TransactionExtractor:
    """FastAPI 의존성 — 부를 때마다 판독 방식을 본다. 테스트에서는 app.dependency_overrides 로 교체한다."""
    if ocr.enabled() or ocr.mode() == "ocr":  # ocr 인데 주소가 없으면 판독이 '주소 없음'으로 실패해 그 사실이 기록된다
        return OcrLlmExtractor(fallback=AgentSdkExtractor() if ocr.mode() == "auto" else None)
    return AgentSdkExtractor()
