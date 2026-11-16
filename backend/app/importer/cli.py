"""뱅크샐러드 엑셀 가져오기 CLI.

    uv run python -m app.importer.cli ~/Downloads/2025-10-08~2026-10-08.xlsx --dry-run
    uv run python -m app.importer.cli ~/Downloads/권민석님_….zip
"""

import argparse
import json
from pathlib import Path

from app.core.db import connect, init_db
from app.importer.banksalad import ImportError_, run_import


def main() -> None:
    p = argparse.ArgumentParser(description="뱅크샐러드 가계부 내보내기(xlsx/zip) 가져오기")
    p.add_argument("file", type=Path)
    p.add_argument("--dry-run", action="store_true", help="저장하지 않고 결과만 미리 보기")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    init_db()
    conn = connect()
    try:
        report = run_import(conn, args.file.expanduser().read_bytes(), args.file.name, dry_run=args.dry_run)
    except ImportError_ as e:
        raise SystemExit(f"가져오기 실패: {e}") from None
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return
    period = report["period"] or {}
    print(f"{'[미리보기] ' if report['dry_run'] else ''}{args.file.name}: {report['rows']}행 · {period.get('from')} ~ {period.get('to')}")
    print("  처리:", ", ".join(f"{k} {v}" for k, v in report["actions"].items()))
    for m in report["mapping"]:
        print(f"    {m['count']:>5}  {m['rule']}")
    if not report["dry_run"]:
        print(f"  저장 {report['inserted']}건 (가져오기 #{report['batch_id']}) · 분류 필요 {report['needs_review']} · "
              f"정기지출 매칭 {report['recurring_matched']} · 내 규칙으로 분류 {report['filled_by_rule']}")


if __name__ == "__main__":
    main()
