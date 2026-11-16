"""급여 분석 — 급여명세서 기록에서 숫자를 코드로 꺼낸다 (LLM 없음).

- 명세서 한 장: 지급 합계(과세 + 비과세) · 공제 합계 · 실지급액(명세서 값, 없으면 지급 − 공제)과 계산이 어긋나는지, 실수령 비율,
  4대보험 · 지방소득세 검산(정기 급여만 — rules.py 의 2026 요율), 가계부 입금(지급일 ±3일 · 같은 금액 수입)이 있는지.
- 올해: 달마다 흐름, 항목별 합계, 실효 세율(소득세 + 지방세 ÷ 지급 합계) · 4대보험 비율, 지난달 대비 정기 급여 변화.
- 연말 추정: 총급여 = 올해 과세 지급액 + (기록 없는 달 — 앞 · 사이 빈 달과 남은 달) × 최근 정기 급여 평균(상여는 잇지 않음).
  원천징수 · 4대보험도 같은 방식으로 잇는다. 기록을 올해 중간부터 시작했으면 앞 달을 채웠다고 적는다(입사 · 휴직이면 실제보다 큼).
  결정세액은 소비 분석의 절세 계산(insights.tax — 카드 · 연금저축 · 청약 등 가계부로 추정한 공제 포함)을 쓰고, 그게 안 되면
  기본 공제만으로 계산한다. 원천징수 − 결정세액 = 연말정산 환급(+) · 추가 납부(−) 추정.
"""

import json
import sqlite3
from datetime import date, timedelta

from app.insights import tax_rules as T
from app.salary import rules as R

MATCH_DAYS = 3
COLS = ("id", "pay_month", "paid_on", "kind", "employer", "taxable_pay", "nontaxable_pay", *R.DEDUCTIONS, "net_pay", "items_json",
        "memo", "source", "created_at")
KIND_KO = {"regular": "정기 급여", "bonus": "상여", "retro": "소급분", "other": "기타"}


def slips(conn: sqlite3.Connection, year: int | None = None) -> list[dict]:
    where, args = ("WHERE pay_month LIKE ?", (f"{year}-%",)) if year else ("", ())
    rows = conn.execute(f"SELECT {', '.join(COLS)} FROM salary_slips {where} ORDER BY pay_month, paid_on, id", args).fetchall()
    return [_row(r) for r in rows]


def get_slip(conn: sqlite3.Connection, slip_id: int) -> dict | None:
    r = conn.execute(f"SELECT {', '.join(COLS)} FROM salary_slips WHERE id = ?", (slip_id,)).fetchone()
    return _row(r) if r else None


def _row(r: sqlite3.Row) -> dict:
    d = dict(r)
    d["items"] = json.loads(d.pop("items_json") or "[]")
    return d


def _deposit(conn: sqlite3.Connection, s: dict, net: int) -> dict | None:
    """지급일 ±3일 안의 같은 금액 수입 거래."""
    if not s.get("paid_on") or net <= 0:
        return None
    day = date.fromisoformat(s["paid_on"])
    r = conn.execute("SELECT id, occurred_on, merchant FROM transactions WHERE type = 'income' AND amount = ? "
                     "AND occurred_on BETWEEN ? AND ? ORDER BY ABS(julianday(occurred_on) - julianday(?)) LIMIT 1",
                     (net, (day - timedelta(days=MATCH_DAYS)).isoformat(), (day + timedelta(days=MATCH_DAYS)).isoformat(),
                      s["paid_on"])).fetchone()
    return dict(r) if r else None


