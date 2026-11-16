"""급여명세서 이미지 → 명세서 초안 (저장하지 않음 — 화면에서 고친 뒤 저장한다).

OCR(Unlimited-OCR-2, app/ocr)이 켜져 있으면 OCR 글을 LLM 이 칸으로 나누고(글만 보내므로 로컬 LLM 경로도 된다), 아니면 Vision
LLM 이 이미지를 직접 본다. 판독 방식 auto 에서 OCR 이 안 되면 Vision 으로 다시 읽는다. 숫자는 모델이 읽은 그대로이고, 합계 검산은
analysis.view 가 한다.
"""

import asyncio

from app.llm.client import LLMError, image_block, structured
from app.ocr import client as ocr

_AMOUNT = {"type": "integer", "description": "원 단위 정수, 없으면 0"}
FIELDS = ("taxable_pay", "nontaxable_pay", "national_pension", "health_insurance", "long_term_care", "employment_insurance",
          "income_tax", "local_income_tax", "other_deductions")
SCHEMA = {
    "type": "object",
    "properties": {
        "pay_month": {"type": "string", "description": "귀속 월 YYYY-MM"},
        "paid_on": {"type": ["string", "null"], "description": "지급일 YYYY-MM-DD, 안 보이면 null"},
        "kind": {"type": "string", "enum": ["regular", "bonus", "retro", "other"]},
        "employer": {"type": "string", "description": "회사 이름, 안 보이면 빈 문자열"},
        **{k: _AMOUNT for k in FIELDS},
        "net_pay": {"type": ["integer", "null"], "description": "실지급액(차인지급액), 안 보이면 null"},
        "items": {"type": "array", "items": {"type": "object", "properties": {
            "label": {"type": "string"}, "amount": {"type": "integer"},
            "kind": {"type": "string", "enum": ["pay_taxable", "pay_nontaxable", "deduction"]}},
            "required": ["label", "amount", "kind"], "additionalProperties": False}},
    },
    "required": ["pay_month", "paid_on", "kind", "employer", *FIELDS, "net_pay", "items"],
    "additionalProperties": False,
}

PROMPT = """한국 회사의 급여명세서를 칸으로 나누세요. 보이는 숫자만 쓰고 지어내지 마세요.
- 지급 항목: 기본급 · 수당 · 상여 등. 비과세(식대 월 20만 원까지 · 자가운전보조금 · 보육수당 등 '비과세'로 적힌 줄)는
  nontaxable_pay 에, 나머지는 taxable_pay 에 더하세요. 명세서에 '과세 합계'가 있으면 그 값을 쓰세요.
- 공제 항목: 국민연금 · 건강보험 · 장기요양 · 고용보험 · 소득세 · 지방소득세(주민세)는 각 칸에, 나머지(노조비 · 사우회비 · 대출 상환 ·
  연말정산 분납 등)는 other_deductions 에 더하세요.
- kind: 정기 월급이면 regular, 상여만 따로 나온 명세서면 bonus, 임금 소급분이면 retro.
- items 에는 명세서의 모든 줄을 그대로 (label · amount · kind).
- 금액은 원 단위 양수 정수. 연도가 안 보이면 오늘({today}) 기준 가장 가까운 과거로."""


class SalaryExtractError(Exception):
    pass


async def extract(image: bytes, media_type: str, today: str) -> dict:
    """→ 초안 dict (+ via: 'ocr' | 'vision', note)."""
    prompt = PROMPT.format(today=today)
    note = None
    if ocr.enabled() or ocr.mode() == "ocr":
        try:
            got = await asyncio.to_thread(ocr.read_text, image, media_type)
            try:
                out = await structured("ocr_structure", prompt + "\n\n[OCR 글 — Unlimited-OCR-2]\n" + got["text"][:20000], SCHEMA)
            except LLMError as e:
                raise SalaryExtractError(f"OCR 글 정리 실패: {e}") from None
            return {**out, "via": "ocr", "ocr_text": got["text"], "note": None}
        except ocr.OcrError as e:
            if ocr.mode() == "ocr":
                raise SalaryExtractError(f"OCR 판독 실패: {e}") from None
            note = f"OCR 실패 → Vision 으로 읽음: {e}"
    try:
        out = await structured("salary_extract", [image_block(image, media_type), {"type": "text", "text": prompt}], SCHEMA)
    except LLMError as e:
        raise SalaryExtractError(f"이미지 판독 실패: {e}") from None
    return {**out, "via": "vision", "ocr_text": None, "note": note}
