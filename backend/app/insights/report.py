"""LLM 소비 습관 보고서 — 코드가 계산한 번호 붙은 사실(facts.py)만 근거로 습관·고정비·저금·절세를 해석하고 실천 제안을 쓴다.

근거 규칙: 사실에 없는 숫자·가맹점을 지어내지 않는다. 항목마다 근거 사실 번호를 단다 — 코드가 목록에 없는 번호를 지우고 그 수
(citations_dropped)와 근거가 하나도 남지 않은 항목 수(ungrounded)를 기록한다. 훈계가 아니라 정보 정리 + 제안.
절세 팁은 공제 항목(item)만 고르게 하고, 금액(추가 절세·효과가 나는 납입액)은 코드가 tax.py 의 계산값을 붙인다.
"""

from collections.abc import Awaitable, Callable

from app.insights.fmt import won
from app.insights.tax import TITLES as TAX_TITLES
from app.llm.client import structured

TONES = ("good", "neutral", "watch")
TAX_ITEMS = (*TAX_TITLES, "other")
TONE_KO = {"good": "잘하고 있어요", "neutral": "특징", "watch": "살펴볼 점"}

_IDS = {"type": "array", "items": {"type": "integer"}}
_NOTE = {"type": "object", "properties": {"title": {"type": "string"}, "tone": {"type": "string", "enum": list(TONES)},
                                         "detail": {"type": "string"}, "fact_ids": _IDS},
         "required": ["title", "tone", "detail", "fact_ids"]}
SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "headline": {"type": "string"},
        "summary": {"type": "string"},
        "habits": {"type": "array", "items": _NOTE},
        "money_notes": {"type": "array", "items": _NOTE},
        "tax_tips": {"type": "array", "items": {"type": "object", "properties": {
            "item": {"type": "string", "enum": list(TAX_ITEMS)}, "action": {"type": "string"}, "reason": {"type": "string"},
            "fact_ids": _IDS}, "required": ["item", "action", "reason", "fact_ids"]}},
        "category_notes": {"type": "array", "items": {"type": "object", "properties": {
            "category": {"type": "string"}, "note": {"type": "string"}, "fact_ids": _IDS},
            "required": ["category", "note", "fact_ids"]}},
        "suggestions": {"type": "array", "items": {"type": "object", "properties": {
            "action": {"type": "string"}, "reason": {"type": "string"}, "fact_ids": _IDS,
            "monthly_saving": {"type": "integer", "minimum": 0}}, "required": ["action", "reason", "fact_ids", "monthly_saving"]}},
        "questions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["title", "headline", "summary", "habits", "suggestions", "money_notes", "tax_tips"],
}

SYSTEM = """당신은 사용자의 개인 가계부를 함께 보는 소비 습관 코치입니다.
- 근거는 사용자가 준 '사실' 목록(번호·내용)뿐입니다. 사실에 없는 숫자·가맹점·사건을 지어내지 마세요. 숫자는 사실의 값을 그대로 쓰거나
  '약 ○○만 원'처럼 반올림만 하세요.
- 습관(habits)·카테고리 메모·제안마다 근거 사실 번호(fact_ids)를 다세요. 목록에 없는 번호는 쓰지 마세요.
- 소비를 비난하거나 훈계하지 마세요. 사실 → 해석 → 실천할 수 있는 제안 순서로, 잘하고 있는 점(tone=good)도 찾으세요.
- 제안은 구체적으로(어느 카테고리·가맹점·요일·시간대를, 얼마나). monthly_saving(월 절감 추정, 원)은 사실의 숫자로 계산할 수 있을 때만
  넣고 아니면 0. 가맹점 이름이 법인명이면(예: 배달 앱 운영사) 흔히 알려진 서비스로 풀어 써도 됩니다.
- '일회성 큰 지출'은 습관이 아니니 습관으로 해석하지 마세요. 카테고리 없는 결제·분류 필요가 많거나 비교 기간이 없으면 그 한계를
  questions 에 쓰세요.
- money_notes(고정비·저금)는 고정 지출·저금·주수입 배분 사실로 씁니다. 저금 칸에 있어도 빚을 갚는 돈(예: 상환)처럼 저금이 아닌 것은
  구분해 말하고, 계획과 실제가 다르거나 금액이 바뀐 항목, 구독처럼 줄일 수 있는 고정 지출을 짚으세요.
- tax_tips(절세)는 '절세' 사실만 근거로 씁니다. item 에 공제 항목 키(card·pension·housing_saving·rent_loan·insurance·isa, 그 밖은
  other)를 고르세요 — 금액은 코드가 붙이니 새로 계산하지 말고, 사실에 있는 금액만 그대로 쓰세요. 효과가 큰 순서로, 연말(12월 31일)까지
  할 수 있는 것을 먼저. 새 금융상품 가입을 권하지 말고 이미 있는 계좌·공제 한도 안에서 말하세요. 요건(무주택 세대주, 국민주택규모,
  총급여 등)이 확인되지 않았거나 총급여가 가정이면 그 점을 questions 에 쓰세요. 세법 판단은 추정이라고 밝히세요. 한국어로 간결하게."""

