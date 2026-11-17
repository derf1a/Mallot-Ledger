from datetime import date, timedelta

import pytest

from app.capture.extractor import get_extractor


def cat_id(client, name):
    return next(c["id"] for c in client.get("/api/categories").json() if c["name"] == name)


def recurring(client, name):
    return next(r for r in client.get("/api/recurring-items").json() if r["name"] == name)


def set_recurring(client, name, **changes):
    item = recurring(client, name)
    body = {k: item[k] for k in ("name", "group_id", "icon", "amount", "day_of_month", "match_keyword", "memo",
                                 "active", "sort_order")}
    return client.put(f"/api/recurring-items/{item['id']}", json={**body, **changes}).json()


def add_tx(client, **fields):
    body = {"occurred_on": "2026-10-01", "type": "expense", "amount": 10000, **fields}
    res = client.post("/api/transactions", json=body)
    assert res.status_code == 201, res.text
    return res.json()


@pytest.fixture
def setup(client):
    client.put("/api/settings", json={"monthly_income": 3_000_000, "payday": 25})
    return client


def test_settings_roundtrip(client):
    assert client.get("/api/settings").json()["payday"] == 25
    res = client.put("/api/settings", json={"owner_name": "민석", "payday": 10})
    assert res.json() == {"owner_name": "민석", "monthly_income": 0, "payday": 10, "loan_counterparties": "",
                          "search_months": 12}
    assert client.put("/api/settings", json={"payday": 32}).status_code == 422


def test_internal_transfer_is_zero_effect(setup):
    client = setup
    client.post("/api/accounts", json={"name": "토스 비상금", "keyword": "토스뱅크"})
    tx = add_tx(client, type="transfer", merchant="토스뱅크 홍길동", amount=500000)
    assert tx["transfer_kind"] == "internal"
    assert tx["category_id"] is None and tx["needs_review"] is False
    # 클라이언트가 external 로 보내도 내 계좌 규칙이 우선한다
    assert add_tx(client, type="transfer", transfer_kind="external", merchant="토스뱅크")["transfer_kind"] == "internal"
    s = client.get("/api/summary", params={"on": "2026-10-01"}).json()
    assert s["variable"]["spent_total"] == 0


def test_external_transfer_goes_to_other_and_needs_review(setup):
    client = setup
    tx = add_tx(client, type="transfer", merchant="김철수", amount=30000)
    assert tx["transfer_kind"] == "external"
    assert tx["category_name"] == "기타" and tx["needs_review"] is True
    assert client.get("/api/summary", params={"on": "2026-10-01"}).json()["needs_review"] == 1

    body = {**{k: tx[k] for k in ("occurred_on", "type", "transfer_kind", "amount", "merchant")},
            "category_id": cat_id(client, "여가·유흥"), "reviewed": True}
    fixed = client.put(f"/api/transactions/{tx['id']}", json=body).json()
    assert fixed["needs_review"] is False and fixed["category_name"] == "여가·유흥"


def test_recurring_auto_match_excludes_from_variable(setup):
    client = setup
    set_recurring(client, "ISA 자동이체", amount=500000, day_of_month=26)
    tx = add_tx(client, type="transfer", transfer_kind="external", merchant="미래에셋 ISA", amount=500000,
                occurred_on="2026-09-26")
    assert tx["recurring_name"] == "ISA 자동이체" and tx["needs_review"] is False

    # 같은 기간에 두 번째 거래는 매칭되지 않는다
    tx2 = add_tx(client, type="transfer", transfer_kind="external", merchant="미래에셋 ISA", amount=500000,
                 occurred_on="2026-10-02")
    assert tx2["recurring_id"] is None

    s = client.get("/api/summary", params={"on": "2026-10-01"}).json()
    assert s["recurring"]["total"] == 500000
    assert s["variable"]["pool"] == 2_500_000
    assert s["variable"]["spent_total"] == 500000  # tx2 만 변동비
    isa = next(i for i in s["recurring"]["items"] if i["name"] == "ISA 자동이체")
    assert isa["status"] == "paid" and isa["transaction"]["id"] == tx["id"]


