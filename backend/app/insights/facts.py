"""소비 습관 분석의 근거 — 가계부 거래에서 코드가 계산한 번호 붙은 사실(fact) 목록과 화면용 통계.

LLM 은 이 사실만 근거로 습관을 해석한다(report.py). 숫자는 모두 여기서 계산한다.
- 분석 기간: 수입일 기준으로 끝난 기간 N개. 진행 중인 이번 기간은 '이번 기간 진행' 사실로만 본다.
- 비교 기간: 분석 기간 바로 앞 N개 기간. 데이터가 시작되기 전에 걸친 기간은 뺀다(일부만 있는 기간은 왜곡되므로).
- 변동비: 가계부 요약과 같은 정의 — 정기지출에 연결되지 않은 지출 + 타 계좌 이체 − 정산·환불.
- 일회성 큰 지출: 100만 원 이상인 지출·송금 한 건(보증금·큰 구매 등). 습관이 아니라서 따로 사실로 남기고 습관 통계·비교에서는 뺀다
  (한 건이 기간 평균을 수천만 원씩 바꿔 비교를 망가뜨리는 것을 막는다).
- 결제 습관(가맹점·요일·시간대·소액·큰 결제)은 정기지출이 아닌 지출(expense)만 본다.
- 개인정보: 이체 상대 이름은 사실에 넣지 않는다(건수·합계만). 가맹점은 정규화 키(지점명 뺀 이름)로, 숫자 8자리 이상이
  들어간 이름(계좌번호 등)은 가린다.
- 고정 지출·저금(fixed.py)은 분석 기간의 정기지출 계획 대비 실제, 절세(tax.py)는 기간과 따로 올해(귀속연도) 기준이다.
"""

import re
import sqlite3
from bisect import bisect_right
from collections import Counter, defaultdict
from datetime import date, timedelta

from app.core.periods import Period, period_for
from app.insights import fixed as fixed_costs, tax as tax_analysis
from app.insights.fmt import change, share, won
from app.ledger.settings import get_settings
from app.ledger.summary import summary as period_summary

MONTHS = (1, 3, 6, 12)
SMALL = 10_000      # 소액 결제 기준 (미만)
BIG = 100_000       # 큰 결제 기준 (이상)
ONE_OFF = 1_000_000  # 일회성 큰 지출 기준 (이상) — 습관 통계에서 뺀다
_NUMBER_LIKE = re.compile(r"\d[\d\- ]{6,}\d")
WEEKDAYS = "월화수목금토일"
# 시간대 (시작 시, 끝 시 포함) — 밤은 자정을 넘긴다
BUCKETS = (("아침", 5, 10), ("점심", 11, 14), ("오후", 15, 17), ("저녁", 18, 21), ("밤", 22, 4))
UNCATEGORIZED = "미분류"


class InsightsError(Exception):
    """분석할 수 없음 (사용자에게 보여줄 메시지)."""


def in_bucket(hour: int, start: int, end: int) -> bool:
    return start <= hour <= end if start <= end else hour >= start or hour <= end


def periods_before(p: Period, payday: int, count: int) -> list[Period]:
    """p 바로 앞의 기간 count 개 (오래된 것부터)."""
    out = []
    for _ in range(count):
        p = period_for(p.start - timedelta(days=1), payday)
        out.append(p)
    return out[::-1]


def label(p: Period) -> str:
    return f"{p.start.month}.{p.start.day}~{p.end.month}.{p.end.day}"


def _span(periods: list[Period]) -> dict:
    return {"start": periods[0].start.isoformat(), "end": periods[-1].end.isoformat(), "periods": len(periods),
            "label": f"{label(periods[0]).split('~')[0]} ~ {label(periods[-1]).split('~')[1]}"}


def _is_one_off(r: sqlite3.Row) -> bool:
    return _is_variable(r) and r["type"] != "refund" and r["amount"] >= ONE_OFF