LlmJson = Callable[[str, str, str, dict, str | None], Awaitable[dict]]


async def _default_llm(feature: str, system: str, prompt: str, schema: dict, model: str | None) -> dict:
    return await structured(feature, prompt, schema, model=model, system_prompt=system)


LLM: LlmJson = _default_llm  # 테스트에서 가짜로 바꾼다


def build_prompt(facts: dict) -> str:
    cats = "\n".join(f"- {c['name']}: {c['description'] or '설명 없음'} (기간당 예산 {won(c['budget']) if c['budget'] else '없음'})"
                     for c in facts["categories"])
    base = facts["baseline"]["label"] if facts["baseline"] else "없음 (데이터가 부족해 비교하지 않음)"
    lines = "\n".join(f"[{f['id']}] {f['text']}" for f in facts["facts"])
    notes = "".join(f"\n참고: {n}" for n in facts["notes"])
    return (f"분석 기간: {facts['window']['label']} (수입일 기준 {facts['window']['periods']}개 기간), 비교 기간: {base}{notes}\n"
            f"카테고리(설명·예산):\n{cats}\n\n사실:\n{lines}\n\n"
            "위 사실만 근거로 소비 습관 보고서를 쓰세요. title 은 짧게, headline 은 한 문장, summary 는 세 문장 이내. "
            "habits 3~6개(tone: good 잘하는 점 / neutral 특징 / watch 살펴볼 점), category_notes 는 눈에 띄는 카테고리만, "
            "suggestions 2~4개(변동비), money_notes 2~4개(고정비·저금), tax_tips 1~4개(절세), questions 는 데이터 한계나 "
            "사용자에게 확인할 것.")