def test_amount_mismatch_does_not_match(setup):
    client = setup
    set_recurring(client, "보험료", amount=80000, day_of_month=5)
    assert add_tx(client, merchant="삼성화재 보험", amount=79000)["recurring_id"] is None


def test_recurring_status_missed_upcoming_unset(setup):
    client = setup
    today = date.today()
    period = client.get("/api/summary").json()["period"]
    start = date.fromisoformat(period["start"])
    end = date.fromisoformat(period["end"])
    set_recurring(client, "보험료", amount=80000, day_of_month=start.day)
    set_recurring(client, "구독료", amount=17000, day_of_month=end.day, match_keyword="넷플릭스")
    items = {i["name"]: i for i in client.get("/api/recurring-status").json()["items"]}
    assert items["보험료"]["status"] == ("missed" if start < today else "upcoming")
    assert items["구독료"]["status"] == ("upcoming" if end >= today else "missed")
    assert items["예·적금"]["status"] == "unset"

    add_tx(client, merchant="넷플릭스", amount=17000, occurred_on=today.isoformat())
    items = {i["name"]: i for i in client.get("/api/recurring-status").json()["items"]}
    assert items["구독료"]["status"] == "paid"


def test_category_budget_remaining(setup):
    client = setup
    food = cat_id(client, "식비")
    client.put(f"/api/categories/{food}", json={"name": "식비", "budget": 400000})
    add_tx(client, category_id=food, amount=12000, merchant="스타벅스")
    add_tx(client, type="income", amount=3_000_000, merchant="급여")
    s = client.get("/api/summary", params={"on": "2026-10-01"}).json()
    food_row = next(c for c in s["variable"]["categories"] if c["name"] == "식비")
    assert (food_row["spent"], food_row["remaining"]) == (12000, 388000)
    assert s["income"]["actual"] == 3_000_000
    assert s["variable"]["unallocated"] == 3_000_000 - 400000


def test_transactions_filtered_by_payday_period(setup):
    client = setup
    add_tx(client, occurred_on="2026-09-24", merchant="이전 기간")
    add_tx(client, occurred_on="2026-09-25", merchant="이번 기간 첫날")
    add_tx(client, occurred_on="2026-10-24", merchant="이번 기간 마지막날")
    res = client.get("/api/transactions", params={"on": "2026-10-01"}).json()
    assert res["period"] == {"start": "2026-09-25", "end": "2026-10-24"}
    assert {t["merchant"] for t in res["transactions"]} == {"이번 기간 첫날", "이번 기간 마지막날"}


def test_system_category_cannot_be_deleted(client):
    assert client.delete(f"/api/categories/{cat_id(client, '기타')}").status_code == 400
    assert client.delete(f"/api/categories/{cat_id(client, '식비')}").status_code == 204


def test_deleting_category_keeps_transactions(setup):
    client = setup
    food = cat_id(client, "식비")
    tx = add_tx(client, category_id=food)
    client.delete(f"/api/categories/{food}")
    assert client.get("/api/transactions", params={"on": "2026-10-01"}).json()["transactions"][0]["id"] == tx["id"]


class FakeExtractor:
    def __init__(self, items):
        self.items = items
        self.ctx = None

    async def extract(self, image, media_type, ctx):
        self.ctx = ctx
        return self.items


