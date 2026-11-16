from datetime import date, timedelta

from tests.test_ledger_api import add_tx, cat_id


def test_budget_overview_references_and_bulk_save(client):
    client.put("/api/settings", json={"monthly_income": 3_000_000, "payday": 21})
    period = client.get("/api/budget").json()["period"]
    start = date.fromisoformat(period["start"])
    food, other = cat_id(client, "식비"), cat_id(client, "기타")

    add_tx(client, occurred_on=(start - timedelta(days=200)).isoformat(), merchant="오래전", amount=1_000, category_id=other)
    add_tx(client, occurred_on=start.isoformat(), merchant="이번", amount=50_000, category_id=food)
    add_tx(client, occurred_on=(start - timedelta(days=1)).isoformat(), merchant="지난", amount=90_000, category_id=food)
    add_tx(client, occurred_on=(start - timedelta(days=2)).isoformat(), merchant="가전", amount=1_500_000, category_id=food)
    add_tx(client, occurred_on=(start - timedelta(days=40)).isoformat(), merchant="두 달 전", amount=60_000, category_id=food)
    add_tx(client, occurred_on=start.isoformat(), merchant="모름", amount=7_000)

    b = client.get("/api/budget").json()
    s = client.get("/api/summary").json()
    assert b["pool"] == s["variable"]["pool"] and b["income"] == 3_000_000
    f = next(c for c in b["categories"] if c["id"] == food)
    assert (f["spent"], f["last"]) == (50_000, 1_590_000)  # 지난 기간은 실제 그대로
    assert f["history"] == [0, 60_000, 90_000] and f["average"] == 50_000  # 평균에선 100만 원 이상 한 건을 뺀다
    assert b["uncategorized"]["spent"] == 7_000
    assert len(b["reference"]["periods"]) == 3

    saved = client.put("/api/budget", json={"budgets": [{"id": food, "budget": 400_000}, {"id": other, "budget": 50_000}]})
    assert saved.status_code == 200
    by_id = {c["id"]: c["budget"] for c in saved.json()["categories"]}
    assert (by_id[food], by_id[other]) == (400_000, 50_000)
    assert client.get("/api/summary").json()["variable"]["budget_total"] == 450_000

    # 없는 카테고리가 섞이면 아무것도 바꾸지 않는다
    assert client.put("/api/budget", json={"budgets": [{"id": food, "budget": 1}, {"id": 9999, "budget": 1}]}).status_code == 404
    assert next(c for c in client.get("/api/budget").json()["categories"] if c["id"] == food)["budget"] == 400_000
    assert client.put("/api/budget", json={"budgets": [{"id": food, "budget": -1}]}).status_code == 422


def test_average_skips_periods_before_data_starts(client):
    client.put("/api/settings", json={"payday": 21})
    start = date.fromisoformat(client.get("/api/budget").json()["period"]["start"])
    add_tx(client, occurred_on=(start - timedelta(days=3)).isoformat(), merchant="첫 거래", amount=30_000,
           category_id=cat_id(client, "식비"))
    b = client.get("/api/budget").json()
    f = next(c for c in b["categories"] if c["name"] == "식비")
    # 지난 기간도 데이터 시작 뒤에 시작한 게 아니라 평균에 넣을 기간이 없다
    assert f["average"] is None and b["reference"]["periods"] == []


def test_category_transactions_match_spent_and_reclassify_moves_them(client):
    client.put("/api/settings", json={"monthly_income": 3_000_000, "payday": 21})
    start = date.fromisoformat(client.get("/api/budget").json()["period"]["start"])
    on = start.isoformat()
    food, living = cat_id(client, "식비"), cat_id(client, "생활비")
    item = next(r for r in client.get("/api/recurring-items").json() if r["name"] == "ISA 자동이체")

    lunch = add_tx(client, occurred_on=on, merchant="김밥천국", amount=8_000, category_id=food)
    add_tx(client, occurred_on=on, merchant="다이소", amount=5_000, category_id=food)  # 잘못 분류된 거래
    add_tx(client, occurred_on=on, type="refund", merchant="정산", amount=3_000, category_id=food)
    add_tx(client, occurred_on=on, type="transfer", transfer_kind="external", merchant="친구", amount=20_000, category_id=food)
    # 정기지출에 연결된 거래는 카테고리가 있어도 변동비가 아니다
    linked = add_tx(client, occurred_on=on, merchant="ISA", amount=10_000, category_id=food, recurring_id=item["id"])
    assert linked["recurring_id"] == item["id"]
    add_tx(client, occurred_on=on, type="refund", merchant="환불", amount=2_000)  # 카테고리 없는 환불 = 미분류에서 뺌

    def listed(category):
        res = client.get("/api/transactions", params={"on": on, "category_id": category, "variable": True}).json()
        return res, {t["merchant"] for t in res["transactions"]}

    b = client.get("/api/budget").json()
    f = next(c for c in b["categories"] if c["id"] == food)
    res, names = listed(food)
    assert names == {"김밥천국", "다이소", "정산", "친구"} and f["count"] == res["total"] == 4
    assert res["sums"]["expense"] + res["sums"]["transfer_out"] - res["sums"]["refund"] == f["spent"] == 30_000
    res, names = listed("none")
    assert names == {"환불"} and b["uncategorized"] == {**b["uncategorized"], "spent": -2_000, "count": 1}

    # 재분류는 거래 수정 그대로 — 사용자가 고른 분류로 옮기면 사용액도 따라 옮겨 간다
    daiso = next(t for t in listed(food)[0]["transactions"] if t["merchant"] == "다이소")
    moved = client.put(f"/api/transactions/{daiso['id']}",
                       json={**daiso, "category_id": living, "category_source": "user", "reviewed": True}).json()
    assert moved["category_id"] == living and moved["category_source"] == "user"
    b = client.get("/api/budget").json()
    by_id = {c["id"]: c for c in b["categories"]}
    assert (by_id[food]["spent"], by_id[food]["count"]) == (25_000, 3)
    assert (by_id[living]["spent"], by_id[living]["count"]) == (5_000, 1)
    assert listed(living)[1] == {"다이소"} and lunch["id"] in {t["id"] for t in listed(food)[0]["transactions"]}
