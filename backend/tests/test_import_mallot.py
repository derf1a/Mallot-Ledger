"""Mallot DB → 이 앱 DB 옮기기. Mallot 스키마(마지막 모양)를 흉내 낸 DB 를 만들어 옮긴다."""

import sqlite3

import pytest

from app.core.db import connect, init_db
from app.core.migrations import MIGRATIONS
from app.ledger import import_mallot


def _mallot_db(path):
    """이 앱 v1 의 가계부 테이블 = Mallot 마지막 모양. 거기에 Mallot 에만 있는 투자 테이블 · 설정을 더한다."""
    c = sqlite3.connect(path)
    c.create_function("merchant_key", 1, lambda s: s)
    c.executescript(MIGRATIONS[0])
    c.execute("ALTER TABLE extraction_logs DROP COLUMN ocr_text")  # Mallot 에는 없는 칸
    c.execute("CREATE TABLE invest_orders (id INTEGER PRIMARY KEY, symbol TEXT)")
    c.execute("INSERT INTO invest_orders (symbol) VALUES ('005930')")
    c.execute("UPDATE settings SET value = '3500000' WHERE key = 'monthly_income'")
    c.execute("INSERT INTO settings (key, value) VALUES ('invest_autopilot', '{}'), ('tax_profile', '{\"gross_salary\": 50000000}')")
    item = c.execute("SELECT id FROM recurring_items WHERE name = '보험료'").fetchone()[0]
    food = c.execute("SELECT id FROM categories WHERE name = '식비'").fetchone()[0]
    c.execute("INSERT INTO transactions (occurred_on, type, amount, merchant, category_id) VALUES ('2026-10-01', 'expense', 9000, '김밥천국', ?)", (food,))
    c.execute("INSERT INTO transactions (occurred_on, type, transfer_kind, amount, merchant, recurring_id) "
              "VALUES ('2026-10-02', 'transfer', 'external', 80000, '보험', ?)", (item,))
    c.commit()
    c.close()


def test_imports_ledger_tables_and_settings_but_not_invest(tmp_path):
    src = tmp_path / "wt.db"
    _mallot_db(src)
    out = import_mallot.run(src)
    assert out["tables"]["transactions"] == 2 and out["broken_foreign_keys"] == 0
    with connect() as conn:
        rows = conn.execute("SELECT t.merchant, c.name, r.name FROM transactions t LEFT JOIN categories c ON c.id = t.category_id "
                            "LEFT JOIN recurring_items r ON r.id = t.recurring_id ORDER BY t.id").fetchall()
        assert [tuple(r) for r in rows] == [("김밥천국", "식비", None), ("보험", None, "보험료")]
        keys = {r[0]: r[1] for r in conn.execute("SELECT key, value FROM settings")}
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert keys["monthly_income"] == "3500000" and "tax_profile" in keys and "invest_autopilot" not in keys
    assert "invest_orders" not in tables


def test_refuses_when_ledger_has_data_unless_replace(tmp_path):
    src = tmp_path / "wt.db"
    _mallot_db(src)
    init_db()
    with connect() as conn:
        conn.execute("INSERT INTO transactions (occurred_on, type, amount) VALUES ('2026-01-01', 'expense', 1)")
        conn.commit()
    with pytest.raises(import_mallot.ImportError_, match="이미 있어요"):
        import_mallot.run(src)
    assert import_mallot.run(src, replace=True)["tables"]["transactions"] == 2
    with pytest.raises(import_mallot.ImportError_, match="없어요"):
        import_mallot.run(tmp_path / "nope.db")