def test_extract_returns_drafts_with_duplicates(setup):
    client = setup
    client.post("/api/accounts", json={"name": "토스 비상금", "keyword": "토스뱅크"})
    existing = add_tx(client, occurred_on="2026-10-01", amount=4500, merchant="스타벅스")
    fake = FakeExtractor([
        {"occurred_on": "2026-10-01", "type": "expense", "transfer_kind": None, "amount": 4500,
         "merchant": "스타벅스", "category": "식비", "payment_method": "신한카드", "memo": ""},
        {"occurred_on": "2026-10-02", "type": "expense", "transfer_kind": "internal", "amount": -9900,
         "merchant": "쿠팡", "category": "없는카테고리", "payment_method": "", "memo": ""},
        {"occurred_on": "2026-10-02", "type": "transfer", "transfer_kind": "external", "amount": 100000,
         "merchant": "토스뱅크 홍길동", "category": None, "payment_method": "", "memo": ""},
        {"occurred_on": "10월 3일", "type": "expense", "amount": 1},  # 깨진 항목은 버린다
    ])
    client.app.dependency_overrides[get_extractor] = lambda: fake
    try:
        res = client.post("/api/transactions/extract", files={"image": ("a.png", b"\x89PNG", "image/png")})
    finally:
        client.app.dependency_overrides.clear()
    assert res.status_code == 200, res.text
    drafts = res.json()["drafts"]
    assert len(drafts) == 3
    assert drafts[2]["transfer_kind"] == "internal"
    assert "토스 비상금 (토스뱅크)" in fake.ctx.own_accounts
    assert drafts[0]["duplicate_of"] == existing["id"] and drafts[0]["category_id"] == cat_id(client, "식비")
    assert drafts[1]["amount"] == 9900 and drafts[1]["category_id"] is None
    assert drafts[1]["transfer_kind"] is None  # expense 에는 이체 구분이 없다
    assert [c["name"] for c in fake.ctx.categories][:2] == ["식비", "커피"]


def test_extract_rejects_non_image(client):
    res = client.post("/api/transactions/extract", files={"image": ("a.txt", b"hi", "text/plain")})
    assert res.status_code == 415


def test_bulk_create(setup):
    client = setup
    res = client.post("/api/transactions/bulk", json=[
        {"occurred_on": "2026-10-01", "type": "expense", "amount": 1000, "source": "image"},
        {"occurred_on": "2026-10-02", "type": "income", "amount": 2000, "source": "image"},
    ])
    assert res.status_code == 201 and len(res.json()) == 2


def test_system_info_and_backup(client):
    info = client.get("/api/system").json()
    assert info["db"]["schema_version"] >= 1
    res = client.get("/api/system/backup")
    assert res.status_code == 200 and res.content[:15] == b"SQLite format 3"


def group(client, name):
    return next(g for g in client.get("/api/recurring-groups").json() if g["name"] == name)


def test_recurring_groups_crud_and_kind_totals(setup):
    client = setup
    set_recurring(client, "예·적금", amount=500000)
    set_recurring(client, "통신비", amount=55000)
    s = client.get("/api/summary").json()["recurring"]
    assert (s["saving_total"], s["expense_total"]) == (500000, 55000)
    saving = next(g for g in s["groups"] if g["group_name"] == "저금")
    assert saving["kind"] == "saving" and saving["icon"] == "💰"

    created = client.post("/api/recurring-groups", json={"name": "운동", "kind": "expense", "icon": "🏋️"}).json()
    assert client.post("/api/recurring-groups", json={"name": "운동"}).status_code == 409
    item = client.post("/api/recurring-items", json={"name": "헬스장", "group_id": created["id"], "amount": 50000})
    assert item.status_code == 201
    assert item.json()["display_icon"] == "🏋️"  # 항목 아이콘이 없으면 그룹 아이콘

    # 쓰는 항목이 있으면 삭제할 수 없다
    assert client.delete(f"/api/recurring-groups/{created['id']}").status_code == 409
    client.delete(f"/api/recurring-items/{item.json()['id']}")
    assert client.delete(f"/api/recurring-groups/{created['id']}").status_code == 204


def test_recurring_item_rejects_unknown_group(client):
    res = client.post("/api/recurring-items", json={"name": "x", "group_id": 9999})
    assert res.status_code == 400


def test_transaction_exposes_recurring_kind_and_icons(setup):
    client = setup
    set_recurring(client, "ISA 자동이체", amount=300000)
    tx = add_tx(client, type="transfer", transfer_kind="external", merchant="ISA", amount=300000)
    assert (tx["recurring_kind"], tx["recurring_icon"]) == ("saving", "📈")
    food = add_tx(client, category_id=cat_id(client, "식비"))
    assert food["category_icon"] == "🍚"


