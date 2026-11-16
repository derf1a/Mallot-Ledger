"""가계부 도메인 규칙.

- 내 계좌 간 이체(internal): 합계에 반영하지 않는다 (±0).
- 타 계좌 이체(external): '기타'로 분류하고 '분류 필요'로 표시한다. 정기지출에 매칭되면 표시하지 않는다.
- 정산·환불 입금(refund): 1/n 정산으로 돌려받은 돈·부분 환불. 수입이 아니라 변동비에서 빠지는 돈 (카테고리를 고르면 그 예산에서 차감).
- 정기지출 자동 매칭은 app.recurring.matching (저장 직전 normalize 가 부른다).
"""

import sqlite3

from app.ledger.merchants import apply_rule, merchant_key
from app.ledger.schemas import TransactionIn
from app.ledger.settings import is_own_account, loan_counterparty
from app.recurring.matching import find_recurring_match

# 변동비 거래: 정기지출에 매칭되지 않은 지출·정산·환불 + 타 계좌 이체 (요약·홈 추세가 같이 쓴다)
VARIABLE_WHERE = ("recurring_id IS NULL "
                  "AND (type IN ('expense', 'refund') OR (type = 'transfer' AND transfer_kind = 'external'))")


def other_category_id(conn: sqlite3.Connection) -> int | None:
    row = conn.execute("SELECT id FROM categories WHERE is_system = 1 ORDER BY id LIMIT 1").fetchone()
    return row["id"] if row else None


def normalize(conn: sqlite3.Connection, tx: TransactionIn, tx_id: int | None = None) -> dict:
    """저장 직전 규칙 적용. DB에 넣을 컬럼 dict를 돌려준다."""
    data = tx.model_dump(exclude={"reviewed"})
    data["merchant_key"] = merchant_key(tx.merchant)
    if tx.type != "transfer":
        data["transfer_kind"] = None
    elif is_own_account(conn, tx.merchant):
        data["transfer_kind"] = "internal"  # 등록된 내 계좌 규칙이 항상 우선
    elif tx.transfer_kind is None:
        data["transfer_kind"] = "external"

    if data["type"] == "refund":  # 정산·환불: 정기지출·분류 필요와 무관, 카테고리는 고른 것만
        if data["category_id"] is None:
            data["category_source"] = None
        data.update(recurring_id=None, needs_review=0)
        return data

    if data["transfer_kind"] == "internal":
        # 빌린 돈 상대에게서 받은 입금(±0)은 상환이 아니다 → 매칭하지 않는다 (갚는 출금은 타 계좌 이체라 영향 없음)
        recurring = data["recurring_id"]
        if recurring is None and not loan_counterparty(conn, tx.merchant):
            recurring = find_recurring_match(conn, TransactionIn(**{**data, "reviewed": tx.reviewed}), tx_id)
        data.update(category_id=None, category_source=None, recurring_id=recurring, needs_review=0)
        return data

    if data["recurring_id"] is None:
        data["recurring_id"] = find_recurring_match(conn, TransactionIn(**{**data, "reviewed": tx.reviewed}), tx_id)

    # 카테고리가 비어 있으면 가맹점 규칙으로 채운다. 사용자 규칙이면 이미 사람이 분류한 것과 같다.
    by_user_rule = apply_rule(conn, data)
    if data["category_id"] is None:
        data["category_source"] = None

    needs_review = 0
    if data["transfer_kind"] == "external" and data["recurring_id"] is None:
        if data["category_id"] is None:
            data["category_id"] = other_category_id(conn)  # 임시 분류라 출처는 비워 둔다
        needs_review = 0 if tx.reviewed or by_user_rule else 1
    data["needs_review"] = needs_review
    return data


def find_duplicate(conn: sqlite3.Connection, occurred_on: str, amount: int, merchant: str) -> int | None:
    row = conn.execute(
        "SELECT id FROM transactions WHERE occurred_on = ? AND amount = ? AND merchant = ? LIMIT 1",
        (occurred_on, amount, merchant),
    ).fetchone()
    return row["id"] if row else None
