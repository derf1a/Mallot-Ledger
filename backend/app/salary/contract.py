"""연봉 기준 — 연봉 구성(소비 분석 > 절세의 총급여 계산기와 같은 값, settings tax_profile.salary_parts)으로 달마다 명세서 초안을 만든다.

- 한 달 몫: 계산기의 매달 받는 돈(기본급 · 식대 · 자가운전보조금 · 보육수당)을 과세 · 비과세로 나눈다 (tax_rules.salary_lines, 1달).
- 4대보험: 과세 몫에 2026 요율 (rules.expected) — 실제는 신고한 보수월액 기준이라 조금 다를 수 있다.
- 실수령: 가계부에 그달 정기 급여 입금(가장 자주 들어온 이름, 예: '정기급여')이 있으면 그 금액. 지급 − 4대보험 − 실수령 = 세금 + 다른 공제.
  실제 명세서(이미지 · 직접)가 하나라도 있으면 그 달의 다른 공제를 그대로 쓰고 나머지를 세금으로, 없으면 세금은 추정값으로 두고 남는 몫을
  기타 공제(노조비 · 사우회 등 또는 세금 차이)로 둔다 — 모두 세금으로 보면 원천징수가 부풀어 연말정산 환급이 크게 나온다.
  입금이 연봉 기준과 너무 다르면(상여 · 연말정산 환급이 섞인 달) 거꾸로 내지 않고 추정 세금을 쓴다.
- 입금이 없으면 세금은 '한 달 몫 × 12' 의 결정세액 ÷ 12 (간이세액표 대신 대략값).
- 저장한 줄은 source='estimate' — 실제 명세서로 고치면(이미지 · 직접) 검산이 붙는다. 이미 정기 급여 명세서가 있는 달은 건드리지 않는다.
- 정기 급여가 아닌 큰 입금(소급분 · 일시금 · 상여)은 따로 알려 준다 — 화면에서 상여 · 소급으로 더한다.
"""

import json
import sqlite3
from collections import Counter
from datetime import date

from app.insights import tax_rules as T
from app.ledger.settings import get_settings, loan_counterparty
from app.salary import rules as R

PROFILE_KEY = "tax_profile"   # insights.tax.PROFILE_KEY 와 같다
REGULAR_MIN = 1_000_000       # 정기 급여 입금으로 볼 최소 금액
REGULAR_MONTHS = 3            # 이만큼 다른 달에 같은 이름으로 들어와야 정기 급여로 본다
OTHER_MIN = 500_000           # 따로 알려 줄 큰 입금
TAX_SANE = (0.0, 0.35)        # 거꾸로 낸 세금이 과세 몫의 이 비율 안이어야 믿는다


def profile(conn: sqlite3.Connection) -> dict:
    raw = get_settings(conn).get(PROFILE_KEY)
    return raw if isinstance(raw, dict) else {}


def parts(conn: sqlite3.Connection) -> dict | None:
    p = profile(conn).get("salary_parts")
    return p if isinstance(p, dict) and p.get("base_monthly") else None


