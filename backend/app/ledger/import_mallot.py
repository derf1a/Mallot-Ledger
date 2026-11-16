"""Mallot(가계부 · 투자를 같이 쓰던 앱) DB 의 가계부 데이터를 이 앱의 DB 로 옮긴다 — `make import-mallot DB=~/Mallot/data/wt.db`.

- 옮기는 것: 거래 · 카테고리 · 내 계좌 · 정기지출(칸 · 항목 · 건너뜀 · 반복 지출 제안) · 가맹점 규칙 · 캡쳐 판독 기록 · 뱅크샐러드
  가져오기 묶음, 그리고 가계부 설정(이름 · 월 주수입 · 수입일 · 빌린 돈 상대 · 검색 범위 · 절세 내 정보). 투자 · 실험실 테이블은 두고 온다.
- 스키마 v1 이 Mallot 의 마지막 가계부 테이블 모양 그대로라 같은 이름 칸을 그대로 복사한다 (이 앱에만 있는 칸은 기본값).
- 이 앱 DB 에 거래가 이미 있으면 멈춘다 (--replace 면 가계부 테이블을 비우고 옮긴다). 판독 이미지는 --images 면 data 폴더로 복사한다.
- id 를 그대로 옮겨서 거래 ↔ 정기지출 · 카테고리 · 판독 기록 연결이 유지된다.
"""

import argparse
import shutil
import sqlite3
import sys
from pathlib import Path

from app.core.db import connect, data_dir, init_db

# 부모부터 (외래 키 순서)
TABLES = ("categories", "accounts", "recurring_groups", "recurring_items", "recurring_skips", "recurring_candidates",
          "merchant_rules", "import_batches", "extraction_logs", "transactions")
SETTINGS = ("owner_name", "monthly_income", "payday", "loan_counterparties", "search_months", "tax_profile")


class ImportError_(Exception):
    pass


def _cols(conn: sqlite3.Connection, table: str, schema: str = "main") -> list[str]:
    return [r[1] for r in conn.execute(f"PRAGMA {schema}.table_info({table})")]


def run(source: Path, replace: bool = False, images: bool = False) -> dict:
    if not source.is_file():
        raise ImportError_(f"Mallot DB 파일이 없어요: {source}")
    init_db()
    conn = connect()
    try:
        conn.execute("ATTACH DATABASE ? AS src", (str(source),))
        have = {r[0] for r in conn.execute("SELECT name FROM src.sqlite_master WHERE type = 'table'")}
        if "transactions" not in have:
            raise ImportError_("가계부 거래 테이블(transactions)이 없는 DB 예요 — Mallot 의 data/wt.db 인지 확인하세요")
        if conn.execute("SELECT COUNT(*) FROM main.transactions").fetchone()[0] and not replace:
            raise ImportError_("이 앱 DB 에 거래가 이미 있어요 — 비우고 옮기려면 --replace")
        conn.execute("PRAGMA foreign_keys = OFF")
        counts = {}
        with conn:
            for t in reversed(TABLES):
                conn.execute(f"DELETE FROM main.{t}")
            for t in TABLES:
                if t not in have:
                    counts[t] = 0
                    continue
                cols = [c for c in _cols(conn, t) if c in set(_cols(conn, t, "src"))]
                names = ", ".join(cols)
                conn.execute(f"INSERT INTO main.{t} ({names}) SELECT {names} FROM src.{t}")
                counts[t] = conn.execute(f"SELECT COUNT(*) FROM main.{t}").fetchone()[0]
            marks = ", ".join("?" * len(SETTINGS))
            for key, value in conn.execute(f"SELECT key, value FROM src.settings WHERE key IN ({marks})", SETTINGS).fetchall():
                conn.execute("INSERT INTO main.settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                             (key, value))
        broken = conn.execute("PRAGMA foreign_key_check").fetchall()
        conn.execute("PRAGMA foreign_keys = ON")
        copied = 0
        if images:
            src_root = source.parent
            for (rel,) in conn.execute("SELECT image_path FROM main.extraction_logs WHERE image_path IS NOT NULL"):
                a, b = src_root / rel, data_dir() / rel
                if a.is_file() and not b.exists():
                    b.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(a, b)
                    copied += 1
        conn.execute("DETACH DATABASE src")
        return {"tables": counts, "images": copied, "broken_foreign_keys": len(broken)}
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Mallot DB 의 가계부 데이터를 옮긴다")
    ap.add_argument("db", type=Path, help="Mallot 의 data/wt.db")
    ap.add_argument("--replace", action="store_true", help="이 앱의 가계부 테이블을 비우고 옮긴다")
    ap.add_argument("--images", action="store_true", help="캡쳐 판독 이미지도 data 폴더로 복사")
    a = ap.parse_args(argv)
    from app.core import envfile

    envfile.load()
    try:
        out = run(a.db.expanduser(), a.replace, a.images)
    except ImportError_ as e:
        print(f"[import-mallot] {e}", file=sys.stderr)
        return 1
    for t, n in out["tables"].items():
        print(f"  {t:22s} {n:>7,}")
    print(f"[import-mallot] 끝 — 이미지 {out['images']}장 복사, 깨진 연결 {out['broken_foreign_keys']}건")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