def view(conn: sqlite3.Connection, s: dict) -> dict:
    """명세서 한 장 + 계산한 값과 검산."""
    gross = s["taxable_pay"] + s["nontaxable_pay"]
    social = sum(s[k] for k in R.SOCIAL)
    taxes = sum(s[k] for k in R.TAXES)
    deductions = social + taxes + s["other_deductions"]
    computed_net = gross - deductions
    net = s["net_pay"] if s["net_pay"] is not None else computed_net
    checks = []
    if s["net_pay"] is not None and s["net_pay"] != computed_net:
        checks.append({"key": "net", "ok": False, "text": f"실지급액 {s['net_pay']:,}원 ≠ 지급 {gross:,} − 공제 {deductions:,} = {computed_net:,}원 "
                                                         "— 빠진 공제 · 지급 줄이 있는지 보세요"})
    if s["source"] == "estimate":
        checks.append({"key": "estimate", "ok": None, "text": "연봉 기준 추정 — 실제 명세서 숫자로 고치면(이미지 · 직접) 요율 검산을 해요"})
    elif s["kind"] == "regular" and s["taxable_pay"] > 0:
        want = R.expected(s["taxable_pay"], s["health_insurance"] or None, s["income_tax"])
        for key, w in want.items():
            got = s[key]
            if not got and key != "local_income_tax":
                checks.append({"key": key, "ok": None, "text": f"{R.LABELS[key]} 공제가 없어요 (계산 {w:,}원) — 가입 대상이 아니거나 빠졌어요"})
                continue
            ok = R.close(got, w)
            why = ""
            if not ok and key == "national_pension" and got < w:
                why = " — 기준소득월액 상한을 넘는 월급이면 이보다 적게 내는 게 맞아요"
            elif not ok and key in ("national_pension", "health_insurance", "long_term_care"):
                why = " — 보험료는 신고한 보수월액(보통 지난해 소득) 기준이라 월급이 바뀐 해에는 어긋나요"
            checks.append({"key": key, "ok": ok, "expected": w, "actual": got,
                           "text": f"{R.LABELS[key]} {got:,}원 · 계산 {w:,}원" + ("" if ok else why)})
    dep = _deposit(conn, s, net)
    return {**s, "kind_ko": KIND_KO.get(s["kind"], s["kind"]), "gross_pay": gross, "social": social, "taxes": taxes,
            "deductions": deductions, "net": net, "computed_net": computed_net,
            "take_home_rate": round(net / gross, 4) if gross else None, "checks": checks, "deposit": dep,
            "deposit_note": None if dep or not s.get("paid_on") else f"가계부에 {s['paid_on']} ±{MATCH_DAYS}일 {net:,}원 입금이 없어요"}


def _sum(vs: list[dict], key: str) -> int:
    return sum(v[key] or 0 for v in vs)


def summary(conn: sqlite3.Connection, year: int, today: date | None = None, with_estimate: bool = True) -> dict:
    """with_estimate=False 는 절세 계산이 총급여만 물을 때 (서로 부르며 돌지 않게)."""
    today = today or date.today()
    views = [view(conn, s) for s in slips(conn, year)]
    out = {"year": year, "rules_year": R.RULES_YEAR, "slips": views, "notes": [], "months": [], "totals": None, "rates": None,
           "projection": None, "estimate": None, "change": None}
    if year != R.RULES_YEAR:
        out["notes"].append(f"요율 · 세법 숫자는 {R.RULES_YEAR}년 기준이에요 — {year}년 요율을 확인해야 해요")
    if not views:
        return out
    months: dict[str, dict] = {}
    for v in views:
        m = months.setdefault(v["pay_month"], {"month": v["pay_month"], "gross": 0, "taxable": 0, "net": 0, "social": 0, "taxes": 0,
                                               "regular_taxable": 0, "regular_taxes": 0})
        for k, src in (("gross", "gross_pay"), ("taxable", "taxable_pay"), ("net", "net"), ("social", "social"), ("taxes", "taxes")):
            m[k] += v[src]
        if v["kind"] == "regular":
            m["regular_taxable"] += v["taxable_pay"]
            m["regular_taxes"] += v["taxes"]
    out["months"] = list(months.values())
    totals = {k: _sum(views, k) for k in ("gross_pay", "taxable_pay", "nontaxable_pay", "net", "social", "taxes", "other_deductions", *R.DEDUCTIONS)}
    out["totals"] = totals
    g = totals["gross_pay"]
    out["rates"] = {"tax": round(totals["taxes"] / g, 4) if g else None, "social": round(totals["social"] / g, 4) if g else None,
                    "take_home": round(totals["net"] / g, 4) if g else None}
    regular = [m for m in out["months"] if m["regular_taxable"]]
    if len(regular) >= 2:
        a, b = regular[-2], regular[-1]
        diff = b["regular_taxable"] - a["regular_taxable"]
        out["change"] = {"from": a["month"], "to": b["month"], "diff": diff,
                         "rate": round(diff / a["regular_taxable"], 4) if a["regular_taxable"] else None}
    # 1년 채우기 — 정기 급여 기록이 없는 달(앞쪽 빈 달 · 사이 빈 달 · 남은 달)을 최근 정기 급여 3달 평균으로
    last = max(int(m["month"][5:7]) for m in out["months"])
    covered = {int(m["month"][5:7]) for m in regular}
    end = 12 if year <= today.year else last
    rest = max(0, 12 - last) if year == today.year else 0
    missing_before = sorted(m for m in range(1, last + 1) if m not in covered)
    filled = len(missing_before) + rest if year <= today.year else 0
    recent = regular[-3:]
    avg_taxable = round(sum(m["regular_taxable"] for m in recent) / len(recent)) if recent else 0
    avg_taxes = round(sum(m["regular_taxes"] for m in recent) / len(recent)) if recent else 0
    avg_social = round(sum(m["social"] for m in recent) / len(recent)) if recent else 0
    gross_year = totals["taxable_pay"] + avg_taxable * filled
    withheld = totals["taxes"] + avg_taxes * filled
    social_year = totals["social"] + avg_social * filled
    notes = []
    # 연봉 구성(계산기)에 있는 상여 · 소급 · 일시금 · 복지포인트 · 기타 과세 중 아직 기록하지 않은 몫 — 세금은 정기 급여의 실효 세율로
    extras_planned = _contract_extras(conn)
    extras_recorded = sum(v["taxable_pay"] for v in views if v["kind"] != "regular")
    extras_add = max(0, extras_planned - extras_recorded) if year <= today.year else 0
    if extras_add:
        rate = avg_taxes / avg_taxable if avg_taxable else 0
        gross_year += extras_add
        withheld += round(extras_add * rate)
        notes.append(f"연봉 구성의 상여 · 일시금 등 중 아직 기록하지 않은 {extras_add:,}원을 더했어요 (세금은 정기 급여 세율 {rate:.1%})")
    if missing_before:
        notes.append(f"정기 급여 기록이 없는 {len(missing_before)}달({', '.join(f'{m}월' for m in missing_before)})도 최근 평균으로 채웠어요 — "
                     "그 달에 일하지 않았다면(올해 입사 · 휴직) 총급여 · 원천징수가 실제보다 커요")
    if any(v["kind"] != "regular" for v in views) and not extras_planned:
        notes.append("상여 · 소급분은 기록한 것만 넣고 잇지 않았어요")
    out["projection"] = {"through": f"{year}-{last:02d}", "rest_months": rest, "filled_before": len(missing_before),
                         "filled_months": filled, "covered_months": len(covered), "months_in_year": end,
                         "avg_regular_taxable": avg_taxable, "extras_added": extras_add, "gross_salary": gross_year, "withheld": withheld, "social": social_year,
                         "note": " · ".join(notes) or None}
    if with_estimate:
        out["estimate"] = estimate(conn, gross_year, withheld, social_year, today)
    return out