def test_reorder_recurring_within_and_across_groups(client):
    items = {i["name"]: i for i in client.get("/api/recurring-items").json()}
    saving, sub = group(client, "저금")["id"], group(client, "구독")["id"]
    # 저금: 청약을 맨 앞으로 / 구독료를 저금으로 옮겨 맨 뒤에
    order = [
        {"group_id": saving, "item_ids": [items["주택청약"]["id"], items["예·적금"]["id"], items["구독료"]["id"]]},
        {"group_id": sub, "item_ids": []},
    ]
    res = client.put("/api/recurring-items/order", json=order)
    assert res.status_code == 200, res.text
    in_saving = [i["name"] for i in res.json() if i["group_id"] == saving]
    assert in_saving == ["주택청약", "예·적금", "구독료"]
    assert next(i for i in res.json() if i["name"] == "구독료")["group_name"] == "저금"


def test_reorder_rejects_duplicates_and_unknown(client):
    saving = group(client, "저금")["id"]
    first = client.get("/api/recurring-items").json()[0]["id"]
    assert client.put("/api/recurring-items/order",
                      json=[{"group_id": saving, "item_ids": [first, first]}]).status_code == 400
    assert client.put("/api/recurring-items/order",
                      json=[{"group_id": saving, "item_ids": [99999]}]).status_code == 400
    assert client.put("/api/recurring-items/order",
                      json=[{"group_id": 99999, "item_ids": []}]).status_code == 400


def test_internal_transfer_to_own_savings_matches_recurring(setup):
    client = setup
    client.post("/api/accounts", json={"name": "내 이름", "keyword": "권민석"})
    set_recurring(client, "ISA 자동이체", amount=300000, match_keyword="238.권민석")
    tx = add_tx(client, type="transfer", merchant="238.권민석", amount=300000, occurred_on="2026-10-01")
    assert (tx["transfer_kind"], tx["recurring_name"], tx["needs_review"]) == ("internal", "ISA 자동이체", False)
    s = client.get("/api/summary", params={"on": "2026-10-01"}).json()
    assert s["variable"]["spent_total"] == 0  # 집계는 ±0 그대로
    assert next(i for i in s["recurring"]["items"] if i["name"] == "ISA 자동이체")["status"] == "paid"


def test_loan_money_received_is_not_a_repayment(setup):
    client = setup
    client.put("/api/settings", json={"loan_counterparties": "홍부모"})
    set_recurring(client, "예·적금", amount=1000000, match_keyword="홍부모")
    received = add_tx(client, type="transfer", transfer_kind="internal", merchant="홍부모", amount=1000000)
    assert received["recurring_id"] is None
    repaid = add_tx(client, type="transfer", transfer_kind="external", merchant="농협-홍부모", amount=1000000)
    assert repaid["recurring_name"] == "예·적금"


def test_search_filters_range_and_sums(setup):
    client = setup
    food, life = cat_id(client, "식비"), cat_id(client, "생활비")
    add_tx(client, occurred_on="2026-10-01", merchant="스타벅스 강남점", amount=4500, category_id=food,
           payment_method="현대카드", memo="친구랑")
    add_tx(client, occurred_on="2026-05-01", merchant="스타벅스 역삼점", amount=5000, category_id=food,
           payment_method="삼성카드")
    add_tx(client, occurred_on="2024-01-01", merchant="스타벅스 옛날", amount=3000, category_id=food)
    add_tx(client, occurred_on="2026-10-02", merchant="다이소", amount=2000, category_id=life, payment_method="현대카드")
    add_tx(client, occurred_on="2026-10-03", merchant="쿠팡", amount=9900)                       # 미분류
    add_tx(client, occurred_on="2026-10-04", type="income", merchant="급여", amount=3000000)
    add_tx(client, occurred_on="2026-10-05", type="transfer", transfer_kind="external", merchant="김철수", amount=7000)

    # 기간 보기 (기본)
    period = client.get("/api/transactions", params={"on": "2026-10-01"}).json()
    assert period["period"] is not None and period["total"] == 5

    # 검색은 범위로: 최근 12개월 (오늘 기준) — 2024년 건은 빠진다
    res = client.get("/api/transactions", params={"q": "스타벅스", "months": 12, "end": "2026-10-08"}).json()
    assert res["period"] is None and {t["merchant"] for t in res["transactions"]} == {"스타벅스 강남점", "스타벅스 역삼점"}
    assert res["sums"]["expense"] == 9500
    assert client.get("/api/transactions", params={"q": "스타벅스", "months": 0}).json()["total"] == 3
    # 메모·결제수단·카테고리 이름으로도
    assert client.get("/api/transactions", params={"q": "친구", "months": 0}).json()["total"] == 1
    assert client.get("/api/transactions", params={"q": "생활비", "months": 0}).json()["transactions"][0]["merchant"] == "다이소"

    f = {"months": 0}
    assert client.get("/api/transactions", params={**f, "category_id": "none"}).json()["transactions"][0]["merchant"] == "쿠팡"
    assert client.get("/api/transactions", params={**f, "payment_method": "현대카드"}).json()["total"] == 2
    assert client.get("/api/transactions", params={**f, "type": "income"}).json()["sums"]["income"] == 3000000
    assert client.get("/api/transactions", params={**f, "needs_review": True}).json()["total"] == 1
    page = client.get("/api/transactions", params={**f, "limit": 2, "offset": 2}).json()
    assert page["total"] == 7 and len(page["transactions"]) == 2

    methods = client.get("/api/transactions/payment-methods").json()
    assert methods[0] == {"name": "현대카드", "count": 2}


