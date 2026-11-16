"""급여 관리 — 명세서 기록 · 검산 · 올해 흐름 · 연말정산 추정 · 가계부 입금 맞춤 · 명세서 판독(OCR · Vision)."""

import asyncio
import json
from datetime import date

import pytest

from app.salary import analysis, extract, rules

SLIP = {"pay_month": "2026-03", "paid_on": "2026-03-25", "employer": "테스트상사", "taxable_pay": 3_800_000, "nontaxable_pay": 200_000,
        "national_pension": 180_500, "health_insurance": 136_610, "long_term_care": 17_950, "employment_insurance": 34_200,
        "income_tax": 200_000, "local_income_tax": 20_000, "net_pay": 3_410_740}


def test_expected_social_insurance_matches_2026_rates():
    e = rules.expected(3_800_000, income_tax=200_000)
    assert e == {"national_pension": 180_500, "health_insurance": 136_610, "long_term_care": 17_950, "employment_insurance": 34_200,
                 "local_income_tax": 20_000}


def test_slip_checks_net_and_rates(client):
    v = client.post("/api/salary", json=SLIP).json()
    assert v["gross_pay"] == 4_000_000 and v["deductions"] == 589_260 and v["net"] == 3_410_740
    assert all(c["ok"] for c in v["checks"]), v["checks"]
    assert v["take_home_rate"] == pytest.approx(0.8527, abs=1e-4)
    assert v["deposit"] is None and "입금이 없어요" in v["deposit_note"]
    # 국민연금이 적으면 상한 가능성을, 실지급액이 안 맞으면 빠진 줄을 알려 준다
    bad = client.post("/api/salary", json={**SLIP, "pay_month": "2026-04", "national_pension": 150_000, "net_pay": 3_400_000}).json()
    by = {c["key"]: c for c in bad["checks"]}
    assert by["national_pension"]["ok"] is False and "상한" in by["national_pension"]["text"]
    assert by["net"]["ok"] is False and "빠진" in by["net"]["text"]
    # 상여 명세서는 요율 검산을 하지 않는다
    bonus = client.post("/api/salary", json={"pay_month": "2026-04", "kind": "bonus", "taxable_pay": 1_000_000, "income_tax": 50_000}).json()
    assert [c["key"] for c in bonus["checks"]] == []


def test_deposit_is_matched_with_ledger_income(client):
    client.post("/api/transactions", json={"occurred_on": "2026-03-24", "type": "income", "amount": 3_410_740, "merchant": "급여"})
    v = client.post("/api/salary", json=SLIP).json()
    assert v["deposit"]["occurred_on"] == "2026-03-24" and v["deposit_note"] is None


def test_year_summary_projection_and_refund_estimate(client):
    from app.core.db import connect

    for m in ("01", "02", "03"):
        client.post("/api/salary", json={**SLIP, "pay_month": f"2026-{m}", "paid_on": f"2026-{m}-25"})
    client.post("/api/salary", json={"pay_month": "2026-02", "kind": "bonus", "taxable_pay": 2_000_000, "income_tax": 300_000,
                                     "local_income_tax": 30_000})
    with connect() as conn:
        s = analysis.summary(conn, 2026, today=date(2026, 3, 31))
    assert [m["month"] for m in s["months"]] == ["2026-01", "2026-02", "2026-03"]
    assert s["totals"]["taxable_pay"] == 3 * 3_800_000 + 2_000_000
    p = s["projection"]
    assert p["rest_months"] == 9 and p["filled_before"] == 0 and p["gross_salary"] == 3 * 3_800_000 + 2_000_000 + 9 * 3_800_000
    assert p["withheld"] == 3 * 220_000 + 330_000 + 9 * 220_000 and p["note"] == "상여 · 소급분은 기록한 것만 넣고 잇지 않았어요"
    e = s["estimate"]
    assert e["refund"] == e["withheld"] - e["decided"] and e["decided"] > 0 and ("돌려받" in e["text"] or "더 낼" in e["text"])
    assert s["rates"]["tax"] == pytest.approx(s["totals"]["taxes"] / s["totals"]["gross_pay"], abs=1e-4)


