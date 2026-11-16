"""절세 분석의 세법 숫자와 계산식 — 2026년 귀속(2026.1.1 시행 법률) 기준. 숫자는 코드가 계산하고 LLM 은 결과만 받는다.

조문 원문으로 확인한 것 (casenote.kr, 2026-10-29):
- 근로소득공제 소득세법 47조 · 기본세율 55조 · 근로소득세액공제 59조 · 본인 기본공제 150만 원
- 신용카드 등 사용금액 소득공제 조세특례제한법 126조의2 (2025.12.23 개정, 2028.12.31 사용분까지)
- 주택청약종합저축 소득공제 조특법 87조②(2028.12.31 납입분까지) · 주택임차차입금 원리금 상환액 공제 소득세법 52조④(청약 공제와 합산 400만 원)
- 연금계좌세액공제 소득세법 59조의3 · 보장성 보험료 세액공제·표준세액공제 59조의4 · ISA 조특법 91조의18
- 총급여의 비과세 식사대·보육 급여 소득세법 12조 3호 러목·머목 (원문, 2026-11-03)
2차 자료로만 확인한 것: 자가운전보조금 월 20만 원(시행령 12조) · 소급 임금의 귀속(시행령 49조: 급여는 근로를 제공한 날) · 민간 복지포인트 과세(2026-06 헌재 합헌 보도)
세법은 해마다 바뀐다 — 올해가 RULES_YEAR 와 다르면 tax.py 가 그 사실을 남긴다. 4대보험·부양가족은 단순 가정(SOCIAL_RATE)이라
결정세액은 '대략'이고, 항목별 효과는 같은 가정으로 '그 항목이 있을 때와 없을 때'의 차이를 잰다.
"""

RULES_YEAR = 2026
LOCAL_TAX = 0.10           # 지방소득세 = 소득세의 10%
BASIC_DEDUCTION = 1_500_000  # 본인 기본공제
SOCIAL_RATE = 0.097        # 4대보험 근로자 부담 대략(국민연금 4.75% + 건강 3.595% + 장기요양 + 고용 0.9%) — 과세표준 추정용
STANDARD_CREDIT = 130_000  # 표준세액공제: 특별소득공제·특별세액공제·월세세액공제를 신청하지 않을 때만

# 근로소득공제 (구간 하한, 그 하한까지의 공제액, 초과분 공제율), 한도 2천만 원
EARNED_DEDUCTION = ((0, 0, 0.70), (5_000_000, 3_500_000, 0.40), (15_000_000, 7_500_000, 0.15),
                    (45_000_000, 12_000_000, 0.05), (100_000_000, 14_750_000, 0.02))
EARNED_DEDUCTION_CAP = 20_000_000
# 기본세율 (과세표준 상한, 세율) — 마지막은 상한 없음
BRACKETS = ((14_000_000, 0.06), (50_000_000, 0.15), (88_000_000, 0.24), (150_000_000, 0.35),
            (300_000_000, 0.38), (500_000_000, 0.40), (1_000_000_000, 0.42), (None, 0.45))

# 신용카드 등 (조특법 126조의2): 최저사용금액 = 총급여 25%, 그 위로 수단별 공제율
CARD_MIN_SHARE = 0.25
CARD_RATES = {"credit": 0.15, "debit": 0.30, "culture": 0.30, "transit": 0.40, "market": 0.40}
CARD_ORDER = ("credit", "debit", "culture", "transit", "market")  # 최저사용금액을 먼저 채우는 순서 (낮은 공제율부터)
CARD_HIGH_EARNER = 70_000_000  # 이 총급여를 넘으면 한도가 낮고, 도서·공연·체육시설(문화) 30% 가 따로 없다
CARD_LIMIT = {False: (3_000_000, 3_500_000, 4_000_000), True: (2_500_000, 2_750_000, 3_000_000)}  # 자녀 0·1·2명 이상
CARD_EXTRA_LIMIT = {False: 3_000_000, True: 2_000_000}  # 기본 한도를 넘는 몫: 전통시장·대중교통(·문화) 공제액까지

# 주택자금 (조특법 87조② · 소득세법 52조④)
HOUSING_SAVING_LIMIT = 3_000_000   # 청약 납입 인정 한도 (연)
HOUSING_SAVING_MAX_SALARY = 70_000_000
HOUSING_RATE = 0.40                # 청약 납입액·전세대출 원리금 상환액의 40%
HOUSING_COMBINED_LIMIT = 4_000_000  # 청약 공제 + 주택임차차입금 공제 합계

