"""거래 읽기·저장 — 가계부 API 와 캡쳐 판독 확인이 같이 쓴다. 저장은 늘 normalize(가계부 규칙) → 가맹점 규칙 학습을 거친다."""

import sqlite3

from app.ledger.merchants import learn
from app.ledger.rules import normalize
from app.ledger.schemas import TransactionIn

COLUMNS = ("occurred_on", "occurred_time", "type", "transfer_kind", "amount", "merchant", "merchant_key", "category_id",
           "category_source", "recurring_id", "payment_method", "memo", "needs_review", "source")
SELECT = """
SELECT t.*, c.name AS category_name, c.icon AS category_icon,
       r.name AS recurring_name, g.kind AS recurring_kind,
       COALESCE(NULLIF(r.icon, ''), g.icon) AS recurring_icon
FROM transactions t
LEFT JOIN categories c ON c.id = t.category_id
LEFT JOIN recurring_items r ON r.id = t.recurring_id
LEFT JOIN recurring_groups g ON g.id = r.group_id
"""


def get_transaction(conn: sqlite3.Connection, tx_id: int) -> dict | None:
    row = conn.execute(f"{SELECT} WHERE t.id = ?", (tx_id,)).fetchone()
    return {**dict(row), "needs_review": bool(row["needs_review"])} if row else None


def insert_transaction(conn: sqlite3.Connection, body: TransactionIn) -> int:
    data = normalize(conn, body)
    cur = conn.execute(
        f"INSERT INTO transactions ({', '.join(COLUMNS)}) VALUES ({', '.join('?' * len(COLUMNS))})",
        [data[c] for c in COLUMNS],
    )
    learn(conn, data)
    return cur.lastrowid