def _counts(r: sqlite3.Row) -> bool:
    """습관 통계에 넣는 변동비 거래 (일회성 큰 지출 제외)."""
    return _is_variable(r) and not _is_one_off(r)


def _signed_amount(r: sqlite3.Row) -> int:
    return -r["amount"] if r["type"] == "refund" else r["amount"]


def _is_variable(r: sqlite3.Row) -> bool:
    if r["recurring_id"] is not None:
        return False
    return r["type"] in ("expense", "refund") or (r["type"] == "transfer" and r["transfer_kind"] == "external")


def _is_spend(r: sqlite3.Row) -> bool:
    return r["type"] == "expense" and r["recurring_id"] is None and r["amount"] < ONE_OFF


def _merchant(r: sqlite3.Row) -> str:
    name = (r["merchant_key"] or r["merchant"] or "").strip()
    if not name:
        return "(이름 없음)"
    return "(번호로 된 상대)" if _NUMBER_LIKE.search(name) else name


def compute(conn: sqlite3.Connection, months: int = 3, today: date | None = None) -> dict:
    if months not in MONTHS:
        raise InsightsError(f"기간은 {', '.join(map(str, MONTHS))}개월 중에서 고르세요")
    today = today or date.today()
    settings = get_settings(conn)
    payday = int(settings["payday"])
    current = period_for(today, payday)
    first = conn.execute("SELECT MIN(occurred_on) FROM transactions").fetchone()[0]
    if not first:
        raise InsightsError("거래가 없어 분석할 수 없어요 — 가계부에 거래를 먼저 넣어 주세요")
    first_day = date.fromisoformat(first)
    window = [p for p in periods_before(current, payday, months) if p.start >= first_day]
    if not window:
        raise InsightsError("끝난 기간이 아직 없어요 — 수입일 기준 한 기간이 다 지나야 습관을 볼 수 있어요")
    baseline = [p for p in periods_before(window[0], payday, months) if p.start >= first_day]
    notes = []
    if len(window) < months:
        notes.append(f"데이터가 {first} 부터라 끝난 기간 {len(window)}개만 분석합니다")

    periods = baseline + window
    starts = [p.start for p in periods]
    rows = conn.execute(
        "SELECT t.*, c.name AS category FROM transactions t LEFT JOIN categories c ON c.id = t.category_id "
        "WHERE occurred_on BETWEEN ? AND ? ORDER BY occurred_on, id",
        (periods[0].start.isoformat(), today.isoformat()),
    ).fetchall()

    def period_index(d: date) -> int | None:
        i = bisect_right(starts, d) - 1
        return i if i >= 0 and periods[i].contains(d) else None

    n_base = len(baseline)
    by_period: list[list[sqlite3.Row]] = [[] for _ in periods]
    current_rows: list[sqlite3.Row] = []
    for r in rows:
        d = date.fromisoformat(r["occurred_on"])
        if current.contains(d):
            current_rows.append(r)
            continue
        i = period_index(d)
        if i is not None:
            by_period[i].append(r)
    win_rows = [r for rows_ in by_period[n_base:] for r in rows_]
    base_rows = [r for rows_ in by_period[:n_base] for r in rows_]
    n = len(window)

    categories = conn.execute("SELECT name, description, budget FROM categories ORDER BY sort_order, id").fetchall()
    cat_order = [c["name"] for c in categories]
    budgets = {c["name"]: c["budget"] for c in categories}
    budget_total = sum(budgets.values())

    def variable(rows_: list[sqlite3.Row], one_off: bool = False) -> int:
        return sum(_signed_amount(r) for r in rows_ if (_is_variable(r) if one_off else _counts(r)))

    def by_category(rows_: list[sqlite3.Row]) -> dict[str, int]:
        out: dict[str, int] = defaultdict(int)
        for r in rows_:
            if _counts(r):
                out[r["category"] or UNCATEGORIZED] += _signed_amount(r)
        return out

    period_stats = [{**p.to_dict(), "label": label(p), "in_window": i >= n_base, "total": variable(rs),
                     "one_off": sum(r["amount"] for r in rs if _is_one_off(r)), "by_category": dict(by_category(rs))}
                    for i, (p, rs) in enumerate(zip(periods, by_period))]
    win_totals = [s["total"] for s in period_stats[n_base:]]
    total = sum(win_totals)
    avg = total / n
    base_avg = sum(s["total"] for s in period_stats[:n_base]) / n_base if n_base else None

    facts: list[dict] = []

    def fact(group: str, text: str) -> int:
        facts.append({"id": len(facts) + 1, "group": group, "text": text})
        return len(facts)

    # 1) 전체
    span = _span(window)
    ledger_total = variable(win_rows, one_off=True)
    one_offs = sorted((r for r in win_rows if _is_one_off(r)), key=lambda r: -r["amount"])
    fact("overview", f"분석 기간 {window[0].start} ~ {window[-1].end} (수입일 기준 {n}개 기간). 가계부 기준 변동비 합계 "
                     f"{won(ledger_total)}" + (f", 그중 일회성 큰 지출({won(ONE_OFF)} 이상 한 건) {len(one_offs)}건 "
                                              f"{won(sum(r['amount'] for r in one_offs))}" if one_offs else "")
                     + f". 습관 통계는 일회성 큰 지출을 뺀 기준: 합계 {won(total)}, 기간 평균 {won(avg)} "
                       f"(가장 적은 기간 {won(min(win_totals))}, 가장 많은 기간 {won(max(win_totals))}).")
    if one_offs:
        fact("overview", "분석 기간의 일회성 큰 지출: " + ", ".join(
            f"{r['occurred_on']} {_merchant(r) if r['type'] == 'expense' else '송금'} {won(r['amount'])}"
            f"({r['category'] or UNCATEGORIZED})" for r in one_offs[:5]) + (" 외" if len(one_offs) > 5 else "") + ".")
    if base_avg is not None:
        base_one = [r for r in base_rows if _is_one_off(r)]
        fact("overview", f"비교 기간 {baseline[0].start} ~ {baseline[-1].end} ({n_base}개 기간) 평균 변동비(일회성 제외) "
                         f"{won(base_avg)} → 분석 기간 평균이 {change(avg, base_avg)}."
                         + (f" 비교 기간의 일회성 큰 지출 {len(base_one)}건 {won(sum(r['amount'] for r in base_one))}은 뺐음."
                            if base_one else ""))
    budgeted = [c for c in cat_order if budgets.get(c)]
    if budgeted:
        per = [sum(s["by_category"].get(c, 0) for c in budgeted) for s in period_stats[n_base:]]
        b_avg = sum(per) / n
        over = sum(1 for t in per if t > budget_total)
        fact("overview", f"예산이 있는 카테고리({', '.join(budgeted)}) 합계 기간 평균 {won(b_avg)} — 예산 합계 {won(budget_total)}의 "
                         f"{share(b_avg, budget_total)}, 예산 합계를 넘은 기간 {over}/{n}.")
    summary_now = period_summary(conn, current, today)
    income = int(settings.get("monthly_income") or 0)
    pool = summary_now["variable"]["pool"]
    if income:
        fact("overview", f"월 주수입(계획) {won(income)}, 정기지출 {won(summary_now['recurring']['total'])} → 변동비로 쓸 수 있는 돈 "
                         f"{won(pool)}. 분석 기간 평균 변동비(일회성 제외)는 그중 {share(avg, pool)}.")

    # 2) 카테고리
    win_cat = by_category(win_rows)
    base_cat = by_category(base_rows)
    spend_win = [r for r in win_rows if _is_spend(r)]
    names = cat_order + ([UNCATEGORIZED] if win_cat.get(UNCATEGORIZED) else [])
    cat_stats = []
    for name in names:
        amount = win_cat.get(name, 0)
        if amount <= 0:
            continue
        cat_avg = amount / n
        spends = [r for r in spend_win if (r["category"] or UNCATEGORIZED) == name]
        parts = [f"{name}: 기간 평균 {won(cat_avg)} (변동비의 {share(amount, total)})"]
        budget = budgets.get(name, 0)
        if budget:
            over = sum(1 for s in period_stats[n_base:] if s["by_category"].get(name, 0) > budget)
            parts.append(f"예산 {won(budget)}의 {share(cat_avg, budget)}, 예산 초과 {over}/{n}기간")
        if n_base:
            parts.append(f"비교 기간 대비 {change(cat_avg, base_cat.get(name, 0) / n_base)}")
        if spends:
            parts.append(f"결제 {len(spends)}건(기간당 {len(spends) / n:.0f}건), 1회 평균 {won(sum(r['amount'] for r in spends) / len(spends))}")
        fact("category", ", ".join(parts) + ".")
        cat_stats.append({"name": name, "avg": round(cat_avg), "budget": budget,
                          "baseline_avg": round(base_cat.get(name, 0) / n_base) if n_base else None, "count": len(spends)})

    # 3) 가맹점
    merch: dict[str, dict] = {}
    for r in spend_win:
        m = merch.setdefault(_merchant(r), {"name": _merchant(r), "count": 0, "sum": 0, "cats": Counter()})
        m["count"] += 1
        m["sum"] += r["amount"]
        m["cats"][r["category"] or UNCATEGORIZED] += 1
    merchants = [{"name": m["name"], "count": m["count"], "sum": m["sum"], "avg": round(m["sum"] / m["count"]),
                  "category": m["cats"].most_common(1)[0][0]} for m in merch.values()]
    spend_total = sum(r["amount"] for r in spend_win)
    top = sorted(merchants, key=lambda m: -m["sum"])[:8]
    for m in top:
        fact("merchant", f"가맹점 {m['name']} ({m['category']}): {m['count']}건, 합계 {won(m['sum'])} (결제 합계의 "
                         f"{share(m['sum'], spend_total)}), 1회 평균 {won(m['avg'])}.")
    frequent = sorted(merchants, key=lambda m: (-m["count"], -m["sum"]))[:5]
    if frequent:
        fact("merchant", "자주 결제한 곳: " + ", ".join(f"{m['name']} {m['count']}건(기간당 {m['count'] / n:.0f}건)" for m in frequent) + ".")

    # 4) 소액 결제
    small = [r for r in spend_win if r["amount"] < SMALL]
    if small:
        small_top = Counter(_merchant(r) for r in small).most_common(3)
        fact("small", f"{won(SMALL)} 미만 결제 {len(small)}건(결제 건수의 {share(len(small), len(spend_win))}), 합계 "
                      f"{won(sum(r['amount'] for r in small))}(결제 합계의 {share(sum(r['amount'] for r in small), spend_total)}), "
                      f"기간당 {len(small) / n:.0f}건·{won(sum(r['amount'] for r in small) / n)}. 가장 잦은 곳: "
                      + ", ".join(f"{k} {c}건" for k, c in small_top) + ".")

    # 5) 요일
    days_by_wd = Counter()
    d = window[0].start
    while d <= window[-1].end:
        days_by_wd[d.weekday()] += 1
        d += timedelta(days=1)
    sum_by_wd = Counter()
    for r in spend_win:
        sum_by_wd[date.fromisoformat(r["occurred_on"]).weekday()] += r["amount"]
    weekday = [{"day": WEEKDAYS[i], "total": sum_by_wd[i], "days": days_by_wd[i],
                "avg": round(sum_by_wd[i] / days_by_wd[i]) if days_by_wd[i] else 0} for i in range(7)]
    weekend_avg = sum(sum_by_wd[i] for i in (5, 6)) / max(1, days_by_wd[5] + days_by_wd[6])
    weekday_avg = sum(sum_by_wd[i] for i in range(5)) / max(1, sum(days_by_wd[i] for i in range(5)))
    if spend_win:
        busiest = max(weekday, key=lambda w: w["avg"])
        text = ("요일별 하루 평균 결제: " + ", ".join(f"{w['day']} {won(w['avg'])}" for w in weekday)
                + f". 가장 많은 요일 {busiest['day']}요일.")
        if weekday_avg:
            text += f" 주말 하루 평균 {won(weekend_avg)}은 평일 {won(weekday_avg)}의 {weekend_avg / weekday_avg:.1f}배."
        fact("weekday", text)

    # 6) 시간대 (시각을 아는 결제가 절반 이상일 때만)
    timed = [r for r in spend_win if r["occurred_time"]]
    coverage = len(timed) / len(spend_win) if spend_win else 0.0
    hours = None
    night_share = None
    if timed and coverage >= 0.5:
        hours = [{"hour": h, "amount": 0, "count": 0} for h in range(24)]
        for r in timed:
            h = int(str(r["occurred_time"])[:2]) % 24
            hours[h]["amount"] += r["amount"]
            hours[h]["count"] += 1
        timed_total = sum(r["amount"] for r in timed)
        fact("time", "시간대별 결제 비중(금액): " + ", ".join(
            f"{name}({s}~{e}시) {share(sum(h['amount'] for h in hours if in_bucket(h['hour'], s, e)), timed_total)}"
            for name, s, e in BUCKETS) + f". 시각을 아는 결제 {len(timed)}건 기준.")
        night = [r for r in timed if in_bucket(int(str(r["occurred_time"])[:2]) % 24, 22, 4)]
        night_share = sum(r["amount"] for r in night) / timed_total if timed_total else 0.0
        if night:
            fact("time", f"밤 10시~새벽 4시 결제 {len(night)}건, 합계 {won(sum(r['amount'] for r in night))}(기간당 "
                         f"{won(sum(r['amount'] for r in night) / n)}). 가장 잦은 곳: "
                         + ", ".join(f"{k} {c}건" for k, c in Counter(_merchant(r) for r in night).most_common(3)) + ".")

    # 7) 수입일 직후
    early = late = early_days = late_days = 0
    for p, rs in zip(window, by_period[n_base:]):
        cut = p.start + timedelta(days=7)
        early_days += 7
        late_days += (p.end - cut).days + 1
        for r in rs:
            if _is_spend(r):
                if date.fromisoformat(r["occurred_on"]) < cut:
                    early += r["amount"]
                else:
                    late += r["amount"]
    payday_ratio = None
    if early_days and late_days and late:
        payday_ratio = (early / early_days) / (late / late_days)
        fact("payday", f"수입일부터 7일 동안 하루 평균 결제 {won(early / early_days)}, 나머지 날 하루 평균 {won(late / late_days)} "
                       f"({payday_ratio:.1f}배).")

    # 8) 큰 결제
    big = [r for r in spend_win if r["amount"] >= BIG]
    if big:
        biggest = sorted(spend_win, key=lambda r: -r["amount"])[:5]
        fact("big", f"{won(BIG)} 이상 결제 {len(big)}건, 합계 {won(sum(r['amount'] for r in big))}(결제 합계의 "
                    f"{share(sum(r['amount'] for r in big), spend_total)}). 가장 큰 결제: "
                    + ", ".join(f"{r['occurred_on']} {_merchant(r)} {won(r['amount'])}" for r in biggest) + ".")

    # 9) 새 가맹점 (비교 기간에 없던 곳)
    if n_base:
        seen = {_merchant(r) for r in base_rows if _is_spend(r)}
        fresh = [m for m in merchants if m["name"] not in seen]
        if fresh:
            fresh_sum = sum(m["sum"] for m in fresh)
            fact("new", f"비교 기간에 없던 가맹점 {len(fresh)}곳에서 {won(fresh_sum)}(결제 합계의 {share(fresh_sum, spend_total)}). "
                        "큰 곳: " + ", ".join(f"{m['name']} {won(m['sum'])}" for m in sorted(fresh, key=lambda m: -m["sum"])[:3]) + ".")

    # 10) 송금·정산
    sends = [r for r in win_rows if r["type"] == "transfer" and r["transfer_kind"] == "external" and _counts(r)]
    refunds = [r for r in win_rows if r["type"] == "refund"]
    if sends or refunds:
        fact("transfer", f"정기지출이 아닌 송금(다른 사람 계좌로 보낸 돈) {len(sends)}건, 합계 {won(sum(r['amount'] for r in sends))}. "
                         f"돌려받은 정산·환불 {len(refunds)}건, 합계 {won(sum(r['amount'] for r in refunds))}. (상대 이름은 넣지 않음)")

    # 11) 고정 지출·저금 (정기지출 계획 대비 실제)
    fixed = fixed_costs.compute(conn, window, baseline, payday, income, avg)
    for group, text in fixed_costs.fact_lines(fixed):
        fact(group, text)

    # 12) 절세 (올해 귀속연도 — 분석 기간과 따로)
    tax = tax_analysis.compute(conn, today)
    for text in tax_analysis.fact_lines(tax):
        fact("tax", text)

    # 13) 데이터 상태
    review = sum(1 for r in win_rows if r["needs_review"])
    uncategorized = [r for r in spend_win if not r["category"]]
    if review or uncategorized:
        fact("quality", f"분석 기간에 분류 필요 표시 {review}건, 카테고리 없는 결제 {len(uncategorized)}건"
                        f"({won(sum(r['amount'] for r in uncategorized))}) — 카테고리 분석이 그만큼 덜 정확할 수 있음.")

    # 14) 이번 기간 진행
    elapsed = (today - current.start).days + 1
    current_stats = None
    if elapsed >= 3:
        spent_now = variable(current_rows)
        same_day = [sum(_signed_amount(r) for r in rs if _counts(r)
                        and date.fromisoformat(r["occurred_on"]) < p.start + timedelta(days=elapsed))
                    for p, rs in zip(window, by_period[n_base:])]
        pace = sum(same_day) / n
        current_stats = {**current.to_dict(), "elapsed": elapsed, "days": (current.end - current.start).days + 1,
                         "spent": spent_now, "pace": round(pace)}
        fact("current", f"이번 기간({current.start} ~ {current.end}) {elapsed}일째 변동비(일회성 제외) {won(spent_now)}. 분석 기간의 같은 날짜까지 "
                        f"평균 {won(pace)} → {change(spent_now, pace)}.")

    return {
        "months": months,
        "window": span,
        "baseline": _span(baseline) if baseline else None,
        "current": current.to_dict(),
        "facts": facts,
        "notes": notes,
        "categories": [{"name": c["name"], "description": c["description"], "budget": c["budget"]} for c in categories],
        "stats": {
            "periods": period_stats,
            "category_order": names,
            "categories": cat_stats,
            "weekday": weekday,
            "hours": hours,
            "hour_coverage": round(coverage, 3),
            "merchants": top,
            "kpis": {"avg_total": round(avg), "ledger_total": ledger_total, "one_off_total": sum(r["amount"] for r in one_offs),
                     "one_off_count": len(one_offs), "baseline_avg": round(base_avg) if base_avg is not None else None,
                     "budget_total": budget_total, "pool": pool if income else None,
                     "small_count_share": round(len(small) / len(spend_win), 3) if spend_win else None,
                     "small_amount_share": round(sum(r["amount"] for r in small) / spend_total, 3) if spend_total else None,
                     "night_share": round(night_share, 3) if night_share is not None else None,
                     "payday_ratio": round(payday_ratio, 2) if payday_ratio is not None else None,
                     "spend_count": len(spend_win),
                     "saving_rate": fixed["allocation"]["saving_rate"] if fixed["allocation"] else None,
                     "tax_extra": tax["summary"]["extra_total"] if tax["summary"] else None},
            "current": current_stats,
            "fixed": fixed,
            "tax": tax,
        },
    }