def test_reorder_recurring_groups(client):
    groups = client.get("/api/recurring-groups").json()
    ids = [g["id"] for g in groups]
    new = [ids[-1], *ids[:-1]]  # 마지막 칸을 맨 위로
    res = client.put("/api/recurring-groups/order", json=new)
    assert res.status_code == 200 and [g["id"] for g in res.json()] == new
    assert client.put("/api/recurring-groups/order", json=new[:-1]).status_code == 400


def test_recurring_without_day_is_floating(setup):
    client = setup
    item = set_recurring(client, "구독료", amount=17000, day_of_month=None, match_keyword="넷플릭스")
    assert item["day_of_month"] is None
    today = date.today()
    current = {i["name"]: i for i in client.get("/api/recurring-status").json()["items"]}["구독료"]
    assert (current["status"], current["due_date"]) == ("floating", None)   # 이번 기간: 미정
    assert client.get("/api/summary").json()["recurring"]["missed"] == 0      # 미정은 미확인으로 세지 않는다
    past = client.get("/api/recurring-status", params={"on": (today - timedelta(days=70)).isoformat()}).json()
    assert {i["name"]: i for i in past["items"]}["구독료"]["status"] == "missed"  # 지난 기간에 안 나갔으면 미확인
    add_tx(client, merchant="넷플릭스", amount=17000, occurred_on=today.isoformat())
    paid = {i["name"]: i for i in client.get("/api/recurring-status").json()["items"]}["구독료"]
    assert paid["status"] == "paid"


def test_skip_missed_recurring_for_this_period_only(setup):
    client = setup
    period = client.get("/api/summary").json()["period"]
    start = date.fromisoformat(period["start"])
    item = set_recurring(client, "보험료", amount=80000, day_of_month=start.day)
    before = client.get("/api/summary").json()
    status = {i["name"]: i for i in before["recurring"]["items"]}["보험료"]["status"]
    assert status in ("missed", "upcoming")

    res = client.post(f"/api/recurring-items/{item['id']}/skip")
    assert res.json()["skipped"] is True and res.json()["period_start"] == period["start"]
    after = client.get("/api/summary").json()
    assert {i["name"]: i for i in after["recurring"]["items"]}["보험료"]["status"] == "skipped"
    assert after["recurring"]["missed"] == 0 and after["recurring"]["skipped_total"] == 80000
    assert after["recurring"]["total"] == before["recurring"]["total"] - 80000
    assert after["variable"]["pool"] == before["variable"]["pool"] + 80000

    # 다음 기간에는 다시 나타난다
    nxt = client.get("/api/recurring-status", params={"on": (date.fromisoformat(period["end"]) + timedelta(days=1)).isoformat()})
    assert {i["name"]: i for i in nxt.json()["items"]}["보험료"]["status"] != "skipped"
    # 건너뛰어도 실제로 나가면 확인됨
    add_tx(client, merchant="보험", amount=80000, occurred_on=start.isoformat())  # 결제일에 — 오늘이면 결제일과 멀 때 짝이 안 된다
    assert {i["name"]: i for i in client.get("/api/recurring-status").json()["items"]}["보험료"]["status"] == "paid"
    # 되돌리기
    assert client.delete(f"/api/recurring-items/{item['id']}/skip").json()["skipped"] is False
    assert client.post("/api/recurring-items/9999/skip").status_code == 404