def save_parts(conn: sqlite3.Connection, salary_parts: dict) -> dict:
    """연봉 구성을 저장하고 총급여도 같이 맞춘다 (절세 계산이 같은 값을 쓴다)."""
    lines = T.salary_lines(salary_parts)
    p = {**profile(conn), "salary_parts": salary_parts, "gross_salary": lines["gross_salary"]}
    conn.execute("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                 (PROFILE_KEY, json.dumps(p, ensure_ascii=False)))
    conn.commit()
    return view(conn)


def monthly(p: dict) -> dict:
    """연봉 구성 → 한 달 정기 급여 (과세 · 비과세)."""
    one = {**p, "months": 1, "bonus": 0, "retro_pay": 0, "settlement": 0, "welfare_points": 0, "other_taxable": 0, "other_taxfree": 0}
    lines = T.salary_lines(one)
    return {"taxable": lines["gross_salary"], "nontaxable": lines["taxfree"], "lines": lines["lines"]}


def withholding(taxable_month: int, social_month: int) -> tuple[int, int]:
    """입금이 없는 달의 세금 — 한 달 몫 × 12 의 결정세액 ÷ 12 (소득세, 지방세)."""
    year = taxable_month * 12
    decided = T.income_tax(year, social_month * 12 - round(year * T.SOCIAL_RATE), T.STANDARD_CREDIT)["decided"]
    income = int(decided / 12 // 10 * 10)
    return income, int(income * R.LOCAL_OF_INCOME // 10 * 10)


def _regular_name(conn: sqlite3.Connection, year: int) -> str | None:
    rows = conn.execute("SELECT merchant, COUNT(DISTINCT substr(occurred_on, 1, 7)) m FROM transactions WHERE type = 'income' "
                        "AND amount >= ? AND occurred_on LIKE ? AND merchant != '' GROUP BY merchant ORDER BY m DESC, COUNT(*) DESC",
                        (REGULAR_MIN, f"{year}-%")).fetchall()
    return rows[0]["merchant"] if rows and rows[0]["m"] >= REGULAR_MONTHS else None


def plan(conn: sqlite3.Connection, year: int, today: date | None = None) -> dict:
    """명세서가 없는 달의 초안 (저장 안 함)."""
    today = today or date.today()
    p = parts(conn)
    out = {"year": year, "parts": p, "regular_name": None, "drafts": [], "others": [], "skipped": [], "note": None}
    if not p:
        out["note"] = "연봉 구성이 없어요 — 연봉 기준 카드에서 먼저 넣어 주세요"
        return out
    m = monthly(p)
    taxable, nontaxable = m["taxable"], m["nontaxable"]
    social = R.expected(taxable)
    social_sum = sum(social[k] for k in R.SOCIAL)
    gross = taxable + nontaxable
    est_income, est_local = withholding(taxable, social_sum)
    name = _regular_name(conn, year)
    out["regular_name"] = name
    have = {r[0] for r in conn.execute("SELECT pay_month FROM salary_slips WHERE kind = 'regular' AND pay_month LIKE ?", (f"{year}-%",))}
    # 실제(이미지 · 직접) 정기 급여 명세서가 있으면 그 '다른 공제'로 맞춘다 — 세금과 노조비 등을 가를 근거
    real = conn.execute("SELECT pay_month, other_deductions FROM salary_slips WHERE kind = 'regular' AND source != 'estimate' "
                        "ORDER BY pay_month DESC LIMIT 1").fetchone()
    calib, calib_month = (real["other_deductions"], real["pay_month"]) if real else (None, None)
    out["calibrated_by"] = calib_month
    last = today.month if year == today.year else 12
    used: set[int] = set()
    for mo in range(1, last + 1):
        month = f"{year}-{mo:02d}"
        if month in have:
            out["skipped"].append(month)
            continue
        dep = None
        if name:
            dep = conn.execute("SELECT id, occurred_on, amount FROM transactions WHERE type = 'income' AND merchant = ? "
                               "AND occurred_on LIKE ? ORDER BY amount DESC LIMIT 1", (name, f"{month}-%")).fetchone()
        draft = {"pay_month": month, "paid_on": None, "kind": "regular", "employer": "", "taxable_pay": taxable,
                 "nontaxable_pay": nontaxable, **{k: social[k] for k in R.SOCIAL}, "income_tax": est_income,
                 "local_income_tax": est_local, "other_deductions": 0, "net_pay": None, "items": [], "source": "estimate",
                 "basis": "추정 세금 (입금 없음)", "deposit": None}
        if dep:
            used.add(dep["id"])
            implied = gross - social_sum - dep["amount"]   # 세금 + 다른 공제
            draft.update(paid_on=dep["occurred_on"], deposit=dep["amount"])
            if TAX_SANE[0] * taxable <= implied <= TAX_SANE[1] * taxable:
                if calib is not None:   # 실제 명세서의 다른 공제를 그대로 — 나머지가 세금
                    other = min(calib, implied)
                    why = f"입금 {dep['amount']:,}원 − 실제 명세서({calib_month})의 다른 공제 {other:,}원 → 나머지가 세금"
                else:                   # 세금은 추정, 남는 몫은 다른 공제(노조비 · 사우회 등)로
                    tax_part = min(implied, est_income + est_local)
                    other = implied - tax_part
                    why = (f"입금 {dep['amount']:,}원 · 세금은 추정, 남는 {other:,}원은 기타 공제(노조비 · 사우회 등 또는 세금 차이)"
                           if other else f"입금 {dep['amount']:,}원으로 세금을 거꾸로 냄")
                taxes = implied - other
                income = int(taxes / (1 + R.LOCAL_OF_INCOME) // 10 * 10)
                draft.update(income_tax=income, local_income_tax=taxes - income, other_deductions=other, net_pay=dep["amount"],
                             basis=why)
            else:
                draft["basis"] = (f"입금 {dep['amount']:,}원이 연봉 기준 실수령 {gross - social_sum - est_income - est_local:,}원과 많이 달라요 "
                                  "— 상여 · 연말정산 환급 등이 섞였을 수 있어 추정 세금을 썼어요")
        draft["memo"] = f"연봉 기준 · {draft['basis']}"
        draft["net"] = draft["net_pay"] if draft["net_pay"] is not None else gross - social_sum - draft["income_tax"] - draft["local_income_tax"]
        out["drafts"].append(draft)
    # 정기 급여가 아닌 큰 입금 — 상여 · 소급 · 일시금 후보 (빌린 돈 · 대출은 뺀다)
    for r in conn.execute("SELECT id, occurred_on, merchant, amount FROM transactions WHERE type = 'income' AND amount >= ? "
                          "AND occurred_on LIKE ? ORDER BY occurred_on", (OTHER_MIN, f"{year}-%")):
        if r["id"] in used or r["merchant"] == name or "대출" in r["merchant"] or loan_counterparty(conn, r["merchant"]):
            continue
        guess = "retro" if "소급" in r["merchant"] else "bonus" if any(w in r["merchant"] for w in ("상여", "성과", "보너스", "인센")) else "other"
        out["others"].append({**dict(r), "kind": guess})
    return out


def view(conn: sqlite3.Connection) -> dict:
    p = parts(conn)
    out = {"parts": p, "gross_salary": profile(conn).get("gross_salary") or 0, "monthly": None, "lines": None}
    if p:
        m = monthly(p)
        social = R.expected(m["taxable"])
        s = sum(social[k] for k in R.SOCIAL)
        inc, loc = withholding(m["taxable"], s)
        out.update(monthly={"taxable": m["taxable"], "nontaxable": m["nontaxable"], "social": s, "income_tax": inc, "local_income_tax": loc,
                            "net": m["taxable"] + m["nontaxable"] - s - inc - loc},
                   lines=T.salary_lines(p))
    return out
