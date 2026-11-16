from app.core.db import connect, init_db
from app.core.migrations import MIGRATIONS


def test_migrations_reach_latest_and_are_idempotent():
    init_db()
    init_db()  # 두 번 돌려도 이미 실행된 단계는 다시 돌지 않는다
    with connect() as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == len(MIGRATIONS)
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"settings", "runs", "run_logs", "run_metrics", "llm_usage", "transactions", "categories", "recurring_items",
            "salary_slips"} <= tables
    assert not any(t.startswith(("lab_", "invest_")) for t in tables)


def test_default_categories_and_recurring_groups_exist():
    init_db()
    with connect() as conn:
        assert [r[0] for r in conn.execute("SELECT name FROM categories ORDER BY sort_order")] == ["식비", "커피", "생활비", "여가·유흥", "기타"]
        assert conn.execute("SELECT COUNT(*) FROM recurring_groups").fetchone()[0] == 7
        assert conn.execute("SELECT value FROM settings WHERE key = 'payday'").fetchone()[0] == "25"
