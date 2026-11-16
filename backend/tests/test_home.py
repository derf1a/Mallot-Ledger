from tests.test_ledger_api import add_tx, cat_id


def test_home_trend_matches_summary(client):
    client.put("/api/settings", json={"monthly_income": 3_000_000, "payday": 25})
    client.post("/api/accounts", json={"name": "비상금", "keyword": "토스뱅크"})
    food = cat_id(client, "식비")
    add_tx(client, occurred_on="2026-09-25", type="income", merchant="회사", amount=3_000_000)
    add_tx(client, occurred_on="2026-10-01", merchant="스타벅스 강남점", amount=12_000, category_id=food)
    add_tx(client, occurred_on="2026-10-01", merchant="이마트", amount=30_000, category_id=food)
    add_tx(client, occurred_on="2026-10-02", type="refund", merchant="김철수", amount=5_000, category_id=food)
    add_tx(client, occurred_on="2026-10-03", type="transfer", merchant="토스뱅크", amount=500_000)  # 내 계좌 — 빠짐
    add_tx(client, occurred_on="2026-09-01", merchant="이마트", amount=20_000, category_id=food)  # 지난 기간

    h = client.get("/api/home", params={"on": "2026-10-01"}).json()
    assert h["period"] == {"start": "2026-09-25", "end": "2026-10-24"}
    assert len(h["daily"]) == 30
    day = next(d for d in h["daily"] if d["date"] == "2026-10-01")
    assert (day["spent"], day["count"]) == (42_000, 2)
    assert [t["merchant"] for t in day["top"]] == ["이마트", "스타벅스 강남점"]
    assert next(d for d in h["daily"] if d["date"] == "2026-10-02")["spent"] == -5_000

    assert h["previous"]["start"] == "2026-08-25" and sum(h["previous"]["daily"]) == 20_000
    c = h["categories"][str(food)]
    assert (c["count"], c["previous_spent"]) == (2, 20_000)
    assert [m["name"] for m in c["merchants"]] == ["이마트", "스타벅스 강남점"]

    assert len(h["history"]) == 6
    now = h["history"][-1]
    assert now["current"] is False  # 오늘(실제 날짜)은 이 기간 밖
    assert (now["variable"], now["income"], now["recurring"]) == (37_000, 3_000_000, 0)
    assert h["history"][-2]["variable"] == 20_000

    s = client.get("/api/summary", params={"on": "2026-10-01"}).json()
    assert sum(d["spent"] for d in h["daily"]) == s["variable"]["spent_total"]
