"""작업: 캡쳐 판독 재평가 — 저장된 이미지를 현재 프롬프트·모델로 다시 판독해 확정값과 비교 (#1 evaluate 래퍼)."""

import asyncio

from app.capture.extraction import evaluate, golden_set
from app.capture.extractor import AgentSdkExtractor
from app.runs.runner import JobError, JobSpec, RunContext, register

# 테스트에서 가짜 판독기로 바꿔 끼운다
EXTRACTOR_FACTORY = AgentSdkExtractor


def run(ctx: RunContext, params: dict) -> dict:
    limit = params.get("limit") or None
    total = len(golden_set(ctx.conn, limit))
    if total == 0:
        raise JobError("재평가할 판독 기록이 없습니다 — 캡쳐로 입력하고 저장한 기록(이미지 포함)이 필요해요")
    extractor = EXTRACTOR_FACTORY(params.get("model") or None)
    if hasattr(extractor, "feature"):
        extractor.feature = "ocr_eval"  # 사용량을 '판독 재평가'로 기록
    ctx.log(f"이미지 {total}장 재평가 · 모델 {extractor.model} · 규칙 {'켬' if params.get('use_rules', True) else '끔'}")
    running = {"matched": 0, "predicted": 0, "actual": 0}

    def on_progress(n: int, t: int, info: dict) -> None:
        ctx.check_cancel()
        for k in running:
            running[k] += info[k]
        ctx.metrics(
            n,
            precision=running["matched"] / running["predicted"] if running["predicted"] else 0,
            recall=running["matched"] / running["actual"] if running["actual"] else 0,
        )
        ctx.log(f"[{n}/{t}] 기록 #{info['log_id']}: 예측 {info['predicted']} · 정답 {info['actual']} · 매칭 {info['matched']}")
        ctx.progress(n / t)

    return asyncio.run(evaluate(ctx.conn, extractor, limit, params.get("use_rules", True), on_progress))


register(JobSpec(
    kind="ocr_eval",
    title="캡쳐 판독 재평가",
    description="보관된 캡쳐를 현재 프롬프트·모델로 다시 판독해 확정값과 비교합니다 (정밀도·재현율·필드별 정확도). LLM을 실제로 호출합니다.",
    run=run,
    defaults={"limit": 10, "use_rules": True, "model": ""},
    uses_llm=True,
))
