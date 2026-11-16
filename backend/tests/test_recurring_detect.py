"""반복 지출 자동 탐지 (#3): 탐지 규칙(고정 날짜) + 후보 API(오늘 기준 날짜)."""

import calendar
from datetime import date, timedelta

import pytest

from app.core import db
from app.ledger.merchants import merchant_key
from app.recurring.detect import describe, detect


@pytest.fixture
def conn():
    db.init_db()
    c = db.connect()
    yield c
    c.close()


def add(conn, on, amount, merchant, type="expense", transfer_kind=None, recurring_id=None, memo=""):
    conn.execute(
        "INSERT INTO transactions (occurred_on, type, transfer_kind, amount, merchant, merchant_key, memo, recurring_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (on if isinstance(on, str) else on.isoformat(), type, transfer_kind, amount, merchant, merchant_key(merchant),
         memo, recurring_id),
    )
    conn.commit()


def monthly(day, months, year=2026):
    """2026년 months 달마다 day일 (없는 날짜는 말일)."""
    return [date(year, m, min(day, calendar.monthrange(year, m)[1])) for m in months]


def found(conn, today=date(2026, 7, 10)):
    return {(s.merchant_key, s.cadence): s for s in detect(conn, today)}


# ---------- 탐지 규칙 ----------

def test_month_end_subscription_uses_last_day(conn):
    for d in monthly(31, range(1, 7)):  # 1/31, 2/28, 3/31, 4/30, 5/31, 6/30
        add(conn, d, 17000, "넷플릭스")
    s = found(conn)[("넷플릭스", "monthly")]
    assert (s.anchor, len(s.hits), s.missing, s.jitter) == (31, 6, 0, 0)
    d = describe(conn, s)
    assert d["next_on"] == "2026-07-31" and d["keyword"] == "넷플릭스"
    assert d["stats"]["suggestion"]["day_of_month"] == 31 and d["confidence"] >= 0.8


def test_weekend_shift_and_one_missing_month_still_count(conn):
    for d in ["2026-02-21", "2026-03-23", "2026-05-22", "2026-06-21"]:  # 4월 빠짐, 주말이라 하루이틀 밀림
        add(conn, d, 13900, "유튜브프리미엄")
    s = found(conn)[("유튜브프리미엄", "monthly")]
    assert (s.anchor, len(s.hits), s.missing) == (21, 4, 1)


def test_two_missing_months_break_the_run(conn):
    for d in ["2026-01-05", "2026-02-05", "2026-05-05", "2026-06-05"]:  # 3·4월 빠짐 → 마지막 구간은 2회
        add(conn, d, 9900, "왓챠")
    assert ("왓챠", "monthly") not in found(conn)


def test_weekly_needs_four_weeks(conn):
    saturdays = [date(2026, 6, 6) + timedelta(weeks=i) for i in range(4)]
    for d in saturdays[:3]:
        add(conn, d, 15000, "필라테스")
    assert ("필라테스", "weekly") not in found(conn, date(2026, 6, 25))
    add(conn, saturdays[3] + timedelta(days=1), 15000, "필라테스")  # 일요일로 하루 밀림
    s = found(conn, date(2026, 6, 30))[("필라테스", "weekly")]
    assert (s.anchor, len(s.hits)) == (5, 4)
    assert describe(conn, s)["stats"]["suggestion"]["day_of_month"] is None


def test_frequent_same_amount_topups_are_not_recurring(conn):
    d = date(2026, 1, 3)
    while d < date(2026, 7, 1):  # 4~6일마다 같은 금액 충전
        add(conn, d, 10000, "모바일충전")
        d += timedelta(days=4 + d.day % 3)
    assert not [k for k in found(conn) if k[0] == "모바일충전"]