def test_refund_offsets_variable_spending_not_income(setup):
    client = setup
    food = cat_id(client, "식비")
    add_tx(client, merchant="회식 고깃집", amount=120000, category_id=food, occurred_on="2026-10-01")
    add_tx(client, type="refund", merchant="김철수", amount=30000, category_id=food, occurred_on="2026-10-02")
    add_tx(client, type="refund", merchant="이영희", amount=30000, occurred_on="2026-10-02")   # 카테고리 없음
    add_tx(client, type="income", merchant="급여", amount=3000000, occurred_on="2026-10-03")
    s = client.get("/api/summary", params={"on": "2026-10-01"}).json()
    food_row = next(c for c in s["variable"]["categories"] if c["name"] == "식비")
    assert food_row["spent"] == 90000                     # 식비 120,000 − 정산 30,000
    assert s["variable"]["uncategorized"] == -30000        # 카테고리 없는 정산은 미분류에서 빠진다
    assert s["variable"]["spent_total"] == 60000
    assert s["variable"]["refund_total"] == 60000
    assert s["income"]["actual"] == 3000000               # 정산은 수입이 아니다
    lst = client.get("/api/transactions", params={"on": "2026-10-01"}).json()
    assert lst["sums"]["refund"] == 60000 and lst["sums"]["income"] == 3000000


def test_refund_is_never_matched_or_flagged(setup):
    client = setup
    set_recurring(client, "구독료", amount=17000, match_keyword="넷플릭스")
    r = add_tx(client, type="refund", merchant="넷플릭스 환불", amount=17000, occurred_on="2026-10-02")
    assert (r["recurring_id"], r["needs_review"], r["transfer_kind"]) == (None, False, None)


def isa_status(client, on):
    s = client.get("/api/summary", params={"on": on}).json()
    return s, next(i for i in s["recurring"]["items"] if i["name"] == "ISA 자동이체")


def test_recurring_paid_early_before_payday_counts_for_next_period(client):
    """수입일·출금일 21일인데 21일이 주말·연휴라 20일(지난 기간 마지막 날)에 미리 나간 결제는 다음 기간 몫."""
    client.put("/api/settings", json={"monthly_income": 3_000_000, "payday": 21})
    set_recurring(client, "ISA 자동이체", amount=300000, day_of_month=21, match_keyword="ISA")
    sept = add_tx(client, type="transfer", transfer_kind="external", merchant="미래에셋 ISA", amount=300000,
                  occurred_on="2026-09-21")
    early = add_tx(client, type="transfer", transfer_kind="external", merchant="미래에셋 ISA", amount=300000,
                   occurred_on="2026-10-20")
    assert sept["recurring_name"] == early["recurring_name"] == "ISA 자동이체"  # 예전엔 같은 기간이라 거부 → 분류 필요
    assert early["needs_review"] is False

    s, isa = isa_status(client, "2026-10-25")
    assert isa["status"] == "paid" and isa["transaction"]["id"] == early["id"] and isa["early"] is True
    s, isa = isa_status(client, "2026-10-01")
    assert isa["status"] == "paid" and isa["transaction"]["id"] == sept["id"] and isa["early"] is False
    assert s["variable"]["spent_total"] == 0  # 미리 나간 결제도 변동비가 아니다

    # 다음 달 몫이 또 하루 일찍 나가도 같은 방식 (연속으로 미리 나가는 경우)
    nov = add_tx(client, type="transfer", transfer_kind="external", merchant="미래에셋 ISA", amount=300000,
                 occurred_on="2026-11-20")
    assert nov["recurring_name"] == "ISA 자동이체"
    assert isa_status(client, "2026-11-25")[1]["transaction"]["id"] == nov["id"]
    assert isa_status(client, "2026-10-25")[1]["transaction"]["id"] == early["id"]


