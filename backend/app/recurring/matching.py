"""정기지출 매칭·기간 배정·상태.

- 자동 매칭: 키워드가 가맹점/메모에 포함되고 금액이 같으면 해당 기간의 정기지출로 연결한다 (기간당 한 건).
  지출·타 계좌 이체·내 계좌 간 이체(내 명의 적금·ISA 계좌로 보내는 경우) 모두 대상. 연결된 거래는 변동비 집계에서 빠진다.
- 미리 나간 정기지출: 은행 영업일·연휴로 출금일보다 며칠(EARLY_DAYS) 앞서 나가 수입일 전날(지난 기간)에 찍힌 결제는
  다음 기간 몫으로 본다 (assign_periods). 매칭·상태·반복 지출 연결이 모두 같은 배정을 쓴다.
"""

import sqlite3
from collections import Counter
from datetime import date, timedelta

from app.core.periods import Period, period_for
from app.ledger.schemas import TransactionIn
from app.ledger.settings import get_settings, loan_counterparty, split_keywords

RECURRING_SELECT = """
SELECT r.*, g.name AS group_name, g.kind AS group_kind, g.icon AS group_icon,
       COALESCE(NULLIF(r.icon, ''), g.icon) AS display_icon
FROM recurring_items r JOIN recurring_groups g ON g.id = r.group_id
"""
RECURRING_COLS = ("name", "group_id", "icon", "amount", "day_of_month", "match_keyword", "memo", "active",
                  "sort_order")


EARLY_DAYS = 7  # 출금일보다 이만큼 안쪽으로 앞서 나간 결제까지 '미리 낸 것'으로 본다 (주말 + 명절 연휴)


def assign_periods(payments: list[tuple[int, date]], day: int | None, payday: int) -> dict[int, Period]:
    """정기지출 한 항목의 결제(거래 id, 날짜)를 기간에 배정한다.

    기본은 결제 날짜가 속한 기간. 다음 기간의 출금일보다 EARLY_DAYS 일 안쪽으로 앞서 나간 결제(예: 수입일 21일·출금일 21일인데
    21일이 주말이라 20일에 나감)는 다음 기간 몫이다 — 단 다음 기간에 이미 결제가 있으면 원래 기간에 둔다(지난 기간 몫을 늦게 낸 것).
    최근 결제부터 정해서 제때 낸 결제가 자기 기간을 먼저 차지한다. 출금일이 미정이면 날짜가 속한 기간 그대로.
    """
    out: dict[int, Period] = {}
    taken: set[date] = set()
    for tx_id, on in sorted(payments, key=lambda p: (p[1], p[0]), reverse=True):
        target = period_for(on, payday)
        if day:
            nxt = period_for(target.end + timedelta(days=1), payday)
            if (nxt.date_for_day(day) - on).days <= EARLY_DAYS and nxt.start not in taken:
                target = nxt
        taken.add(target.start)
        out[tx_id] = target
    return out


def _duplicates(assigned: dict[int, Period]) -> int:
    return sum(n - 1 for n in Counter(p.start for p in assigned.values()).values())


def _payments(conn: sqlite3.Connection, item_id: int, exclude_tx_id: int | None = None) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT id, occurred_on, amount, merchant FROM transactions WHERE recurring_id = ? AND id IS NOT ? "
        "ORDER BY occurred_on, id",
        (item_id, exclude_tx_id),
    ).fetchall()


def link_period(conn: sqlite3.Connection, item_id: int, day: int | None, on: date,
                exclude_tx_id: int | None = None) -> Period | None:
    """이 날짜의 결제를 항목에 연결하면 몫이 될 기간. 그 기간(또는 밀려난 다른 결제의 기간)에 이미 결제가 있어 겹치면 None."""
    payday = int(get_settings(conn)["payday"])
    payments = [(r["id"], date.fromisoformat(r["occurred_on"])) for r in _payments(conn, item_id, exclude_tx_id)]
    before = _duplicates(assign_periods(payments, day, payday))
    after = assign_periods([*payments, (0, on)], day, payday)  # 0 = 아직 저장 전인 이 결제
    return after[0] if _duplicates(after) == before else None