def test_records_starting_mid_year_fill_the_earlier_months(client):
    """8월부터 기록했으면 1~7월도 최근 평균으로 채워 1년 총급여를 낸다 (안 그러면 환급이 크게 부풀려진다)."""
    from app.core.db import connect

    for m in ("08", "09", "10"):
        client.post("/api/salary", json={**SLIP, "pay_month": f"2026-{m}"})
    with connect() as conn:
        p = analysis.summary(conn, 2026, today=date(2026, 11, 16))["projection"]
    assert (p["filled_before"], p["rest_months"], p["filled_months"]) == (7, 2, 9)
    assert p["gross_salary"] == 12 * 3_800_000 and p["withheld"] == 12 * 220_000
    assert "1월, 2월" in p["note"] and "입사" in p["note"]


def test_tax_insight_uses_salary_records_for_gross(client):
    """소비 분석 > 절세: 총급여를 안 넣었으면 급여 기록으로 올해 총급여를 잇는다."""
    from app.core.db import connect
    from app.insights import tax

    client.post("/api/transactions", json={"occurred_on": "2026-01-02", "type": "expense", "amount": 1000, "merchant": "시작"})
    for m in ("01", "02"):
        client.post("/api/salary", json={**SLIP, "pay_month": f"2026-{m}"})
    with connect() as conn:
        t = tax.compute(conn, date(2026, 2, 28))
    assert t["gross_source"] == "salary" and t["gross"] == 12 * 3_800_000 and any("급여명세서" in n for n in t["notes"])


def test_api_crud_years_and_validation(client):
    sid = client.post("/api/salary", json=SLIP).json()["id"]
    assert client.post("/api/salary", json={**SLIP, "pay_month": "2026-13"}).status_code == 422
    got = client.put(f"/api/salary/{sid}", json={**SLIP, "memo": "성과급 전"}).json()
    assert got["memo"] == "성과급 전"
    body = client.get("/api/salary", params={"year": 2026}).json()
    assert body["years"] == [2026] and len(body["slips"]) == 1
    assert client.delete(f"/api/salary/{sid}").status_code == 204 and client.delete(f"/api/salary/{sid}").status_code == 404
    assert client.get("/api/salary/rules").json()["pension"] == 0.0475


DRAFT = {"pay_month": "2026-10", "paid_on": "2026-10-25", "kind": "regular", "employer": "테스트상사", "taxable_pay": 3_800_000,
         "nontaxable_pay": 200_000, "national_pension": 180_500, "health_insurance": 136_610, "long_term_care": 17_950,
         "employment_insurance": 34_200, "income_tax": 200_000, "local_income_tax": 20_000, "other_deductions": 0,
         "net_pay": 3_410_740, "items": []}


def test_extract_uses_ocr_text_then_llm(monkeypatch):
    from app.ocr import client as ocr

    monkeypatch.setenv("MLG_OCR_URL", "http://gpu:10000/v1")
    seen = {}
    monkeypatch.setattr(ocr, "read_text", lambda image, mt, prompt=None: {"text": "기본급 3,800,000 식대 200,000 ...", "model": "Unlimited-OCR-2"})

    async def fake_structured(feature, prompt, schema, **kw):
        seen["feature"], seen["prompt"] = feature, prompt
        return DRAFT
    monkeypatch.setattr(extract, "structured", fake_structured)
    out = asyncio.run(extract.extract(b"img", "image/png", "2026-11-16"))
    assert out["via"] == "ocr" and seen["feature"] == "ocr_structure" and "기본급 3,800,000" in seen["prompt"]


def test_extract_falls_back_to_vision_when_ocr_fails_in_auto(monkeypatch):
    from app.ocr import client as ocr

    monkeypatch.setenv("MLG_OCR_URL", "http://gpu:10000/v1")

    def down(*_a, **_k):
        raise ocr.OcrError("OCR 서버 연결 실패: refused")
    monkeypatch.setattr(ocr, "read_text", down)
    seen = {}

    async def fake_structured(feature, prompt, schema, **kw):
        seen["feature"] = feature
        return DRAFT
    monkeypatch.setattr(extract, "structured", fake_structured)
    out = asyncio.run(extract.extract(b"img", "image/png", "2026-11-16"))
    assert out["via"] == "vision" and seen["feature"] == "salary_extract" and "OCR 실패" in out["note"]
    monkeypatch.setenv("MLG_OCR_MODE", "ocr")                                            # ocr 만이면 실패를 그대로
    with pytest.raises(extract.SalaryExtractError, match="OCR 판독 실패"):
        asyncio.run(extract.extract(b"img", "image/png", "2026-11-16"))
    assert json.dumps(DRAFT)
