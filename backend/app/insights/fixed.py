"""고정 지출·저금 분석 — 정기지출 항목의 계획 금액과 분석 기간에 실제로 낸 돈(연결된 거래)을 비교한다. LLM 없음.

- 정기지출 칸의 kind: saving(저금·투자) / expense(고정 지출). 계획 = 항목 금액(기간당 한 번).
- 실제 = 그 항목에 연결된 거래를 정기지출 화면과 같은 배정(recurring.matching.assign_periods — 미리 나간 결제는 다음 기간 몫)으로 모은 것.
- 항목마다 처음 결제된 기간부터 센다 — 나중에 만든 항목이 앞 기간에 '안 냄'으로 잡히지 않게.
- 주수입 배분: 월 주수입(계획) 대비 저금·고정 지출(분석 기간 실제 평균)·변동비(습관 통계의 기간 평균)·남는 돈.
"""

import sqlite3
from collections import defaultdict
from datetime import date

from app.core.periods import Period
from app.insights.fmt import change, share, won
from app.recurring.matching import RECURRING_SELECT, assign_periods

SUBSCRIPTION = "구독"  # 칸 이름에 이 말이 들면 구독으로 묶어 1년 합계를 보여 준다


def compute(conn: sqlite3.Connection, window: list[Period], baseline: list[Period], payday: int, income: int,
            variable_avg: float) -> dict:
    n = len(window)
    items = []
    for it in conn.execute(RECURRING_SELECT + " ORDER BY g.sort_order, r.sort_order, r.id").fetchall():
        pays = conn.execute("SELECT id, occurred_on, amount FROM transactions WHERE recurring_id = ?", (it["id"],)).fetchall()
        assigned = assign_periods([(p["id"], date.fromisoformat(p["occurred_on"])) for p in pays], it["day_of_month"], payday)
        by_start: dict[date, int] = defaultdict(int)
        for p in pays:
            by_start[assigned[p["id"]].start] += p["amount"]
        first = min(by_start, default=None)
        counted = [by_start.get(p.start, 0) for p in window if first and p.start >= first]
        before = [by_start.get(p.start, 0) for p in baseline if first and p.start >= first]
        if not it["active"] and not any(counted):
            continue
        paid = [x for x in counted if x]
        paid_before = [x for x in before if x]
        items.append({
            "id": it["id"], "name": it["name"].strip(), "group": it["group_name"], "kind": it["group_kind"],
            "planned": it["amount"] if it["active"] else 0, "periods": len(counted), "paid_periods": len(paid),
            "window_avg": round(sum(counted) / n), "paid_avg": round(sum(paid) / len(paid)) if paid else 0,
            "min": min(paid, default=0), "max": max(paid, default=0),
            "baseline_avg": round(sum(paid_before) / len(paid_before)) if paid_before else None,  # 낸 기간끼리 비교
        })

    groups: dict[str, dict] = {}
    for i in items:
        g = groups.setdefault(i["group"], {"name": i["group"], "kind": i["kind"], "planned": 0, "window_avg": 0, "count": 0})
        g["planned"] += i["planned"]
        g["window_avg"] += i["window_avg"]
        g["count"] += 1

    def total(kind: str, key: str) -> int:
        return sum(i[key] for i in items if i["kind"] == kind)

    saving, fixed = total("saving", "window_avg"), total("expense", "window_avg")
    allocation = None
    if income:
        left = income - saving - fixed - round(variable_avg)
        allocation = {"income": income, "saving": saving, "fixed": fixed, "variable": round(variable_avg), "left": left,
                      "saving_rate": round(saving / income, 3)}
    return {"items": items, "groups": list(groups.values()), "allocation": allocation,
            "planned": {"saving": total("saving", "planned"), "fixed": total("expense", "planned")},
            "actual": {"saving": saving, "fixed": fixed}, "periods": n}