def find_recurring_match(conn: sqlite3.Connection, tx: TransactionIn, exclude_tx_id: int | None = None) -> int | None:
    # 내 계좌 간 이체도 매칭한다: 적금·ISA·관리비 계좌처럼 '내 명의 계좌'로 보내는 정기지출이 많기 때문 (집계는 ±0 그대로)
    if tx.type in ("income", "refund"):
        return None
    on = date.fromisoformat(tx.occurred_on)
    text = f"{tx.merchant} {tx.memo}".lower()
    items = conn.execute(
        "SELECT id, amount, match_keyword, day_of_month FROM recurring_items WHERE active = 1 AND amount > 0 "
        "ORDER BY sort_order, id"
    ).fetchall()
    for item in items:
        keywords = split_keywords(item["match_keyword"])
        if not keywords or item["amount"] != tx.amount or not any(k in text for k in keywords):
            continue
        # 기간당 한 건 — 출금일 직전에 미리 나간 결제는 다음 기간 몫이라 지난 기간의 결제와 겹치지 않는다
        if link_period(conn, item["id"], item["day_of_month"], on, exclude_tx_id):
            return item["id"]
    return None


def relink_recurring(conn: sqlite3.Connection) -> int:
    """연결 안 된 지출·이체에 지금의 매칭 규칙을 다시 적용한다 (서버 시작 시).

    저장할 때 연결이 비어 있으면 늘 다시 매칭하므로 결과는 같고, 규칙이 바뀌었을 때 지난 거래에도 반영된다
    — 예: 예전 규칙에선 '같은 기간에 이미 있음'으로 거부돼 변동비로 남은 '수입일 전날 미리 나간 정기지출'.
    """
    rows = conn.execute(
        "SELECT id, occurred_on, type, transfer_kind, amount, merchant, memo FROM transactions "
        "WHERE recurring_id IS NULL AND type IN ('expense', 'transfer') ORDER BY occurred_on, id"
    ).fetchall()
    linked = 0
    for r in rows:
        if r["transfer_kind"] == "internal" and loan_counterparty(conn, r["merchant"] or ""):
            continue  # 빌린 돈 입금은 상환이 아니다 (normalize 와 같음)
        tx = TransactionIn(occurred_on=r["occurred_on"], type=r["type"], transfer_kind=r["transfer_kind"],
                           amount=r["amount"], merchant=r["merchant"] or "", memo=r["memo"] or "")
        item = find_recurring_match(conn, tx, r["id"])
        if item:
            conn.execute("UPDATE transactions SET recurring_id = ?, needs_review = 0 WHERE id = ?", (item, r["id"]))
            linked += 1
    conn.commit()
    return linked


def recurring_status(conn: sqlite3.Connection, period: Period, today: date | None = None) -> list[dict]:
    today = today or date.today()
    items = conn.execute(
        f"{RECURRING_SELECT} WHERE r.active = 1 ORDER BY g.sort_order, r.sort_order, r.id"
    ).fetchall()
    skipped = {r[0] for r in conn.execute("SELECT item_id FROM recurring_skips WHERE period_start = ?",
                                           (period.start.isoformat(),))}
    payday = int(get_settings(conn)["payday"])
    result = []
    for item in items:
        # 출금일이 비어 있으면 '미정' — 기간 안 언제든 나갈 수 있으니 기간이 끝나기 전에는 미확인으로 보지 않는다
        day = item["day_of_month"]
        due = period.date_for_day(day) if day else None
        # 이 기간 몫의 결제: 기간 안 결제 + 수입일 전에 미리 나간 결제 (assign_periods)
        payments = _payments(conn, item["id"])
        assigned = assign_periods([(r["id"], date.fromisoformat(r["occurred_on"])) for r in payments], day, payday)
        paid = next((r for r in payments if assigned[r["id"]] == period), None)
        if item["amount"] == 0:
            status = "unset"
        elif paid:
            status = "paid"  # 건너뛰기로 했어도 실제로 나갔으면 확인됨
        elif item["id"] in skipped:
            status = "skipped"  # 이번 기간만 건너뜀 — 미확인으로 세지 않고 이번 기간 정기지출 합계에서도 뺀다
        elif due is None:
            status = "missed" if period.end < today else "floating"
        elif due < today:
            status = "missed"
        else:
            status = "upcoming"
        result.append(
            {
                **dict(item),
                "active": bool(item["active"]),
                "due_date": due.isoformat() if due else None,
                "status": status,
                "transaction": dict(paid) if paid else None,
                # 수입일 전(지난 기간 날짜)에 미리 나간 결제로 확인됨
                "early": bool(paid and paid["occurred_on"] < period.start.isoformat()),
            }
        )
    return result