def test_monthly_transfers_with_different_amounts_are_not_recurring(conn):
    for d, amount in zip(monthly(10, range(2, 7)), [11000, 11400, 11700, 11200, 11500]):  # 매달 다른 1/n 송금
        add(conn, d, amount, "카카오페이", type="transfer", transfer_kind="external")
    assert ("카카오페이", "monthly") not in found(conn)


def test_occasional_extra_charge_keeps_the_usual_amount(conn):
    for d, amount in zip(monthly(21, range(1, 7)), [30800, 30800, 32300, 30800, 30800, 30800]):
        add(conn, d, amount, "SKT 요금")
    s = found(conn)[("skt요금", "monthly")]
    d = describe(conn, s)
    assert d["amount"] == 30800 and (d["stats"]["amount_min"], d["stats"]["amount_max"]) == (30800, 32300)
    assert any("조금씩 달라요" in w for w in d["stats"]["warnings"])


def test_ended_subscription_is_not_suggested(conn):
    for d in monthly(15, range(1, 5)):  # 4월까지
        add(conn, d, 5500, "디즈니플러스")
    add(conn, "2026-07-08", 4000, "편의점")  # 데이터는 7월까지 있음
    assert ("디즈니플러스", "monthly") not in found(conn)


def test_reference_date_is_latest_transaction_not_today(conn):
    for d in monthly(15, range(1, 5)):
        add(conn, d, 5500, "디즈니플러스")
    # 오늘이 한참 뒤여도 가져오기가 4월에서 멈췄으면 끝난 구독으로 보지 않는다
    assert ("디즈니플러스", "monthly") in found(conn, date(2026, 12, 1))


def test_existing_item_keyword_covers_merchant(conn):
    item = conn.execute("SELECT id FROM recurring_items WHERE name = '구독료'").fetchone()["id"]
    conn.execute("UPDATE recurring_items SET match_keyword = '넷플릭스', amount = 13500 WHERE id = ?", (item,))
    for d in monthly(5, range(1, 7)):
        add(conn, d, 17000, "넷플릭스")  # 가격이 올라 자동 매칭은 안 되지만 이미 등록된 항목
    assert ("넷플릭스", "monthly") not in found(conn)


def test_mirror_leg_of_linked_internal_transfer_is_skipped(conn):
    item = conn.execute("SELECT id FROM recurring_items WHERE name = 'ISA 자동이체'").fetchone()["id"]
    for d in monthly(21, range(1, 7)):
        add(conn, d, 300000, "238.홍길동", type="transfer", transfer_kind="internal", recurring_id=item)
        add(conn, d, 300000, "입금 내역", type="transfer", transfer_kind="internal")  # 받는 계좌 쪽 기록
    assert ("입금내역", "monthly") not in found(conn)


def test_same_counterparty_different_amounts_are_separate_series(conn):
    for d in monthly(21, range(1, 7)):
        add(conn, d, 500000, "홍길동", type="transfer", transfer_kind="internal")
    for d in monthly(25, range(1, 7)):
        add(conn, d, 200000, "홍길동", type="transfer", transfer_kind="internal")
    series = sorted((s.anchor, s.amount) for s in detect(conn, date(2026, 7, 10)) if s.merchant_key == "홍길동")
    assert series == [(21, 500000), (25, 200000)]
    s = next(s for s in detect(conn, date(2026, 7, 10)) if s.amount == 500000)
    group = describe(conn, s)["stats"]["suggestion"]["group_id"]
    assert conn.execute("SELECT kind FROM recurring_groups WHERE id = ?", (group,)).fetchone()["kind"] == "saving"


def test_card_bill_and_borrowed_money_are_ignored(conn):
    conn.execute("INSERT INTO settings (key, value) VALUES ('loan_counterparties', '\"홍부모\"')")
    for d in monthly(14, range(1, 7)):
        add(conn, d, 13900, "현대카드", type="transfer", transfer_kind="internal", memo="카드대금 — 카드 사용분과 중복이라 ±0")
        add(conn, d, 1000000, "홍부모", type="transfer", transfer_kind="internal", memo="빌린 돈 (수입 아님)")
    assert not found(conn)


