"""급여명세서 검산에 쓰는 2026년 근로자 부담 요율 — 숫자는 코드가 계산하고 LLM 은 쓰지 않는다.

- 국민연금 4.75% (연금개혁: 2026년 9.5%를 근로자 · 사업주 반씩, 2033년 13%까지 해마다 0.5%p)
- 건강보험 3.595% (7.19%의 절반) · 장기요양 = 건강보험료 × 13.14% · 고용보험 0.9% (실업급여, 동결)
- 지방소득세(근로소득 원천징수분) = 소득세 × 10%
확인: 요율표 정리 글 여러 곳(2026-11-16). 국민연금 기준소득월액 상한 · 하한은 해마다 7월에 바뀌고 이 앱에 숫자로 넣지 않았다 —
상한을 넘는 월급이면 국민연금이 요율 계산보다 적게 나오는 게 맞다 (check 가 그 가능성을 적는다).
4대보험은 그달 월급이 아니라 신고한 보수월액(보통 지난해 소득)으로 매긴다 → 월급이 바뀐 해에는 계산과 어긋나고, 다음 해
4월(건강보험) 정산으로 맞춰진다. 상여 · 소급분 달은 회사마다 떼는 방식이 달라 정기 급여만 검산한다.
"""

import math

RULES_YEAR = 2026
PENSION = 0.0475
HEALTH = 0.03595
CARE_OF_HEALTH = 0.1314
EMPLOYMENT = 0.009
LOCAL_OF_INCOME = 0.10
TOLERANCE = 0.05       # 계산과 5% 안이면 맞다고 본다
TOLERANCE_WON = 1_000  # 또는 1,000원 안

LABELS = {"national_pension": "국민연금", "health_insurance": "건강보험", "long_term_care": "장기요양", "employment_insurance": "고용보험",
          "income_tax": "소득세", "local_income_tax": "지방소득세", "other_deductions": "기타 공제"}
SOCIAL = ("national_pension", "health_insurance", "long_term_care", "employment_insurance")
TAXES = ("income_tax", "local_income_tax")
DEDUCTIONS = SOCIAL + TAXES + ("other_deductions",)


def _floor10(v: float) -> int:
    """보험료 · 지방소득세는 10원 미만을 버린다."""
    return int(math.floor(v / 10) * 10)


def expected(taxable: int, health_paid: int | None = None, income_tax: int | None = None) -> dict[str, int]:
    """과세 급여(비과세 뺀 월급)로 계산한 근로자 부담. 장기요양은 실제 낸 건강보험료가 있으면 그것으로 (명세서와 같은 기준)."""
    health = _floor10(taxable * HEALTH)
    out = {"national_pension": _floor10(taxable * PENSION), "health_insurance": health,
           "long_term_care": _floor10((health_paid if health_paid else health) * CARE_OF_HEALTH),
           "employment_insurance": _floor10(taxable * EMPLOYMENT)}
    if income_tax is not None:
        out["local_income_tax"] = _floor10(income_tax * LOCAL_OF_INCOME)
    return out


def close(actual: int, want: int) -> bool:
    return abs(actual - want) <= max(TOLERANCE_WON, want * TOLERANCE)