# 연금계좌 (소득세법 59조의3): 연금저축 600만 원, IRP 와 합쳐 900만 원. 총급여 5,500만 원 이하 15%, 넘으면 12%
PENSION_SAVINGS_LIMIT = 6_000_000
PENSION_TOTAL_LIMIT = 9_000_000
PENSION_HIGH_RATE_SALARY = 55_000_000
PENSION_RATES = (0.15, 0.12)
ISA_PENSION_EXTRA = (0.10, 3_000_000)  # ISA 만기 자금을 연금계좌로 옮기면 전환액의 10%(최대 300만 원)만큼 한도가 늘어난다

# 보장성 보험료 (소득세법 59조의4①): 12%, 연 100만 원까지
INSURANCE_RATE = 0.12
INSURANCE_LIMIT = 1_000_000

# ISA (조특법 91조의18): 비과세 한도 — 직전 연도 총급여 5천만 원 이하 400만 원, 그 밖 200만 원. 연 납입 2천만 원
ISA_TAX_FREE = (4_000_000, 2_000_000)
ISA_LOW_SALARY = 50_000_000
ISA_YEARLY = 20_000_000


# 총급여 = 한 해 근로소득 − 비과세 (소득세법 12조 3호)
MEAL_TAX_FREE = 200_000       # 식사대 월 20만 원 — 식사를 제공받지 않을 때만
CAR_TAX_FREE = 200_000        # 자가운전보조금 월 20만 원 — 본인 차량을 업무에 쓸 때
CHILDCARE_TAX_FREE = 200_000  # 6세 이하 자녀 1명당 월 20만 원


def salary_lines(p: dict) -> dict:
    """총급여 계산 — 받은 돈을 항목별로 비과세와 나눈다. p 는 api.SalaryIn 값. 민간 복지포인트는 과세, 공무원 복지점수는 비과세로 취급한다."""
    months = p["months"]

    def monthly(key: str, label: str, amount: int, free: int, note: str = "") -> dict:
        return {"key": key, "label": label, "income": amount * months, "taxfree": min(amount, free) * months, "note": note}

    def yearly(key: str, label: str, amount: int, taxfree: bool = False, note: str = "") -> dict:
        return {"key": key, "label": label, "income": amount, "taxfree": amount if taxfree else 0, "note": note}

    children = p["young_children"]
    lines = [
        monthly("base", "월정액 급여", p["base_monthly"], 0),
        monthly("meal", "식대", p["meal_monthly"], 0 if p["meal_provided"] else MEAL_TAX_FREE,
                "회사 식사를 제공받아 비과세 없음" if p["meal_provided"] else f"월 {MEAL_TAX_FREE // 10_000}만 원까지 비과세"),
        monthly("car", "자가운전보조금", p["car_monthly"], CAR_TAX_FREE, f"본인 차량 업무 사용 시 월 {CAR_TAX_FREE // 10_000}만 원까지"),
        monthly("childcare", "보육수당", p["childcare_monthly"], CHILDCARE_TAX_FREE * children,
                f"6세 이하 자녀 1명당 월 {CHILDCARE_TAX_FREE // 10_000}만 원까지" + ("" if children else " — 자녀 수를 넣어 주세요")),
        yearly("bonus", "상여금", p["bonus"]),
        yearly("retro_pay", "임금협상 소급분", p["retro_pay"], note="올해 일한 몫만 — 지난해 일한 몫은 지난해 소득"),
        yearly("settlement", "임금협상 일시금", p["settlement"], note="타결금·격려금 — 합의서가 지난해 임금 차액이면 지난해 소득일 수 있어요"),
        yearly("welfare", "복지포인트", p["welfare_points"], p["welfare_public"], "공무원 복지점수로 비과세" if p["welfare_public"] else "민간 기업은 근로소득으로 과세"),
        yearly("other_taxable", "기타 과세 수당", p["other_taxable"], note="연차수당·초과근무·명절 상여 등"),
        yearly("other_taxfree", "기타 비과세", p["other_taxfree"], True, "출산지원금 등 직접 확인한 비과세"),
    ]
    lines = [{**x, "taxable": x["income"] - x["taxfree"]} for x in lines if x["income"]]
    income, taxfree = sum(x["income"] for x in lines), sum(x["taxfree"] for x in lines)
    return {"lines": lines, "income": income, "taxfree": taxfree, "gross_salary": income - taxfree}


def earned_income_deduction(gross: int) -> int:
    lower, base, rate = next(s for s in reversed(EARNED_DEDUCTION) if gross > s[0] or s[0] == 0)
    return round(min(EARNED_DEDUCTION_CAP, base + (gross - lower) * rate))