def test_payday_boundary_warning(conn):
    conn.execute("UPDATE settings SET value = '21' WHERE key = 'payday'")
    # 출금일(21일) 전날 미리 나간 달은 다음 기간 몫이라 기간이 겹치지 않는다 → 경고 없음
    for d in ["2026-01-20", "2026-02-22", "2026-03-20", "2026-04-22", "2026-05-21"]:
        add(conn, d, 7000, "클라우드")
    s = found(conn)[("클라우드", "monthly")]
    assert not any("수입일(21일)" in w for w in describe(conn, s)["stats"]["warnings"])
    # 출금일(19일)보다 늦게 나가 수입일을 넘긴 달은 다음 기간에 두 번 잡힌다 → 경고
    for d in ["2026-01-19", "2026-02-22", "2026-03-19", "2026-04-22", "2026-05-19"]:
        add(conn, d, 9900, "넷플릭스")
    s = found(conn)[("넷플릭스", "monthly")]
    assert s.anchor == 19
    assert any("수입일(21일)" in w for w in describe(conn, s)["stats"]["warnings"])


# ---------- 후보 API ----------

def recent_monthly(day, n):
    """오늘 이전 가장 최근 n번의 '매월 day일' (오래된 순)."""
    today, out = date.today(), []
    y, m = today.year, today.month
    while len(out) < n:
        d = date(y, m, min(day, calendar.monthrange(y, m)[1]))
        if d <= today:
            out.append(d)
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    return [d.isoformat() for d in reversed(out)]


def post_tx(client, on, amount, merchant, **fields):
    res = client.post("/api/transactions", json={"occurred_on": on, "type": "expense", "amount": amount,
                                                 "merchant": merchant, **fields})
    assert res.status_code == 201, res.text
    return res.json()


def pending(client):
    return {c["merchant"]: c for c in client.get("/api/recurring-candidates").json()["pending"]}


@pytest.fixture
def subscribed(client):
    """오늘의 일(day)에 맞춰 6개월째 나가는 구독 — 이번 기간에도 이미 한 번 나갔다."""
    client.put("/api/settings", json={"payday": 25})
    day = date.today().day
    for on in recent_monthly(day, 6):
        post_tx(client, on, 4400, "Apple")
    return client


def test_candidate_lists_evidence_and_suggestion(subscribed):
    c = pending(subscribed)["Apple"]
    assert (c["cadence"], c["amount"], c["occurrences"], c["status"]) == ("monthly", 4400, 6, "pending")
    assert c["anchor"] == date.today().day and len(c["dates"]) == 6 and len(c["tx_ids"]) == 6
    s = c["suggestion"]
    assert (s["name"], s["amount"], s["match_keyword"]) == ("Apple", 4400, "apple")
    group = next(g for g in subscribed.get("/api/recurring-groups").json() if g["id"] == s["group_id"])
    assert group["name"] == "구독"
    # 다시 조회해도 같은 후보 하나 (중복 생성 없음)
    again = subscribed.get("/api/recurring-candidates").json()["pending"]
    assert [x["id"] for x in again] == [c["id"]]


def test_reject_is_remembered_and_can_be_restored(subscribed):
    c = pending(subscribed)["Apple"]
    assert subscribed.post(f"/api/recurring-candidates/{c['id']}/reject").json()["status"] == "rejected"
    post_tx(subscribed, date.today().isoformat(), 4400, "Apple")  # 같은 반복이 또 나와도
    body = subscribed.get("/api/recurring-candidates").json()
    assert "Apple" not in {x["merchant"] for x in body["pending"]}
    assert [x["id"] for x in body["rejected"]] == [c["id"]]
    assert subscribed.post(f"/api/recurring-candidates/{c['id']}/reject").status_code == 409
    assert subscribed.post(f"/api/recurring-candidates/{c['id']}/restore").json()["status"] == "pending"
    assert "Apple" in pending(subscribed)


