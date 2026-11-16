"""캡쳐 판독 재평가 CLI (#1).

저장해 둔 판독 이미지(확정된 것)를 현재 프롬프트·모델로 다시 판독해 확정값과 비교한다.
프롬프트나 모델을 바꾼 뒤 전후를 비교할 때 쓴다. LLM을 실제로 호출하므로 이미지 수만큼 시간이 걸린다.

    uv run python -m app.capture.eval_cli --limit 20
    uv run python -m app.capture.eval_cli --no-rules          # 사용자 규칙을 빼고 (규칙 효과 비교)
    uv run python -m app.capture.eval_cli --model claude-sonnet-5-5
"""

import argparse
import asyncio
import json

from app.capture.extraction import evaluate, golden_set
from app.capture.extractor import AgentSdkExtractor, OcrLlmExtractor
from app.core.db import connect, init_db


def _fmt(v: float | None) -> str:
    return "  -  " if v is None else f"{v * 100:5.1f}%"


def main() -> None:
    p = argparse.ArgumentParser(description="캡쳐 판독 재평가")
    p.add_argument("--limit", type=int, help="최근 N장만")
    p.add_argument("--model", help="모델 (기본: MLG_LLM_MODEL 또는 claude-opus-5-5)")
    p.add_argument("--no-rules", action="store_true", help="사용자 분류 규칙 없이 판독")
    p.add_argument("--via", choices=("vision", "ocr"), default="vision", help="vision: Vision LLM · ocr: Unlimited-OCR-2 → LLM 정리")
    p.add_argument("--json", action="store_true", help="결과를 JSON으로 출력")
    args = p.parse_args()

    init_db()
    conn = connect()
    total = len(golden_set(conn, args.limit))
    if total == 0:
        print("재평가할 기록이 없습니다. 캡쳐 입력 후 저장한 기록(이미지 포함)이 필요합니다.")
        return
    print(f"재평가: 이미지 {total}장 · 규칙 {'끔' if args.no_rules else '켬'}")

    def progress(n: int, t: int, info: dict) -> None:
        print(f"  [{n}/{t}] 기록 #{info['log_id']}: 예측 {info['predicted']} · 정답 {info['actual']} · 매칭 {info['matched']}")

    extractor = OcrLlmExtractor(args.model) if args.via == "ocr" else AgentSdkExtractor(args.model, feature="ocr_eval")
    report = asyncio.run(evaluate(conn, extractor, args.limit, not args.no_rules, progress))
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return
    print(f"\n모델 {report['model']} · 프롬프트 {report['prompt_version']}")
    print(f"정밀도 {_fmt(report['precision'])}  재현율 {_fmt(report['recall'])}  "
          f"완전 일치 {_fmt(report['exact_match_rate'])}  실패 {report['failed']}장")
    for f in report["fields"]:
        print(f"  {f['label']:<6} {_fmt(f['accuracy'])}")


if __name__ == "__main__":
    main()
