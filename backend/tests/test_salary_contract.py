"""연봉 기준 — 연봉 구성 저장(절세 계산과 같은 값) · 달마다 초안(입금으로 거꾸로) · 실제 명세서로 맞추기 · 저장 · 연말 추정의 상여."""

from datetime import date

from app.core.db import connect
from app.salary import analysis, contract, rules

PARTS = {"months": 12, "base_monthly": 4_000_000, "meal_monthly": 200_000, "meal_provided": False, "car_monthly": 0,
         "childcare_monthly": 0, "young_children": 0, "bonus": 3_000_000, "retro_pay": 0, "settlement": 0, "welfare_points": 0,
         "welfare_public": False, "other_taxable": 0, "other_taxfree": 0}


def _income(client, day, amount, merchant="정기급여"):
    client.post("/api/transactions", json={"occurred_on": day, "type": "income", "amount": amount, "merchant": merchant})


def test_contract_saves_into_tax_profile(client):
    got = client.put("/api/salary/contract", json=PARTS).json()
    assert got["gross_salary"] == 4_000_000 * 12 + 3_000_000 and got["monthly"]["taxable"] == 4_000_000
    assert got["monthly"]["nontaxable"] == 200_000 and got["monthly"]["social"] == sum(rules.expected(4_000_000)[k] for k in rules.SOCIAL)
    with connect() as conn:
        assert contract.profile(conn)["gross_salary"] == 51_000_000          # 절세 계산이 같은 총급여를 쓴다


def test_plan_back_solves_from_deposits_and_flags_odd_months(client):
    client.put("/api/salary/contract", json=PARTS)
    social = sum(rules.expected(4_000_000)[k] for k in rules.SOCIAL)
    for m in ("01", "02", "03"):
        _income(client, f"2026-{m}-21", 3_500_000)
    _income(client, "2026-04-21", 6_000_000)                               # 연말정산 환급이 섞인 달
    _income(client, "2026-04-30", 1_200_000, "임금인상소급")
    with connect() as conn:
        p = contract.plan(conn, 2026, date(2026, 5, 10))
    assert p["regular_name"] == "정기급여" and [d["pay_month"] for d in p["drafts"]] == ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05"]
    jan = p["drafts"][0]
    implied = 4_200_000 - social - 3_500_000
    assert jan["net_pay"] == 3_500_000 and jan["income_tax"] + jan["local_income_tax"] + jan["other_deductions"] == implied
    assert jan["other_deductions"] > 0 and "기타 공제" in jan["basis"]
    apr = p["drafts"][3]
    assert apr["net_pay"] is None and "많이 달라요" in apr["basis"]          # 거꾸로 내지 않고 추정 세금
    assert p["drafts"][4]["basis"] == "추정 세금 (입금 없음)"
    assert [(o["merchant"], o["kind"]) for o in p["others"]] == [("임금인상소급", "retro")]


def test_real_payslip_calibrates_other_deductions_and_apply_saves(client):
    client.put("/api/salary/contract", json=PARTS)
    social = sum(rules.expected(4_000_000)[k] for k in rules.SOCIAL)
    client.post("/api/salary", json={"pay_month": "2026-01", "taxable_pay": 4_000_000, "nontaxable_pay": 200_000,
                                     **rules.expected(4_000_000), "income_tax": 250_000, "local_income_tax": 25_000,
                                     "other_deductions": 30_000})
    for m in ("02", "03", "04"):
        _income(client, f"2026-{m}-21", 3_500_000)
    with connect() as conn:
        p = contract.plan(conn, 2026, date(2026, 4, 30))
    assert p["calibrated_by"] == "2026-01" and p["skipped"] == ["2026-01"]
    feb = p["drafts"][0]
    assert feb["other_deductions"] == 30_000 and feb["income_tax"] + feb["local_income_tax"] == 4_200_000 - social - 3_500_000 - 30_000
    r = client.post("/api/salary/plan", json={"year": 2026, "months": ["2026-02"]})
    assert r.status_code == 201 and r.json()["created"] == 1
    slips = client.get("/api/salary", params={"year": 2026}).json()["slips"]
    est = next(s for s in slips if s["pay_month"] == "2026-02")
    assert est["source"] == "estimate" and est["checks"][0]["key"] == "estimate" and est["deposit"]["occurred_on"] == "2026-02-21"


def test_year_projection_adds_planned_bonus_not_yet_recorded(client):
    client.put("/api/salary/contract", json=PARTS)
    client.post("/api/salary", json={"pay_month": "2026-01", "taxable_pay": 4_000_000, "income_tax": 250_000, "local_income_tax": 25_000})
    with connect() as conn:
        p = analysis.summary(conn, 2026, today=date(2026, 1, 31))["projection"]
    assert p["extras_added"] == 3_000_000 and p["gross_salary"] == 12 * 4_000_000 + 3_000_000
    client.post("/api/salary", json={"pay_month": "2026-01", "kind": "bonus", "taxable_pay": 1_000_000})
    with connect() as conn:
        assert analysis.summary(conn, 2026, today=date(2026, 1, 31))["projection"]["extras_added"] == 2_000_000


def test_plan_without_contract_says_so(client):
    assert "연봉 구성이 없어요" in client.get("/api/salary/plan", params={"year": 2026}).json()["note"]