def clean(raw: dict, allowed: set[int], cap: int, tax_items: list[dict] | None = None) -> tuple[dict, int, int]:
    """형식을 맞추고 목록에 없는 사실 번호를 지운다. 절세 팁에는 코드가 계산한 그 항목의 금액을 붙인다.
    (보고서, 지운 번호 수, 근거가 하나도 없는 항목 수)"""
    dropped = ungrounded = 0

    def ids(item: dict) -> list[int]:
        nonlocal dropped, ungrounded
        got = [i for i in item.get("fact_ids") or [] if isinstance(i, int) and not isinstance(i, bool)]
        keep = sorted({i for i in got if i in allowed})
        dropped += len(got) - len([i for i in got if i in allowed])
        if not keep:
            ungrounded += 1
        return keep

    def text(v: object) -> str:
        return str(v or "").strip()

    def items(key: str) -> list[dict]:
        return [x for x in raw.get(key) or [] if isinstance(x, dict)]

    def notes_of(key: str) -> list[dict]:
        return [{"title": text(h.get("title")), "tone": h.get("tone") if h.get("tone") in TONES else "neutral",
                 "detail": text(h.get("detail")), "fact_ids": ids(h)} for h in items(key) if text(h.get("detail"))][:8]

    habits = notes_of("habits")
    money = notes_of("money_notes")
    by_key = {x["key"]: x for x in tax_items or []}
    tips = []
    for t in items("tax_tips"):
        if not text(t.get("action")):
            continue
        key = t.get("item") if t.get("item") in TAX_ITEMS else "other"
        code = by_key.get(key)
        tips.append({"item": key, "title": TAX_TITLES.get(key, "기타"), "action": text(t["action"]), "reason": text(t.get("reason")),
                     "fact_ids": ids(t), "extra_saving": code["extra_saving"] if code else 0,
                     "useful": code["useful"] if code else 0, "effect": code["effect"] if code else 0})
    notes = [{"category": text(c.get("category")), "note": text(c.get("note")), "fact_ids": ids(c)}
             for c in items("category_notes") if text(c.get("note"))][:8]
    suggestions = []
    for s in items("suggestions"):
        if not text(s.get("action")):
            continue
        try:
            saving = max(0, min(int(s.get("monthly_saving") or 0), cap))
        except (TypeError, ValueError):
            saving = 0
        suggestions.append({"action": text(s["action"]), "reason": text(s.get("reason")), "fact_ids": ids(s),
                            "monthly_saving": saving})
    return {"title": text(raw.get("title")) or "소비 습관 분석", "headline": text(raw.get("headline")),
            "summary": text(raw.get("summary")), "habits": habits, "money_notes": money, "tax_tips": tips[:5],
            "category_notes": notes, "suggestions": suggestions[:5],
            "questions": [text(q) for q in raw.get("questions") or [] if text(q)][:5]}, dropped, ungrounded


async def analyze(facts: dict, model: str | None) -> tuple[dict, int, int]:
    raw = await LLM("spending_report", SYSTEM, build_prompt(facts), SCHEMA, model)
    cap = max(0, int(facts["stats"]["kpis"]["avg_total"]))
    return clean(raw if isinstance(raw, dict) else {}, {f["id"] for f in facts["facts"]}, cap, facts["stats"]["tax"]["items"])


def to_markdown(report: dict, facts: dict) -> str:
    refs = lambda ids: "".join(f" [{i}]" for i in ids)  # noqa: E731
    out = [f"# {report['title']}", "", f"> {report['headline']}" if report["headline"] else "",
           "", f"분석 기간 {facts['window']['label']} · 비교 기간 {facts['baseline']['label'] if facts['baseline'] else '없음'}", "",
           report["summary"], ""]
    if report["habits"]:
        out += ["## 습관", *[f"- **{h['title']}** ({TONE_KO[h['tone']]}) {h['detail']}{refs(h['fact_ids'])}" for h in report["habits"]], ""]
    if report["money_notes"]:
        out += ["## 고정비·저금", *[f"- **{h['title']}** ({TONE_KO[h['tone']]}) {h['detail']}{refs(h['fact_ids'])}"
                                  for h in report["money_notes"]], ""]
    if report["tax_tips"]:
        out += ["## 절세 (추정)", *[f"- **{t['title']}** {t['action']} — {t['reason']}"
                                   + (f" (연 약 {won(t['extra_saving'])} 더 절세 추정)" if t["extra_saving"] else "") + refs(t["fact_ids"])
                                   for t in report["tax_tips"]], ""]
    if report["category_notes"]:
        out += ["## 카테고리", *[f"- {c['category']}: {c['note']}{refs(c['fact_ids'])}" for c in report["category_notes"]], ""]
    if report["suggestions"]:
        out += ["## 제안", *[f"- {s['action']} — {s['reason']}"
                             + (f" (월 약 {won(s['monthly_saving'])} 절감 추정)" if s["monthly_saving"] else "") + refs(s["fact_ids"])
                             for s in report["suggestions"]], ""]
    if report["questions"]:
        out += ["## 확인할 것", *[f"- {q}" for q in report["questions"]], ""]
    out += ["## 근거 사실", *[f"[{f['id']}] {f['text']}" for f in facts["facts"]]]
    return "\n".join(out).strip() + "\n"
