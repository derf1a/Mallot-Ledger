"""소비 습관 분석의 고정 지출·저금(fixed)·절세(tax, tax_rules): 세법 계산식, 올해 금액 추정, 보고서 절세 팁, 내 정보 API."""

import json
from datetime import date

import pytest

from app.core import db
from app.insights import facts, fixed, report, tax, tax_rules as R
from app.ledger.merchants import merchant_key

TAX_TODAY = date(2026, 10, 29)  # 1.1~10.29 = 302일 관찰, 남은 63일
FIX_TODAY = date(2026, 7, 10)   # 수입일 25일 → 분석 기간(1개월) 5.25~6.24, 비교 기간 4.25~5.24


@pytest.fixture
def conn():
    db.init_db()
    c = db.connect()
    yield c
    c.close()


def setting(conn, key, value):
    conn.execute("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                 (key, json.dumps(value, ensure_ascii=False)))
    conn.commit()


def item(conn, name, group, amount, day):
    gid = conn.execute("SELECT id FROM recurring_groups WHERE name = ?", (group,)).fetchone()[0]
    cur = conn.execute("INSERT INTO recurring_items (name, group_id, amount, day_of_month) VALUES (?, ?, ?, ?)",
                       (name, gid, amount, day))
    conn.commit()
    return cur.lastrowid


def tx(conn, on, amount, merchant="", method="", recurring_id=None, type="expense", transfer_kind=None):
    conn.execute("INSERT INTO transactions (occurred_on, type, transfer_kind, amount, merchant, merchant_key, payment_method, "
                 "recurring_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                 (on, type, transfer_kind, amount, merchant, merchant_key(merchant), method, recurring_id))
    conn.commit()


# ---------- 세법 계산식 ----------

def test_income_tax_tables():
    assert R.earned_income_deduction(4_000_000) == 2_800_000
    assert R.earned_income_deduction(43_200_000) == 11_730_000          # 750만 + 2,820만 × 15%
    assert R.earned_income_deduction(500_000_000) == R.EARNED_DEDUCTION_CAP
    assert R.bracket_tax(34_000_000) == (3_840_000, 0.15)               # 84만 + 2,000만 × 15%
    assert R.bracket_tax(60_000_000) == (8_640_000, 0.24)
    assert R.earned_tax_credit(3_840_000, 52_000_000) == 660_000         # 한도 74만 − 1,900만 × 0.008 → 최소 66만
    assert R.earned_tax_credit(1_000_000, 30_000_000) == 550_000
    t = R.income_tax(50_000_000, deductions=1_000_000, credits=100_000)
    assert t["total"] == round(t["decided"] * 1.1) and t["decided"] == t["calculated"] - t["earned_credit"] - 100_000


def test_card_deduction_threshold_rates_and_limits():
    # 최저사용금액 1천만 원은 신용카드부터 채운다
    c = R.card_deduction(40_000_000, {"credit": 12_000_000, "debit": 3_000_000, "transit": 1_000_000})
    assert c["threshold"] == 10_000_000 and c["deduction"] == 300_000 + 900_000 + 400_000
    c = R.card_deduction(40_000_000, {"credit": 4_000_000, "debit": 8_000_000})
    assert c["deduction"] == 2_000_000 * 0.30                             # 신용 400만 다 쓰고 체크 600만이 최저사용금액
    # 기본 한도 300만 원 + 대중교통 공제액만큼 추가 한도
    c = R.card_deduction(40_000_000, {"credit": 10_000_000, "debit": 15_000_000, "transit": 2_000_000})
    assert c["raw"] == 5_300_000 and c["extra"] == 800_000 and c["deduction"] == 3_800_000
    assert R.card_deduction(40_000_000, {"credit": 10_000_000, "debit": 15_000_000}, children=2)["deduction"] == 4_000_000
    # 총급여 7천만 원 초과: 한도 250만, 문화 30% 없음(신용카드 몫)
    c = R.card_deduction(80_000_000, {"credit": 20_000_000, "culture": 2_000_000})
    assert c["amounts"]["culture"] == 0 and c["deduction"] == round(2_000_000 * 0.15) and c["limit"] == 2_500_000
    assert R.card_deduction(40_000_000, {"credit": 5_000_000})["deduction"] == 0


def test_housing_pension_insurance():
    assert R.housing_deductions(3_000_000, 10_000_000, True, True) == (1_200_000, 2_800_000)   # 합쳐 400만 원
    assert R.housing_deductions(5_000_000, 1_000_000, True, True) == (1_200_000, 400_000)      # 청약은 납입 300만 원까지
    assert R.housing_deductions(1_000_000, 1_000_000, False, True) == (0, 400_000)
    assert R.pension_credit(50_000_000, 7_000_000, 3_000_000) == (9_000_000, 1_350_000)        # 연금저축 600만 + IRP 300만
    assert R.pension_credit(60_000_000, 0, 1_000_000) == (1_000_000, 120_000)
    assert R.insurance_credit(2_000_000) == 120_000


# ---------- 분류 ----------

@pytest.mark.parametrize("method, kind, sure", [
    ("카드의정석 EVERYDAY CHECK", "debit", True), ("하나 트래블로그 체크카드", "debit", True), ("카카오페이 머니", "debit", True),
    ("네이버 현대카드 Edition2", "credit", True), ("우리 SUPER주거래 통장", "none", True),
    ("네이버페이 간편결제(포인트)", "none", False), ("taptap Digital", "credit", False), ("", "credit", False),
])
def test_guess_payment_kind(method, kind, sure):
    assert tax.guess_payment_kind(method) == (kind, sure)


def test_item_key_and_bucket():
    assert tax.item_key("ISA ", "투자") == "isa" and tax.item_key("IRP", "투자") == "irp"
    assert tax.item_key("주택청약", "저금") == "housing_saving" and tax.item_key("전세대출이자", "주거") == "rent_loan"
    assert tax.item_key("실손", "보험") == "insurance" and tax.item_key("적금", "저금") is None

    def row(merchant, item=None, grp=None):
        return {"merchant": merchant, "merchant_key": merchant_key(merchant), "item": item, "grp": grp}

    assert tax._bucket(row("서울교통공사"), "credit") == "transit"
    assert tax._bucket(row("07월서울버스58건"), "debit") == "transit"
    assert tax._bucket(row("놀유니버스"), "credit") == "credit"            # '버스'만으로는 대중교통이 아니다
    assert tax._bucket(row("티머니택시_법인"), "credit") == "credit"
    assert tax._bucket(row("교보문고 광화문점"), "credit") == "culture"
    assert tax._bucket(row("황가네칡냉면 국립중앙박물관점"), "credit") == "credit"  # 지점명의 박물관은 문화가 아니다
    assert tax._bucket(row("삼성생명", "보험료", "보험"), "credit") == "excluded"
    assert tax._bucket(row("skt", "통신비", "통신"), "credit") == "excluded"
    assert tax._bucket(row("이자카야 하루"), "credit") == "credit"           # 가맹점의 '이자'는 빼지 않는다
    assert tax._bucket(row("스타벅스"), "none") == "none"


def test_remaining_payments():
    assert tax._remaining_payments(21, TAX_TODAY, False) == 2                # 11.21, 12.21
    assert tax._remaining_payments(30, TAX_TODAY, False) == 3                # 10.30 도 남음
    assert tax._remaining_payments(30, TAX_TODAY, True) == 2                 # 이번 달은 이미 냄
    assert tax._remaining_payments(None, TAX_TODAY, False) == 3              # 미정 = 말일


# ---------- 올해 절세 추정 ----------

@pytest.fixture
def tax_book(conn):
    setting(conn, "monthly_income", 3_000_000)
    conn.execute("INSERT INTO recurring_groups (name, kind, sort_order) VALUES ('주거', 'expense', 8)")
    irp = item(conn, "IRP", "투자", 100_000, 21)
    house = item(conn, "주택청약", "저금", 100_000, 21)
    loan = item(conn, "전세대출이자", "주거", 400_000, 1)
    ins = item(conn, "보험료", "보험", 50_000, 21)
    tel = item(conn, "통신비", "통신", 30_000, 21)
    tx(conn, "2026-01-01", 1000, "시작", "우리 통장")                   # 올해 1월 1일부터 데이터가 있다
    for m in range(1, 11):
        tx(conn, f"2026-{m:02d}-21", 100_000, "IRP", "우리 통장", irp, "transfer", "internal")
        tx(conn, f"2026-{m:02d}-21", 100_000, "청약", "우리 통장", house, "transfer", "internal")
        tx(conn, f"2026-{m:02d}-21", 50_000, "삼성생명", "현대카드", ins)
        tx(conn, f"2026-{m:02d}-21", 30_000, "SKT", "현대카드", tel)
        for d in (5, 6, 7, 8):                                          # 신용카드 달마다 200만 원 (한 건은 100만 원 미만)
            tx(conn, f"2026-{m:02d}-{d:02d}", 500_000, "백화점", "신한카드 Deep")
        tx(conn, f"2026-{m:02d}-06", 500_000, "마트", "국민 체크카드")
        tx(conn, f"2026-{m:02d}-07", 100_000, "서울교통공사", "현대카드")
    for m in (8, 9, 10):
        tx(conn, f"2026-{m:02d}-01", 400_000, "은행 이자", "우리 통장", loan, "transfer", "external")
    tx(conn, "2026-03-03", 30_000_000, "보증금", "우리 통장")         # 계좌 출금 — 공제 안 됨, 한 건이라 연말 추정에서도 뺀다
    tx(conn, "2026-04-04", 1_200_000, "노트북", "신한카드 Deep")        # 한 건 100만 원 이상 — 올해 사용엔 넣고 추정 속도에선 뺀다
    return {"irp": irp, "loan": loan}


def by_key(t):
    return {x["key"]: x for x in t["items"]}


def test_tax_compute_year_estimate(conn, tax_book):
    setting(conn, "tax_profile", {"gross_salary": 50_000_000, "homeless_head": True, "children": 0, "payment_kinds": {}})
    t = tax.compute(conn, TAX_TODAY)
    assert t["available"] and not t["gross_assumed"] and t["observed_from"] == "2026-01-01"
    items = by_key(t)
    assert items["pension"]["paid"] == 1_000_000 and items["pension"]["total"] == 1_200_000   # 11·12월 출금 예정 더함
    assert items["pension"]["effect"] == round(1_200_000 * 0.15 * 1.1)                       # 총급여 5,500만 원 이하 15% + 지방세
    assert items["housing_saving"]["deduction"] == 480_000 and items["housing_saving"]["status"] == "ok"
    assert items["rent_loan"]["total"] == 2_000_000 and items["rent_loan"]["deduction"] == 800_000
    assert items["insurance"]["total"] == 600_000 and "isa" not in items
    c = t["card"]
    assert c["ytd"]["credit"] == 21_200_000 and c["ytd"]["debit"] == 5_000_000 and c["ytd"]["transit"] == 1_000_000
    assert c["ytd"]["excluded"] == 800_000 and c["ytd"]["none"] == 30_001_000
    assert c["projected"]["credit"] == 21_200_000 + round(20_000_000 / 302 * 63)              # 노트북은 추정 속도에서 뺀다
    assert c["projected"]["none"] == 30_001_000 + round(1_000 / 302 * 63)                     # 보증금 한 건도
    assert c["threshold"] == 12_500_000 and items["card"]["effect"] > 0
    s = t["summary"]
    assert s["saved"] == s["tax_without"] - s["tax_now"] > 0 and s["special"] is True
    # 연금계좌: 결정세액이 0 이 되는 데까지만 효과
    assert 0 < items["pension"]["useful"] <= items["pension"]["room"] == 9_000_000 - 1_200_000
    assert items["pension"]["extra_saving"] <= s["tax_now"] and s["extra_total"] <= s["tax_now"]
    text = "\n".join(tax.fact_lines(t))
    assert "총급여 50,000,000원." in text and "[IRP]" in text and "무주택 세대주 예" in text
    assert "결제수단 분류를 이름으로 추정한 것 0개" in text


def test_tax_profile_conditions_and_assumed_salary(conn, tax_book):
    t = tax.compute(conn, TAX_TODAY)
    assert t["gross_assumed"] and t["gross"] == 36_000_000 and "월 주수입 × 12" in t["notes"][0]
    assert by_key(t)["housing_saving"]["status"] == "check"                                  # 무주택 세대주를 모름 → 확인 필요
    guessed = {m["method"]: m for m in t["methods"]}
    assert guessed["신한카드 Deep"]["kind"] == "credit" and not guessed["신한카드 Deep"]["guessed"]

    setting(conn, "tax_profile", {"gross_salary": 50_000_000, "homeless_head": False, "children": 0,
                                  "payment_kinds": {"신한카드 Deep": "debit"}})
    t2 = tax.compute(conn, TAX_TODAY)
    items = by_key(t2)
    assert items["housing_saving"]["status"] == "no" and items["housing_saving"]["deduction"] == 0
    assert items["rent_loan"]["deduction"] == 0 and items["rent_loan"]["effect"] == 0
    assert t2["card"]["ytd"]["debit"] == 26_200_000 and t2["card"]["ytd"]["credit"] == 0
    assert "무주택 세대주 아니요" in "\n".join(tax.fact_lines(t2))


def test_tax_needs_salary(conn):
    t = tax.compute(conn, TAX_TODAY)
    assert not t["available"] and t["items"] == [] and "총급여" in tax.fact_lines(t)[0]


# ---------- 고정 지출·저금 ----------

def test_fixed_and_saving_facts(conn):
    setting(conn, "monthly_income", 2_000_000)
    tx(conn, "2026-04-20", 1000, "시작")                                  # 데이터 시작 (비교 기간이 다 들어가도록)
    save = item(conn, "적금", "저금", 300_000, 25)
    netflix = item(conn, "넷플릭스", "구독", 17_000, 10)
    new = item(conn, "관리비", "기타", 50_000, 1)
    tx(conn, "2026-04-25", 300_000, "적금", "", save, "transfer", "internal")
    tx(conn, "2026-05-25", 300_000, "적금", "", save, "transfer", "internal")
    tx(conn, "2026-05-10", 17_000, "넷플릭스", "", netflix)               # 비교 기간에만 냄 → 분석 기간 0/1
    tx(conn, "2026-06-01", 55_000, "관리비", "", new)                     # 분석 기간에 처음 냄
    r = facts.compute(conn, 1, today=FIX_TODAY)
    f = r["stats"]["fixed"]
    items = {i["name"]: i for i in f["items"]}
    assert items["적금"]["paid_periods"] == 1 and items["적금"]["baseline_avg"] == 300_000
    assert items["넷플릭스"]["periods"] == 1 and items["넷플릭스"]["paid_periods"] == 0
    assert items["관리비"]["periods"] == 1 and items["관리비"]["paid_avg"] == 55_000 and items["관리비"]["baseline_avg"] is None
    a = f["allocation"]
    assert a["saving"] == 300_000 and a["fixed"] == 55_000 and a["saving_rate"] == 0.15
    assert a["left"] == 2_000_000 - 300_000 - 55_000 - a["variable"]
    assert r["stats"]["kpis"]["saving_rate"] == 0.15
    text = "\n".join(x["text"] for x in r["facts"] if x["group"] in ("fixed", "saving"))
    assert "구독 1개(넷플릭스 17,000원) → 기간당 17,000원, 1년 204,000원" in text
    assert "계획보다 덜 낸 정기지출: 넷플릭스 0/1기간" in text
    assert "주수입 배분" in text and "저금·투자 300,000원(15%)" in text
    assert fixed.SUBSCRIPTION == "구독" and tax.ONE_OFF == facts.ONE_OFF


# ---------- 보고서·API ----------

def test_clean_attaches_code_tax_amounts():
    raw = {"title": "t", "headline": "", "summary": "", "habits": [], "suggestions": [],
           "money_notes": [{"title": "저금", "tone": "good", "detail": "절반을 저금", "fact_ids": [1]}],
           "tax_tips": [{"item": "pension", "action": "IRP 연말까지 더 넣기", "reason": "한도 남음", "fact_ids": [2, 9]},
                        {"item": "crypto", "action": "모르는 항목", "reason": "", "fact_ids": []},
                        {"item": "card", "action": "", "reason": "빈 것", "fact_ids": [1]}]}
    tax_items = [{"key": "pension", "extra_saving": 300_000, "useful": 2_000_000, "effect": 100_000}]
    rep, dropped, ungrounded = report.clean(raw, {1, 2}, cap=0, tax_items=tax_items)
    assert dropped == 1 and ungrounded == 1 and rep["money_notes"][0]["tone"] == "good"
    tips = rep["tax_tips"]
    assert len(tips) == 2 and tips[0]["extra_saving"] == 300_000 and tips[0]["title"] == tax.TITLES["pension"]
    assert tips[1]["item"] == "other" and tips[1]["extra_saving"] == 0
    md = report.to_markdown(rep, {"window": {"label": "x"}, "baseline": None, "facts": []})
    assert "## 절세 (추정)" in md and "연 약 300,000원 더 절세 추정" in md and "## 고정비·저금" in md


def test_tax_profile_api(client):
    r = client.put("/api/spending/tax-profile", json={"gross_salary": 50_000_000, "homeless_head": True, "children": 1,
                                                      "payment_kinds": {"신한카드": "debit"}})
    assert r.status_code == 200
    body = r.json()
    assert body["gross"] == 50_000_000 and not body["gross_assumed"] and body["profile"]["children"] == 1
    assert client.get("/api/settings").json()["tax_profile"]["payment_kinds"] == {"신한카드": "debit"}
    assert client.put("/api/spending/tax-profile", json={"payment_kinds": {"x": "cash"}}).status_code == 422
    assert client.put("/api/spending/tax-profile", json={"gross_salary": -1}).status_code == 422


def test_salary_calculator_splits_taxfree(client):
    """총급여 = 받은 돈 − 비과세. 식대·보육은 한도까지만, 민간 복지포인트는 과세."""
    body = {"base_monthly": 4_000_000, "meal_monthly": 300_000, "car_monthly": 200_000, "childcare_monthly": 300_000, "young_children": 1,
            "bonus": 5_000_000, "retro_pay": 1_200_000, "settlement": 2_000_000, "welfare_points": 1_000_000, "other_taxable": 500_000, "other_taxfree": 1_000_000}
    r = client.post("/api/spending/salary", json=body).json()
    by = {x["key"]: x for x in r["lines"]}
    assert (by["meal"]["income"], by["meal"]["taxfree"], by["meal"]["taxable"]) == (3_600_000, 2_400_000, 1_200_000)
    assert by["childcare"]["taxfree"] == 2_400_000 and by["car"]["taxable"] == 0
    assert by["welfare"]["taxfree"] == 0 and by["settlement"]["taxable"] == 2_000_000
    assert (r["income"], r["taxfree"], r["gross_salary"]) == (68_300_000, 8_200_000, 60_100_000)
    assert "other_taxfree" in by and by["base"]["taxable"] == 48_000_000
    public = client.post("/api/spending/salary", json={**body, "welfare_public": True, "meal_provided": True}).json()
    by2 = {x["key"]: x for x in public["lines"]}
    assert by2["welfare"]["taxfree"] == 1_000_000 and by2["meal"]["taxfree"] == 0      # 공무원 복지점수는 비과세, 식사를 제공받으면 식대는 과세
    two = client.post("/api/spending/salary", json={"childcare_monthly": 500_000, "young_children": 2}).json()
    assert two["lines"][0]["taxfree"] == 4_800_000                                     # 자녀 1명당 월 20만 원
    none = client.post("/api/spending/salary", json={"childcare_monthly": 300_000}).json()
    assert none["lines"][0]["taxfree"] == 0 and "자녀 수" in none["lines"][0]["note"]
    half = client.post("/api/spending/salary", json={"months": 6, "base_monthly": 3_000_000, "meal_monthly": 200_000}).json()
    assert half["gross_salary"] == 18_000_000                                          # 근무 개월만큼
    assert client.post("/api/spending/salary", json={}).json() == {"lines": [], "income": 0, "taxfree": 0, "gross_salary": 0}
    assert client.post("/api/spending/salary", json={"bonus": -1}).status_code == 422
    assert client.post("/api/spending/salary", json={"months": 13}).status_code == 422


def test_salary_parts_are_kept_with_the_profile(client):
    parts = {"base_monthly": 4_000_000, "bonus": 5_000_000}
    r = client.put("/api/spending/tax-profile", json={"gross_salary": 53_000_000, "salary_parts": parts})
    assert r.status_code == 200 and r.json()["gross"] == 53_000_000
    saved = client.get("/api/settings").json()["tax_profile"]["salary_parts"]
    assert saved["base_monthly"] == 4_000_000 and saved["months"] == 12                # 다시 열면 그대로
