"""소비 습관 분석: 사실 계산(고정 날짜) + LLM 보고서 정리 + 실험실 작업·API(오늘 기준 날짜)."""

import re
from datetime import date, timedelta

import pytest

from app.core import db
from app.insights import facts, report
from app.insights.facts import InsightsError
from app.ledger.merchants import merchant_key

TODAY = date(2026, 7, 10)  # 수입일 25일 → 이번 기간 6.25~7.24, 분석 기간(1개월) 5.25~6.24, 비교 기간 4.25~5.24


@pytest.fixture
def conn():
    db.init_db()
    c = db.connect()
    yield c
    c.close()


def cat(conn, name):
    return conn.execute("SELECT id FROM categories WHERE name = ?", (name,)).fetchone()[0]


def add(conn, on, amount, merchant="", type="expense", transfer_kind=None, category=None, time=None, recurring_id=None):
    conn.execute(
        "INSERT INTO transactions (occurred_on, occurred_time, type, transfer_kind, amount, merchant, merchant_key, category_id, "
        "recurring_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (on, time, type, transfer_kind, amount, merchant, merchant_key(merchant), cat(conn, category) if category else None,
         recurring_id),
    )
    conn.commit()


def texts(result):
    return "\n".join(f["text"] for f in result["facts"])


def test_window_baseline_and_one_off_big_spend(conn):
    conn.execute("UPDATE categories SET budget = 300000 WHERE name = '식비'")
    add(conn, "2026-04-25", 100000, "김밥천국", category="식비")
    add(conn, "2026-05-01", 5_000_000, "보증금", category="기타")          # 비교 기간 일회성 큰 지출
    add(conn, "2026-05-30", 150000, "김밥천국", category="식비")
    add(conn, "2026-06-10", 250000, "배달의민족", category="식비")
    add(conn, "2026-06-12", 1_200_000, "노트북매장", category="여가·유흥")  # 분석 기간 일회성 큰 지출
    add(conn, "2026-06-20", 50000, "정산", type="refund", category="식비")
    add(conn, "2026-07-01", 30000, "김밥천국", category="식비")            # 이번 기간 — 분석 기간에 안 들어감
    r = facts.compute(conn, 1, today=TODAY)
    assert r["window"]["start"] == "2026-05-25" and r["window"]["end"] == "2026-06-24"
    assert r["baseline"]["start"] == "2026-04-25"
    k = r["stats"]["kpis"]
    assert k["avg_total"] == 150000 + 250000 - 50000           # 일회성 제외, 정산·환불 차감
    assert k["ledger_total"] == 350000 + 1_200_000 and k["one_off_count"] == 1
    assert k["baseline_avg"] == 100000                           # 비교 기간도 보증금 제외
    t = texts(r)
    assert "일회성 큰 지출" in t and "노트북매장 1,200,000원" in t and "+250%" in t
    assert "식비: 기간 평균 350,000원" in t and "예산 300,000원의 117%" in t
    assert r["stats"]["periods"][1]["one_off"] == 1_200_000 and r["stats"]["periods"][1]["in_window"]


def test_habit_facts_and_privacy(conn):
    add(conn, "2026-04-20", 1000, "시작")  # 데이터 시작 (비교 기간 전체가 들어가도록)
    for d in range(25, 32):                # 5.25~5.31 수입일 직후: 매일 3만 원
        add(conn, f"2026-05-{d:02d}", 30000, "편의점 강남점", category="생활비", time="23:30:00")
    for d in range(1, 25):                 # 6.1~6.24: 매일 5천 원 커피
        add(conn, f"2026-06-{d:02d}", 5000, "스타벅스 역삼점", category="식비", time="09:10:00")
    add(conn, "2026-06-05", 80000, "홍길동", type="transfer", transfer_kind="external", category="기타")
    add(conn, "2026-06-07", 45000, "123-456-789012", category="기타", time="13:00:00")
    r = facts.compute(conn, 1, today=TODAY)
    t = texts(r)
    assert "홍길동" not in t and "123-456-789012" not in t      # 이체 상대·계좌번호처럼 보이는 이름은 보내지 않는다
    assert "(번호로 된 상대)" in t and "송금(다른 사람 계좌로 보낸 돈) 1건, 합계 80,000원" in t
    assert "자주 결제한 곳: 스타벅스 24건" in t                 # 지점명은 정규화 키로
    assert "10,000원 미만 결제 24건" in t
    assert "밤 10시~새벽 4시 결제 7건, 합계 210,000원" in t
    k = r["stats"]["kpis"]
    assert k["payday_ratio"] == round((210000 / 7) / ((120000 + 45000) / 24), 2)
    assert r["stats"]["hours"][23]["count"] == 7 and r["stats"]["hour_coverage"] == 1.0
    assert [w["day"] for w in r["stats"]["weekday"]] == list("월화수목금토일")