def bracket_tax(taxable: int) -> tuple[int, float]:
    """기본세율 산출세액과 한계세율."""
    tax, lower = 0.0, 0
    for upper, rate in BRACKETS:
        if upper is None or taxable <= upper:
            return round(tax + (taxable - lower) * rate), rate
        tax += (upper - lower) * rate
        lower = upper
    raise AssertionError("unreachable")


def earned_tax_credit(calculated: int, gross: int) -> int:
    credit = calculated * 0.55 if calculated <= 1_300_000 else 715_000 + (calculated - 1_300_000) * 0.30
    if gross <= 33_000_000:
        cap = 740_000
    elif gross <= 70_000_000:
        cap = max(660_000, 740_000 - (gross - 33_000_000) * 0.008)
    elif gross <= 120_000_000:
        cap = max(500_000, 660_000 - (gross - 70_000_000) / 2)
    else:
        cap = max(200_000, 500_000 - (gross - 120_000_000) / 2)
    return round(min(credit, cap))


def income_tax(gross: int, deductions: int = 0, credits: int = 0) -> dict:
    """근로소득만 있는 사람의 결정세액 추정. deductions = 근로소득금액에서 빼는 소득공제, credits = 세액공제(소득세 기준).
    total 은 지방소득세까지 더한 금액."""
    earned = gross - earned_income_deduction(gross)
    taxable = max(0, earned - BASIC_DEDUCTION - round(gross * SOCIAL_RATE) - deductions)
    calculated, marginal = bracket_tax(taxable)
    earned_credit = earned_tax_credit(calculated, gross)
    decided = max(0, calculated - earned_credit - credits)
    return {"taxable": taxable, "calculated": calculated, "earned_credit": earned_credit, "decided": decided,
            "total": round(decided * (1 + LOCAL_TAX)), "marginal": marginal}


def card_deduction(gross: int, used: dict[str, int], children: int = 0) -> dict:
    """신용카드 등 사용금액 소득공제. used: credit·debit·culture·transit·market 사용액(원).
    최저사용금액(총급여 25%)은 공제율이 낮은 사용분부터 채운다(신용카드 → 체크 등 → 문화 → 대중교통·전통시장)."""
    high = gross > CARD_HIGH_EARNER
    amounts = {k: max(0, int(used.get(k, 0))) for k in CARD_ORDER}
    if high:  # 총급여 7천만 원 초과: 문화 사용분은 따로 없다 — 결제 수단(대부분 신용카드) 몫으로 본다
        amounts["credit"] += amounts["culture"]
        amounts["culture"] = 0
    threshold = round(gross * CARD_MIN_SHARE)
    total = sum(amounts.values())
    left = threshold
    part: dict[str, float] = {}
    for k in CARD_ORDER:
        covered = min(left, amounts[k])
        left -= covered
        part[k] = (amounts[k] - covered) * CARD_RATES[k]
    raw = round(sum(part.values()))
    limit = CARD_LIMIT[high][min(max(children, 0), 2)]
    special = round(part["transit"] + part["market"] + part["culture"])
    extra = min(max(0, raw - limit), special, CARD_EXTRA_LIMIT[high])
    return {"threshold": threshold, "total": total, "over": max(0, total - threshold), "raw": raw, "limit": limit,
            "extra": extra, "deduction": min(raw, limit) + extra, "amounts": amounts}


def pension_credit_rate(gross: int) -> float:
    return PENSION_RATES[0] if gross <= PENSION_HIGH_RATE_SALARY else PENSION_RATES[1]


def pension_credit(gross: int, savings: int, irp: int) -> tuple[int, int]:
    """(공제 대상 납입액, 세액공제액 — 소득세 기준)."""
    base = min(PENSION_TOTAL_LIMIT, min(savings, PENSION_SAVINGS_LIMIT) + irp)
    return base, round(base * pension_credit_rate(gross))


def housing_deductions(saving_paid: int, rent_loan_paid: int, saving_ok: bool, rent_ok: bool) -> tuple[int, int]:
    """(청약 소득공제, 주택임차차입금 소득공제) — 둘의 합은 400만 원까지(넘는 몫은 전세대출 쪽에서 깎는다)."""
    saving = round(min(saving_paid, HOUSING_SAVING_LIMIT) * HOUSING_RATE) if saving_ok else 0
    rent = round(rent_loan_paid * HOUSING_RATE) if rent_ok else 0
    return saving, max(0, min(rent, HOUSING_COMBINED_LIMIT - saving))


def insurance_credit(paid: int) -> int:
    return round(min(paid, INSURANCE_LIMIT) * INSURANCE_RATE)
