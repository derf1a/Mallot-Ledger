"""작업: LLM 소비 습관 분석 — 가계부 거래에서 사실을 계산하고(app/insights/facts.py) LLM 이 그 사실만 근거로 보고서를 쓴다.

단계: 사실 계산(끝난 기간 N개 + 비교 기간, 고정 지출·저금, 올해 절세) → facts.json → LLM 보고서(근거 번호 검증, 절세 금액은
코드 값) → report.json·report.md.
"""

import asyncio
import json

from app.insights import facts as insight_facts, report
from app.insights.facts import InsightsError
from app.runs.runner import JobError, JobSpec, RunContext, register

DEFAULTS = {"months": 3, "model": ""}


def run(ctx: RunContext, params: dict) -> dict:
    months = int(params.get("months") or 3)
    try:
        facts = insight_facts.compute(ctx.conn, months)
    except InsightsError as e:
        raise JobError(str(e)) from None
    for note in facts["notes"]:
        ctx.log(note, "warn")
    ctx.log(f"분석 기간 {facts['window']['label']} · 비교 기간 {facts['baseline']['label'] if facts['baseline'] else '없음'} · "
            f"사실 {len(facts['facts'])}개")
    out = ctx.artifact_dir
    (out / "facts.json").write_text(json.dumps(facts, ensure_ascii=False, indent=1), encoding="utf-8")
    ctx.progress(0.3)
    ctx.check_cancel()

    model = str(params.get("model") or "") or None
    result, dropped, ungrounded = asyncio.run(report.analyze(facts, model))
    if dropped:
        ctx.log(f"목록에 없는 사실 번호 {dropped}개를 지웠습니다", "warn")
    if ungrounded:
        ctx.log(f"근거 번호가 없는 항목 {ungrounded}개", "warn")
    ctx.metrics(1, facts=len(facts["facts"]), habits=len(result["habits"]), suggestions=len(result["suggestions"]),
                money_notes=len(result["money_notes"]), tax_tips=len(result["tax_tips"]),
                citations_dropped=dropped, ungrounded=ungrounded)
    full = {**result, "months": months, "window": facts["window"], "baseline": facts["baseline"],
            "citations_dropped": dropped, "ungrounded": ungrounded, "facts": facts["facts"], "stats": facts["stats"]}
    (out / "report.json").write_text(json.dumps(full, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "report.md").write_text(report.to_markdown(result, facts), encoding="utf-8")
    ctx.set_artifact(out)
    ctx.progress(1.0)
    ctx.log(f"보고서: {result['title']}")
    return {"title": result["title"], "headline": result["headline"], "months": months, "window": facts["window"]["label"],
            "facts": len(facts["facts"]), "habits": len(result["habits"]), "suggestions": len(result["suggestions"]),
            "money_notes": len(result["money_notes"]), "tax_tips": len(result["tax_tips"]),
            "citations_dropped": dropped, "ungrounded": ungrounded}


register(JobSpec(
    kind="spending_report",
    title="LLM 소비 습관 분석",
    description="가계부 거래에서 코드가 사실(번호)을 계산하고, LLM 이 그 사실만 근거로 소비 습관·고정비·저금·절세 제안을 씁니다 "
                "(근거 번호 검증, 절세 금액은 코드 계산).",
    run=run,
    defaults=DEFAULTS,
    uses_llm=True,
))