def test_needs_a_finished_period(conn):
    with pytest.raises(InsightsError, match="거래가 없어"):
        facts.compute(conn, 3, today=TODAY)
    add(conn, "2026-07-01", 10000, "김밥천국")
    with pytest.raises(InsightsError, match="끝난 기간"):
        facts.compute(conn, 3, today=TODAY)
    with pytest.raises(InsightsError, match="개월"):
        facts.compute(conn, 2, today=TODAY)


def test_clean_drops_unknown_fact_ids():
    raw = {"title": " 7월 ", "headline": "배달이 많아요", "summary": "요약",
           "habits": [{"title": "배달", "tone": "watch", "detail": "배달이 잦음", "fact_ids": [1, 99, 1]},
                      {"title": "근거 없음", "tone": "weird", "detail": "지어낸 말", "fact_ids": [42]},
                      {"title": "빈 것", "tone": "good", "detail": "", "fact_ids": [1]}],
           "suggestions": [{"action": "배달 주 2회로", "reason": "사실 1", "fact_ids": [2], "monthly_saving": 9_999_999}],
           "questions": ["  ", "미분류 정리"]}
    rep, dropped, ungrounded = report.clean(raw, {1, 2}, cap=300000)
    assert dropped == 2 and ungrounded == 1
    assert rep["title"] == "7월" and [h["fact_ids"] for h in rep["habits"]] == [[1], []]
    assert rep["habits"][1]["tone"] == "neutral" and rep["suggestions"][0]["monthly_saving"] == 300000
    assert rep["questions"] == ["미분류 정리"] and rep["category_notes"] == []


def test_report_job_and_api(client, monkeypatch):
    today = date.today()
    conn = db.connect()
    for i in range(1, 130):  # 넉 달 남짓 매일 결제 (끝난 기간이 생기도록)
        d = (today - timedelta(days=i)).isoformat()
        add(conn, d, 12000 if i % 3 else 4500, "배달의민족" if i % 3 else "스타벅스", category="식비", time="20:00:00")
    add(conn, (today - timedelta(days=40)).isoformat(), 300000, "김철수", type="transfer", transfer_kind="external")
    conn.close()

    seen = {}

    async def fake_llm(feature, system, prompt, schema, model):
        seen.update(feature=feature, prompt=prompt, model=model)
        ids = [int(x) for x in re.findall(r"^\[(\d+)\]", prompt, re.M)]
        return {"title": "배달 습관", "headline": "저녁 배달이 많아요", "summary": "요약",
                "habits": [{"title": "저녁 배달", "tone": "watch", "detail": "저녁 8시 결제가 대부분", "fact_ids": [ids[0], 999]}],
                "category_notes": [{"category": "식비", "note": "대부분 배달", "fact_ids": ids[1:2]}],
                "suggestions": [{"action": "배달 주 3회로", "reason": "횟수", "fact_ids": ids[:1], "monthly_saving": 50000}]}

    monkeypatch.setattr(report, "LLM", fake_llm)
    stats = client.get("/api/spending/stats?months=1").json()
    assert stats["facts"] and stats["stats"]["merchants"][0]["name"] == "배달의민족"
    assert client.get("/api/spending/stats?months=2").status_code == 400

    run = client.post("/api/spending/reports", json={"months": 1, "model": "claude-haiku-4-5-20251001"}).json()
    assert run["status"] == "succeeded", run.get("error")
    assert run["summary"]["citations_dropped"] == 1 and run["summary"]["habits"] == 1
    assert seen["feature"] == "spending_report" and seen["model"] == "claude-haiku-4-5-20251001"
    assert "김철수" not in seen["prompt"] and "[1] 분석 기간" in seen["prompt"] and "식비: 외식, 배달" in seen["prompt"]
    detail = client.get(f"/api/spending/reports/{run['id']}").json()
    rep = detail["report"]
    assert rep["title"] == "배달 습관" and rep["habits"][0]["fact_ids"] == [1] and rep["facts"][0]["id"] == 1
    assert rep["stats"]["kpis"]["avg_total"] > 0 and rep["window"]["periods"] == 1
    assert client.get("/api/spending/reports").json()[0]["id"] == run["id"]
    conn = db.connect()
    other = conn.execute("INSERT INTO runs (kind, name) VALUES ('news_report', '뉴스') RETURNING id").fetchone()[0]
    conn.commit()
    conn.close()
    assert client.get(f"/api/spending/reports/{other}").status_code == 404


def test_report_needs_data(client):
    r = client.post("/api/spending/reports", json={"months": 3})
    assert r.status_code == 400 and "거래가 없어" in r.json()["detail"]