def test_accept_creates_item_links_payments_and_auto_matches_next(subscribed):
    c = pending(subscribed)["Apple"]
    res = subscribed.post(f"/api/recurring-candidates/{c['id']}/accept", json={"item": c["suggestion"]})
    assert res.status_code == 200, res.text
    body = res.json()
    item = body["item"]
    assert (item["name"], item["amount"], item["match_keyword"]) == ("Apple", 4400, "apple")
    assert body["linked"] == 6 and body["candidate"]["status"] == "accepted"
    assert body["candidate"]["recurring_id"] == item["id"]

    status = {i["id"]: i for i in subscribed.get("/api/recurring-status").json()["items"]}
    assert status[item["id"]]["status"] == "paid"  # 이번 기간 결제가 바로 연결됨
    first = subscribed.get("/api/recurring-status", params={"on": c["dates"][0]}).json()["items"]
    assert next(i for i in first if i["id"] == item["id"])["status"] == "paid"  # 지난 기간도

    # 다음 결제는 기존 자동 매칭으로 연결되고, 수락한 후보는 다시 나오지 않는다
    nxt = (date.fromisoformat(c["next_on"])).isoformat()
    assert post_tx(subscribed, nxt, 4400, "Apple")["recurring_id"] == item["id"]
    assert "Apple" not in pending(subscribed)
    assert subscribed.post(f"/api/recurring-candidates/{c['id']}/accept", json={"item": c["suggestion"]}).status_code == 409


def test_accept_without_past_links_only_this_period(subscribed):
    c = pending(subscribed)["Apple"]
    body = subscribed.post(f"/api/recurring-candidates/{c['id']}/accept",
                           json={"item": c["suggestion"], "link_past": False}).json()
    assert body["linked"] == 1
    first = subscribed.get("/api/recurring-status", params={"on": c["dates"][0]}).json()["items"]
    assert next(i for i in first if i["id"] == body["item"]["id"])["status"] == "missed"


def test_merge_into_similar_item_without_keyword(subscribed):
    items = {i["name"]: i for i in subscribed.get("/api/recurring-items").json()}
    icloud = items["구독료"]
    subscribed.put(f"/api/recurring-items/{icloud['id']}",
                   json={**{k: icloud[k] for k in ("name", "group_id", "icon", "day_of_month", "memo", "active",
                                                   "sort_order")}, "amount": 4400, "match_keyword": ""})
    c = pending(subscribed)["Apple"]
    assert c["similar_item"]["id"] == icloud["id"]
    merged = {**c["similar_item"], "match_keyword": c["keyword"], "amount": c["amount"]}
    merged = {k: merged[k] for k in ("name", "group_id", "icon", "amount", "day_of_month", "match_keyword", "memo",
                                     "active", "sort_order")}
    body = subscribed.post(f"/api/recurring-candidates/{c['id']}/accept",
                           json={"item": merged, "item_id": icloud["id"]}).json()
    assert body["item"]["id"] == icloud["id"] and body["item"]["match_keyword"] == "apple"
    assert len(subscribed.get("/api/recurring-items").json()) == len(items)  # 새 항목을 만들지 않음


def test_accept_validates_group_and_item(subscribed):
    c = pending(subscribed)["Apple"]
    bad_group = {**c["suggestion"], "group_id": 9999}
    assert subscribed.post(f"/api/recurring-candidates/{c['id']}/accept", json={"item": bad_group}).status_code == 400
    assert subscribed.post(f"/api/recurring-candidates/{c['id']}/accept",
                           json={"item": c["suggestion"], "item_id": 9999}).status_code == 404
    assert subscribed.post("/api/recurring-candidates/9999/reject").status_code == 404
    assert pending(subscribed)["Apple"]["status"] == "pending"  # 실패한 수락은 아무것도 바꾸지 않음