def test_late_payment_on_payday_eve_stays_in_its_period(client):
    """지난 기간 몫을 늦게(수입일 전날) 냈고 다음 기간 몫은 제때 냈으면 각자 자기 기간 (실데이터 ISA 4/20·4/21)."""
    client.put("/api/settings", json={"monthly_income": 3_000_000, "payday": 21})
    set_recurring(client, "ISA 자동이체", amount=300000, day_of_month=21, match_keyword="ISA")
    late = add_tx(client, type="transfer", transfer_kind="external", merchant="미래에셋 ISA", amount=300000,
                  occurred_on="2026-04-20")
    on_time = add_tx(client, type="transfer", transfer_kind="external", merchant="미래에셋 ISA", amount=300000,
                     occurred_on="2026-04-21")
    assert late["recurring_name"] == on_time["recurring_name"] == "ISA 자동이체"
    assert isa_status(client, "2026-04-01")[1]["transaction"]["id"] == late["id"]
    assert isa_status(client, "2026-05-01")[1]["transaction"]["id"] == on_time["id"]

    # 같은 기간 몫이 세 번째로 나오면 연결하지 않는다
    third = add_tx(client, type="transfer", transfer_kind="external", merchant="미래에셋 ISA", amount=300000,
                   occurred_on="2026-05-02")
    assert third["recurring_id"] is None


def test_payment_more_than_a_week_early_is_not_moved(client):
    client.put("/api/settings", json={"monthly_income": 3_000_000, "payday": 21})
    set_recurring(client, "ISA 자동이체", amount=300000, day_of_month=21, match_keyword="ISA")
    add_tx(client, type="transfer", transfer_kind="external", merchant="미래에셋 ISA", amount=300000, occurred_on="2026-09-21")
    # 출금일(10/21)보다 9일 앞 — 미리 낸 것으로 보지 않아 9/21 기간과 겹친다
    assert add_tx(client, type="transfer", transfer_kind="external", merchant="미래에셋 ISA", amount=300000,
                  occurred_on="2026-10-12")["recurring_id"] is None
    assert isa_status(client, "2026-10-25")[1]["status"] in ("upcoming", "missed")


def test_startup_relinks_payments_refused_by_the_old_rule(client):
    """예전 규칙에선 같은 기간에 이미 결제가 있다고 거부돼 변동비로 남은 '미리 나간 결제'를 서버 시작 때 연결한다."""
    from app.core.db import connect
    from app.recurring.matching import relink_recurring

    client.put("/api/settings", json={"monthly_income": 3_000_000, "payday": 21})
    set_recurring(client, "ISA 자동이체", amount=300000, day_of_month=21, match_keyword="ISA")
    add_tx(client, type="transfer", transfer_kind="external", merchant="미래에셋 ISA", amount=300000, occurred_on="2026-09-21")
    early = add_tx(client, type="transfer", transfer_kind="external", merchant="미래에셋 ISA", amount=300000,
                   occurred_on="2026-10-20")
    conn = connect()
    try:  # 예전 규칙으로 저장된 상태를 흉내 낸다: 연결 없음 + 분류 필요
        conn.execute("UPDATE transactions SET recurring_id = NULL, needs_review = 1 WHERE id = ?", (early["id"],))
        conn.commit()
        assert isa_status(client, "2026-10-25")[1]["status"] == "missed"
        assert relink_recurring(conn) == 1
        assert relink_recurring(conn) == 0  # 몇 번 돌려도 같다
    finally:
        conn.close()
    s, isa = isa_status(client, "2026-10-25")
    assert isa["status"] == "paid" and isa["transaction"]["id"] == early["id"]
    assert client.get("/api/summary", params={"on": "2026-10-01"}).json()["needs_review"] == 0