def _item_text(i: dict, n: int) -> str:
    parts = [f"{i['name']}({i['group']}): 계획 {won(i['planned']) if i['planned'] else '없음(0원 또는 꺼짐)'}"]
    if i["periods"]:
        parts.append(f"분석 기간 {i['periods']}개 기간 중 {i['paid_periods']}번 냄" + (f", 낸 기간 평균 {won(i['paid_avg'])}" if i["paid_periods"] else ""))
        if i["paid_periods"] > 1 and i["max"] - i["min"] > max(1000, i["paid_avg"] * 0.05):
            parts.append(f"금액이 {won(i['min'])}~{won(i['max'])}로 달라짐")
        if i["baseline_avg"]:
            parts.append(f"비교 기간 평균 {won(i['baseline_avg'])} 대비 {change(i['paid_avg'] or i['window_avg'], i['baseline_avg'])}")
    else:
        parts.append(f"분석 기간({n}개 기간)에 연결된 결제 없음")
    return ", ".join(parts)


def fact_lines(f: dict) -> list[tuple[str, str]]:
    """(묶음, 문장) — 고정 지출(fixed)·저금(saving)·배분."""
    n = f["periods"]
    out: list[tuple[str, str]] = []
    a = f["allocation"]
    income = a["income"] if a else 0
    fixed_items = [i for i in f["items"] if i["kind"] == "expense"]
    saving_items = [i for i in f["items"] if i["kind"] == "saving"]
    if fixed_items:
        groups = [g for g in f["groups"] if g["kind"] == "expense"]
        text = (f"고정 지출(정기지출 지출 칸 {len(fixed_items)}개 항목) 계획 기간당 {won(f['planned']['fixed'])}"
                + (f" — 월 주수입의 {share(f['planned']['fixed'], income)}" if income else "")
                + f". 분석 기간 실제 기간 평균 {won(f['actual']['fixed'])}. 칸별 실제 평균: "
                + ", ".join(f"{g['name']} {won(g['window_avg'])}" for g in sorted(groups, key=lambda g: -g["window_avg"])) + ".")
        out.append(("fixed", text))
        for i in sorted(fixed_items, key=lambda i: -max(i["planned"], i["window_avg"]))[:6]:
            out.append(("fixed", _item_text(i, n) + "."))
        subs = [i for i in fixed_items if SUBSCRIPTION in i["group"] and (i["planned"] or i["window_avg"])]
        if subs:
            per = sum(i["planned"] or i["window_avg"] for i in subs)
            out.append(("fixed", f"구독 {len(subs)}개(" + ", ".join(f"{i['name']} {won(i['planned'] or i['window_avg'])}" for i in subs)
                        + f") → 기간당 {won(per)}, 1년 {won(per * 12)}."))
    if saving_items:
        text = (f"저금·투자(정기지출 저금 칸 {len(saving_items)}개 항목) 계획 기간당 {won(f['planned']['saving'])}"
                + (f" — 월 주수입의 {share(f['planned']['saving'], income)}" if income else "")
                + f". 분석 기간 실제 기간 평균 {won(f['actual']['saving'])}"
                + (f"(월 주수입의 {share(f['actual']['saving'], income)})" if income else "") + ".")
        out.append(("saving", text))
        for i in saving_items:
            out.append(("saving", _item_text(i, n) + "."))
    short = [i for i in f["items"] if i["planned"] and i["periods"] and i["paid_periods"] < i["periods"]]
    if short:
        out.append(("saving" if all(i["kind"] == "saving" for i in short) else "fixed",
                    "분석 기간에 계획보다 덜 낸 정기지출: " + ", ".join(f"{i['name']} {i['paid_periods']}/{i['periods']}기간" for i in short)
                    + " (출금일이 기간 끝이거나 금액이 달라 연결이 안 된 것일 수도 있음)."))
    if a:
        out.append(("saving", f"주수입 배분(분석 기간 평균, 월 주수입 {won(income)} 기준): 저금·투자 {won(a['saving'])}({share(a['saving'], income)}) · "
                              f"고정 지출 {won(a['fixed'])}({share(a['fixed'], income)}) · 변동비(일회성 제외) {won(a['variable'])}"
                              f"({share(a['variable'], income)}) → 남는 돈 {won(a['left'])}({share(a['left'], income)})."))
    return out