def _contract_extras(conn: sqlite3.Connection) -> int:
    """연봉 구성의 한 해 몫 과세 금액(상여 · 소급 · 일시금 · 복지포인트 · 기타 과세). 없으면 0."""
    from app.salary import contract  # 늦게 — contract 가 tax_rules 를 쓴다

    p = contract.parts(conn)
    if not p:
        return 0
    lines = contract.T.salary_lines(p)["lines"]
    return sum(x["taxable"] for x in lines if x["key"] in ("bonus", "retro_pay", "settlement", "welfare", "other_taxable"))


def projected_gross(conn: sqlite3.Connection, year: int, today: date | None = None) -> int:
    """절세 계산(insights.tax)이 총급여를 정할 때 쓴다 — 급여 기록이 없으면 0."""
    s = summary(conn, year, today, with_estimate=False)
    return (s["projection"] or {}).get("gross_salary") or 0


def estimate(conn: sqlite3.Connection, gross: int, withheld: int, social: int, today: date) -> dict:
    """연말정산 추정 — 결정세액(지방세 포함)과 원천징수의 차이."""
    basis = "basic"
    decided = None
    try:
        from app.insights import tax  # 늦게 — 절세 계산은 가계부 전체를 읽어 무겁다

        t = tax.compute(conn, today)
        # 절세 계산의 총급여가 급여 기록으로 이은 값이거나, 직접 넣은 총급여(연봉 구성)와 5% 안이면 그 결정세액을 쓴다
        close = t.get("gross") and abs(t["gross"] - gross) <= 0.05 * max(gross, 1)
        if t.get("available") and t.get("summary") and (t.get("gross_source") == "salary" or close):
            decided, basis = t["summary"]["tax_now"], "ledger"
    except Exception:  # noqa: BLE001 — 절세 계산이 안 돼도 기본 추정은 낸다
        decided = None
    if decided is None:
        # 기본 공제만: 4대보험은 실제 낸 값으로 (income_tax 는 총급여 × SOCIAL_RATE 를 가정하므로 그 차이를 더 공제한다)
        decided = T.income_tax(gross, social - round(gross * T.SOCIAL_RATE), T.STANDARD_CREDIT)["total"]
    diff = withheld - decided
    return {"gross_salary": gross, "decided": decided, "withheld": withheld, "refund": diff, "basis": basis,
            "basis_ko": "가계부로 추정한 공제(카드 · 연금저축 · 청약 등) 포함" if basis == "ledger" else "기본 공제(본인 · 4대보험 · 표준세액공제)만",
            "text": (f"연말정산에서 약 {diff:,}원 돌려받을 것 같아요" if diff > 0 else
                     f"연말정산에서 약 {-diff:,}원 더 낼 것 같아요" if diff < 0 else "원천징수와 결정세액이 거의 같아요")}
