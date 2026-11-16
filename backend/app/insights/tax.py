"""절세 분석 — 올해(귀속연도) 가계부로 연말정산 공제 항목을 추정한다. 세법 숫자·계산식은 tax_rules.py.

- 올해 = 1월 1일(데이터가 늦게 시작하면 그날)부터 오늘까지의 실제 거래 + 12월 31일까지 이어질 몫. 정기지출은 남은 출금일마다
  계획 금액, 카드 사용은 올해 하루 평균으로 잇는다.
- 공제 항목은 정기지출 이름(과 칸 이름)으로 알아본다: 연금저축·IRP·ISA·청약·전세대출(주택임차차입금)·보험.
- 카드 사용: 결제수단 이름으로 신용카드(15%)·체크·선불(30%)·공제 안 됨(계좌 출금 등)을 추정하고 — 사용자가 고칠 수 있다 —
  가맹점 이름으로 대중교통(40%)·도서·공연·체육시설(30%)을 가른다. 보험료·통신·공과금·관리비·세금·이자는 카드로 내도 뺀다.
  전통시장·해외 사용은 이름만으로 알 수 없어 따로 가르지 않는다.
- 효과: 같은 가정의 결정세액 추정에서 '그 항목이 있을 때와 없을 때'의 차이(지방소득세 포함). 특별공제(주택임차차입금 공제·
  보험료 세액공제)를 받으면 표준세액공제 13만 원을 못 받으므로 세금이 적은 쪽을 고른다.
- 내 정보(설정 tax_profile): 총급여(세전, 계산기 입력값 salary_parts 도 남긴다), 무주택 세대주, 자녀 수, 결제수단 분류. 총급여가 비면
  급여 관리의 명세서 기록으로 잇고(salary.analysis), 그것도 없으면 월 주수입 × 12 로 가정한다.
"""

import calendar
import sqlite3
from collections.abc import Callable
from datetime import date

from app.insights import tax_rules as R
from app.insights.fmt import won
from app.ledger.settings import get_settings

PROFILE_KEY = "tax_profile"
DEFAULT_PROFILE = {"gross_salary": 0, "homeless_head": None, "children": 0, "payment_kinds": {}, "salary_parts": None}
PAYMENT_KINDS = {"credit": "신용카드", "debit": "체크·선불·현금영수증", "none": "공제 안 됨"}
ONE_OFF = 1_000_000  # 연말까지 이을 때 빼는 한 건 (facts.ONE_OFF 와 같은 기준) — 보증금 같은 큰 지출이 하루 평균을 부풀리지 않게

# 정기지출 이름(소문자) → 공제 항목. 앞에서부터 처음 맞는 것. 보험은 칸 이름('보험')으로도 알아본다.
ITEM_KEYWORDS = (
    ("pension_savings", ("연금저축",)),
    ("irp", ("irp", "퇴직연금")),
    ("isa", ("isa",)),
    ("housing_saving", ("청약",)),
    ("rent_loan", ("전세대출", "전세자금", "주택임차", "임차차입")),
    ("insurance", ("보험",)),
)
# 카드로 내도 신용카드 등 공제에서 빠지는 것 — 정기지출(이름·칸)과 가맹점에 따로 (가맹점에 '이자'를 쓰면 이자카야가 걸린다)
RECURRING_EXCLUDED = ("보험", "통신", "인터넷", "휴대폰", "공과금", "관리비", "세금", "이자", "대출", "월세")
MERCHANT_EXCLUDED = ("보험", "국세", "지방세", "세무서", "관리비", "한국전력", "도시가스", "상품권", "면세점")
# 대중교통·문화는 정규화 가맹점 키(지점명 뺀 이름)로 본다 — '○○박물관점' 식당이 문화로 잡히지 않게. '버스'만으로는 놀유니버스·
# 인큐버스가 걸려 버스 종류를 적는다.
TRANSIT = ("지하철", "교통공사", "코레일", "korail", "srt", "철도", "티머니", "캐시비", "기후동행", "서울버스", "경기버스",
           "인천버스", "시내버스", "시외버스", "고속버스", "마을버스", "광역버스")
TRANSIT_NOT = ("택시", "자전거", "모빌리티", "킥보드")
CULTURE = ("서점", "문고", "알라딘", "yes24", "예스24", "cgv", "메가박스", "롯데시네마", "박물관", "미술관", "공연",
           "티켓링크", "수영장", "헬스장", "피트니스", "체력단련")
BUCKET_LABEL = {"credit": "신용카드", "debit": "체크·선불", "transit": "대중교통", "culture": "도서·공연·체육시설",
                "market": "전통시장", "none": "계좌 출금 등 공제 안 되는 수단", "excluded": "공제 제외 항목(보험·통신·공과금 등)"}
SOURCE_KEYS = {"pension": ("pension_savings", "irp"), "housing_saving": ("housing_saving",), "rent_loan": ("rent_loan",),
               "insurance": ("insurance",), "isa": ("isa",)}
TITLES = {"card": "신용카드 등 사용액", "pension": "연금계좌 (연금저축·IRP)", "housing_saving": "주택청약종합저축",
          "rent_loan": "전세대출 원리금 상환 (주택임차차입금)", "insurance": "보장성 보험료", "isa": "ISA"}


def get_profile(conn: sqlite3.Connection) -> dict:
    raw = get_settings(conn).get(PROFILE_KEY)
    return {**DEFAULT_PROFILE, **(raw if isinstance(raw, dict) else {})}


def guess_payment_kind(method: str) -> tuple[str, bool]:
    """결제수단 이름 → (분류, 확실한지). 간편결제·이름 없는 카드는 신용카드로 추정(공제율이 낮은 쪽 — 공제를 부풀리지 않는다)."""
    m = method.lower()
    if "체크" in m or "check" in m:
        return "debit", True
    if "머니" in m:  # 페이 머니 = 선불전자지급수단
        return "debit", True
    if "포인트" in m:  # 적립 포인트 결제는 공제되지 않는다 (충전 포인트는 다를 수 있음)
        return "none", False
    if any(k in m for k in ("통장", "예금", "계좌", "적금")):
        return "none", True
    if "카드" in m:
        return "credit", True
    return "credit", False


def item_key(name: str, group: str) -> str | None:
    text = name.strip().lower()
    for key, words in ITEM_KEYWORDS:
        if any(w in text for w in words):
            return key
    return "insurance" if "보험" in group else None


def _remaining_payments(day: int | None, today: date, paid_this_month: bool) -> int:
    """올해 남은 출금 횟수 — 달력 달마다 한 번(출금일이 미정이면 말일로 본다). 이번 달에 이미 냈으면 이번 달은 뺀다."""
    count = 0
    for month in range(today.month, 13):
        last = calendar.monthrange(today.year, month)[1]
        due = date(today.year, month, min(day or last, last))
        if month == today.month and (paid_this_month or due <= today):
            continue
        count += 1
    return count


def _bucket(row: sqlite3.Row, kind: str) -> str:
    recurring = f"{row['item'] or ''} {row['grp'] or ''}".lower()
    merchant = f"{row['merchant']} {row['merchant_key']}".lower()
    if (row["item"] and any(w in recurring for w in RECURRING_EXCLUDED)) or any(w in merchant for w in MERCHANT_EXCLUDED):
        return "excluded"
    if kind == "none":
        return "none"
    key = (row["merchant_key"] or row["merchant"]).lower()
    if any(w in key for w in TRANSIT) and not any(w in key for w in TRANSIT_NOT):
        return "transit"
    if any(w in key for w in CULTURE):
        return "culture"
    return kind


def _useful(gain_at: Callable[[int], int], room: int) -> tuple[int, int]:
    """(효과가 끝나는 추가 금액, 그때 줄어드는 세금). 결정세액이 0 이 되면 더 내도 효과가 없어 그 지점을 찾는다(1만 원 단위)."""
    best = gain_at(room)
    if best <= 0:
        return 0, 0
    lo, hi = 0, room
    while hi - lo > 10_000:
        mid = (lo + hi) // 2
        if gain_at(mid) >= best - 100:
            hi = mid
        else:
            lo = mid
    return hi, best


def _tax_total(gross: int, s: dict) -> tuple[int, bool]:
    """(결정세액 추정 — 지방세 포함, 특별공제를 골랐는지). 표준세액공제와 특별공제 중 세금이 적은 쪽."""
    base_ded = s["card"] + s["housing_saving"]
    standard = R.income_tax(gross, base_ded, s["pension"] + R.STANDARD_CREDIT)["total"]
    if not (s["rent_loan"] or s["insurance"]):
        return standard, False
    special = R.income_tax(gross, base_ded + s["rent_loan"], s["pension"] + s["insurance"])["total"]
    return (special, True) if special <= standard else (standard, False)


def compute(conn: sqlite3.Connection, today: date | None = None) -> dict:
    today = today or date.today()
    settings = get_settings(conn)
    profile = get_profile(conn)
    year = today.year
    notes: list[str] = []
    gross = int(profile.get("gross_salary") or 0)
    source = "profile"
    if gross <= 0:
        from app.salary.analysis import projected_gross  # 늦게 — 급여 기록이 있으면 그것으로 올해 총급여를 잇는다

        gross, source = projected_gross(conn, year, today), "salary"
    if gross <= 0:
        gross, source = int(settings.get("monthly_income") or 0) * 12, "assumed"
    assumed = source == "assumed"
    out = {"year": year, "rules_year": R.RULES_YEAR, "profile": profile, "gross": gross, "gross_assumed": assumed, "gross_source": source,
           "available": gross > 0, "notes": notes, "items": [], "methods": [], "card": None, "summary": None}
    if not gross:
        notes.append("총급여(세전)나 월 주수입을 넣어야 절세를 계산할 수 있어요")
        return out
    if assumed:
        notes.append(f"총급여를 입력하지 않아 월 주수입 × 12 = {won(gross)}로 가정했어요 — 세전 총급여는 이보다 클 수 있어요")
    if source == "salary":
        notes.append(f"총급여를 입력하지 않아 급여명세서 기록으로 올해 총급여를 {won(gross)}로 이었어요 (상여는 잇지 않음)")
    if year != R.RULES_YEAR:
        notes.append(f"세법 숫자는 {R.RULES_YEAR}년 귀속 기준이에요 — {year}년 개정 내용을 확인해야 해요")
    first = conn.execute("SELECT MIN(occurred_on) FROM transactions").fetchone()[0]
    start = max(date(year, 1, 1), date.fromisoformat(first)) if first else today
    observed = max(1, (today - start).days + 1)
    rest_days = (date(year, 12, 31) - date(year, 1, 1)).days + 1 - observed
    if start > date(year, 1, 1):
        notes.append(f"올해 거래가 {start} 부터 있어 그날부터의 하루 평균으로 1년을 이었어요")
    out["observed_from"] = start.isoformat()

    # 카드 등 사용액
    kinds = profile.get("payment_kinds") or {}
    ytd = dict.fromkeys(BUCKET_LABEL, 0)
    big = dict.fromkeys(BUCKET_LABEL, 0)
    methods: dict[str, dict] = {}
    rows = conn.execute(
        "SELECT t.amount, t.merchant, t.merchant_key, t.payment_method, r.name AS item, g.name AS grp FROM transactions t "
        "LEFT JOIN recurring_items r ON r.id = t.recurring_id LEFT JOIN recurring_groups g ON g.id = r.group_id "
        "WHERE t.type = 'expense' AND t.occurred_on BETWEEN ? AND ?", (start.isoformat(), today.isoformat())).fetchall()
    for r in rows:
        method = (r["payment_method"] or "").strip()
        guess, sure = guess_payment_kind(method)
        kind = kinds.get(method) if kinds.get(method) in PAYMENT_KINDS else guess
        m = methods.setdefault(method, {"method": method, "ytd": 0, "count": 0, "kind": kind,
                                        "guessed": method not in kinds and not sure})
        m["ytd"] += r["amount"]
        m["count"] += 1
        b = _bucket(r, kind)
        ytd[b] += r["amount"]
        if r["amount"] >= ONE_OFF:
            big[b] += r["amount"]
    projected = {k: v + round((v - big[k]) / observed * rest_days) for k, v in ytd.items()}
    used = {k: projected[k] for k in R.CARD_ORDER}
    children = int(profile.get("children") or 0)
    card = R.card_deduction(gross, used, children)

    # 정기지출로 알아본 공제 항목
    items: dict[str, list[dict]] = {}
    year_from = date(year, 1, 1).isoformat()
    for it in conn.execute("SELECT r.*, g.name AS group_name FROM recurring_items r JOIN recurring_groups g ON g.id = r.group_id "
                           "ORDER BY g.sort_order, r.sort_order, r.id").fetchall():
        key = item_key(it["name"], it["group_name"])
        if not key:
            continue
        paid = conn.execute("SELECT COALESCE(SUM(amount), 0), COALESCE(SUM(occurred_on >= ?), 0) FROM transactions "
                            "WHERE recurring_id = ? AND occurred_on BETWEEN ? AND ?",
                            (today.replace(day=1).isoformat(), it["id"], year_from, today.isoformat())).fetchone()
        left = _remaining_payments(it["day_of_month"], today, bool(paid[1])) * it["amount"] if it["active"] else 0
        if not paid[0] and not left:  # 만들어만 둔 항목(처음 깔린 0원 항목 등)
            continue
        items.setdefault(key, []).append({"name": it["name"].strip(), "paid": paid[0], "remaining": left, "total": paid[0] + left})
    total = {k: sum(i["total"] for i in v) for k, v in items.items()}
    homeless = profile.get("homeless_head")
    saving_ok = homeless is not False and gross <= R.HOUSING_SAVING_MAX_SALARY
    rent_ok = homeless is not False
    pension_base, pension_cr = R.pension_credit(gross, total.get("pension_savings", 0), total.get("irp", 0))
    saving_ded, rent_ded = R.housing_deductions(total.get("housing_saving", 0), total.get("rent_loan", 0), saving_ok, rent_ok)
    state = {"card": card["deduction"], "housing_saving": saving_ded, "rent_loan": rent_ded, "pension": pension_cr,
             "insurance": R.insurance_credit(total.get("insurance", 0))}
    now, special = _tax_total(gross, state)
    none, _ = _tax_total(gross, dict.fromkeys(state, 0))

    def effect(key: str) -> int:
        return _tax_total(gross, {**state, key: 0})[0] - now

    def gain(**changes: int) -> int:
        return max(0, now - _tax_total(gross, {**state, **changes})[0])

    rate = R.pension_credit_rate(gross)
    result: list[dict] = []

    # 신용카드 등 — 남은 기간 신용카드 몫을 체크·선불로 쓰면
    credit_left = max(0, projected["credit"] - ytd["credit"])
    moved = R.card_deduction(gross, {**used, "credit": used["credit"] - credit_left, "debit": used["debit"] + credit_left}, children)
    under = card["over"] <= 0
    result.append({
        "key": "card", "title": TITLES["card"], "kind": "income_deduction", "status": "ok" if card["total"] else "none",
        "paid": sum(ytd[k] for k in R.CARD_ORDER), "total": card["total"], "limit": card["limit"],
        "deduction": card["deduction"], "effect": effect("card"),
        "room": 0 if under else credit_left, "useful": 0 if under else credit_left,
        "extra_saving": 0 if under else gain(card=moved["deduction"]),
        "requirement": f"총급여의 {R.CARD_MIN_SHARE:.0%}({won(card['threshold'])})를 넘게 쓴 몫부터 공제 — 신용카드 15%, 체크·선불·현금영수증 30%, "
                       "대중교통 40%. 보험료·통신·공과금·관리비·세금·해외 사용은 빠져요.",
        "law": "조세특례제한법 126조의2",
    })
    pension_paid = sum(i["paid"] for k in ("pension_savings", "irp") for i in items.get(k, []))
    pension_room = R.PENSION_TOTAL_LIMIT - pension_base
    pension_useful, pension_gain = _useful(lambda x: gain(pension=round(min(R.PENSION_TOTAL_LIMIT, pension_base + x) * rate)), pension_room)
    result.append({
        "key": "pension", "title": TITLES["pension"], "kind": "tax_credit",
        "status": "ok" if pension_base else "none", "paid": pension_paid, "total": total.get("pension_savings", 0) + total.get("irp", 0),
        "limit": R.PENSION_TOTAL_LIMIT, "deduction": pension_base, "effect": effect("pension"), "room": pension_room,
        "useful": pension_useful, "extra_saving": pension_gain,
        "requirement": f"연금저축 {won(R.PENSION_SAVINGS_LIMIT)}, IRP 와 합쳐 {won(R.PENSION_TOTAL_LIMIT)}까지 납입액의 "
                       f"{rate * (1 + R.LOCAL_TAX):.1%}(지방세 포함, 총급여 {won(R.PENSION_HIGH_RATE_SALARY)} "
                       f"{'이하' if rate == R.PENSION_RATES[0] else '초과'}) 세액공제. 55세 전에 빼면 공제받은 세금을 다시 내요.",
        "law": "소득세법 59조의3",
    })
    hs_total, rent_total = total.get("housing_saving", 0), total.get("rent_loan", 0)
    hs_room = max(0, R.HOUSING_SAVING_LIMIT - hs_total) if saving_ok else 0

    def housing_gain(saving_paid: int, rent_paid: int) -> int:
        d = R.housing_deductions(saving_paid, rent_paid, saving_ok, rent_ok)
        return gain(housing_saving=d[0], rent_loan=d[1])

    if "housing_saving" in items:
        hs_useful, hs_gain = _useful(lambda x: housing_gain(hs_total + x, rent_total), hs_room)
        result.append({
            "key": "housing_saving", "title": TITLES["housing_saving"], "kind": "income_deduction",
            "status": "no" if not saving_ok else ("ok" if homeless else "check"),
            "paid": sum(i["paid"] for i in items["housing_saving"]), "total": hs_total, "limit": R.HOUSING_SAVING_LIMIT,
            "deduction": saving_ded, "effect": effect("housing_saving"), "room": hs_room, "useful": hs_useful, "extra_saving": hs_gain,
            "requirement": f"무주택 세대주(또는 배우자)·총급여 {won(R.HOUSING_SAVING_MAX_SALARY)} 이하. 연 {won(R.HOUSING_SAVING_LIMIT)}(월 25만 원)까지 "
                           f"납입액의 {R.HOUSING_RATE:.0%} 소득공제, 다음 해 2월 말까지 은행에 무주택 확인서를 내야 해요.",
            "law": "조세특례제한법 87조②",
        })
    if "rent_loan" in items:
        rent_cap = max(0, R.HOUSING_COMBINED_LIMIT - saving_ded)
        rent_room = max(0, round(rent_cap / R.HOUSING_RATE) - rent_total) if rent_ok else 0
        rent_useful, rent_gain = _useful(lambda x: housing_gain(hs_total, rent_total + x), rent_room)
        result.append({
            "key": "rent_loan", "title": TITLES["rent_loan"], "kind": "income_deduction",
            "status": "no" if not rent_ok else "check", "paid": sum(i["paid"] for i in items["rent_loan"]), "total": rent_total,
            "limit": round(rent_cap / R.HOUSING_RATE), "deduction": rent_ded, "effect": effect("rent_loan"), "room": rent_room,
            "useful": rent_useful, "extra_saving": rent_gain,
            "requirement": f"무주택 세대주, 국민주택규모 이하 주택(주거용 오피스텔 포함), 입주·전입 전후 3개월 안에 금융기관에서 빌린 전세자금. "
                           f"이자와 원금 상환액의 {R.HOUSING_RATE:.0%}, 청약 공제와 합쳐 {won(R.HOUSING_COMBINED_LIMIT)}까지 — 원금을 더 갚아도 "
                           "들어가요. 신청해야 적용돼요(회사에 요건 서류 확인).",
            "law": "소득세법 52조④",
        })
    if "insurance" in items:
        ins_total = total["insurance"]
        result.append({
            "key": "insurance", "title": TITLES["insurance"], "kind": "tax_credit", "status": "check",
            "paid": sum(i["paid"] for i in items["insurance"]), "total": ins_total, "limit": R.INSURANCE_LIMIT,
            "deduction": min(ins_total, R.INSURANCE_LIMIT), "effect": effect("insurance"), "room": 0, "useful": 0, "extra_saving": 0,
            "requirement": f"만기 환급금이 낸 보험료보다 많지 않은 보장성 보험, 연 {won(R.INSURANCE_LIMIT)}까지 {R.INSURANCE_RATE:.0%} 세액공제 — "
                           f"특별공제를 받으면 표준세액공제 {won(R.STANDARD_CREDIT)}을 못 받아요.",
            "law": "소득세법 59조의4①",
        })
    if "isa" in items:
        isa_free = R.ISA_TAX_FREE[0] if gross <= R.ISA_LOW_SALARY else R.ISA_TAX_FREE[1]
        extra_cap = R.ISA_PENSION_EXTRA[1]
        result.append({
            "key": "isa", "title": TITLES["isa"], "kind": "info", "status": "ok",
            "paid": sum(i["paid"] for i in items["isa"]), "total": total["isa"], "limit": R.ISA_YEARLY,
            "deduction": isa_free, "effect": 0, "room": extra_cap, "useful": extra_cap,
            "extra_saving": round(extra_cap * rate * (1 + R.LOCAL_TAX)),
            "requirement": f"3년 이상 유지하면 이자·배당 {won(isa_free)}까지 비과세(직전 연도 총급여 {won(R.ISA_LOW_SALARY)} 이하면 "
                           f"{won(R.ISA_TAX_FREE[0])}), 넘는 몫은 9% 분리과세. 만기 자금을 연금계좌로 옮기면 옮긴 돈의 10%(최대 "
                           f"{won(extra_cap)})만큼 연금계좌 공제 한도가 늘어요.",
            "law": "조세특례제한법 91조의18 · 소득세법 59조의3",
        })
    for x in result:
        x["sources"] = [i["name"] for k in SOURCE_KEYS.get(x["key"], ()) for i in items.get(k, [])]

    out.update(
        items=result,
        methods=sorted(methods.values(), key=lambda m: -m["ytd"]),
        card={"ytd": ytd, "projected": projected, "threshold": card["threshold"], "total": card["total"], "over": card["over"],
              "deduction": card["deduction"], "limit": card["limit"], "raw": card["raw"]},
        summary={"tax_now": now, "tax_without": none, "saved": none - now, "special": special,
                 "marginal": R.income_tax(gross, state["card"] + state["housing_saving"] + (state["rent_loan"] if special else 0))["marginal"],
                 # 카드(남은 기간 체크·선불) + 연금계좌·청약을 한도까지 — 함께 했을 때. 전세대출 원금 상환은 큰돈이라 뺀다
                 "extra_total": gain(card=moved["deduction"] if not under else card["deduction"],
                                     pension=round(R.PENSION_TOTAL_LIMIT * rate),
                                     **(dict(zip(("housing_saving", "rent_loan"),
                                                 R.housing_deductions(hs_total + hs_room, rent_total, saving_ok, rent_ok)))))},
    )
    return out


def fact_lines(t: dict) -> list[str]:
    """LLM 에게 줄 절세 사실 문장."""
    if not t["available"]:
        return [f"절세 분석: {t['notes'][0]}."]
    s = t["summary"]
    lines = [f"절세 분석 {t['year']}년 귀속 ({t['observed_from']} ~ 오늘 실제 거래 + 12월 31일까지 추정, 세법 {t['rules_year']}년 기준). "
             f"총급여 {won(t['gross'])}{' (입력 안 함 — 월 주수입 × 12 로 가정)' if t['gross_assumed'] else ''}. "
             f"예상 결정세액(지방세 포함) 약 {won(s['tax_now'])} — 아래 공제가 하나도 없을 때({won(s['tax_without'])})보다 {won(s['saved'])} 적음. "
             f"한계세율 {s['marginal']:.0%}. 4대보험·부양가족은 단순 가정이라 실제 연말정산과 다를 수 있음. "
             + ("특별공제(주택자금·보험료)가 표준세액공제 13만 원보다 유리해 특별공제로 계산" if s["special"] else
                "표준세액공제 13만 원이 특별공제보다 유리해 표준세액공제로 계산")
             + " — 특별공제 항목끼리는 표준세액공제와 바꿔 받는 것이라 항목별 효과를 더하면 전체와 다를 수 있음. "
             f"카드 남은 기간 체크·선불 + 연금계좌·청약을 한도까지 채우면 함께 약 {won(s['extra_total'])} 더 감소(추정)."]
    for x in t["items"]:
        status = {"ok": "", "check": " (요건 확인 필요)", "no": " (요건에 안 맞음)", "none": " (해당 거래 없음)"}[x["status"]]
        src = f" [{', '.join(x['sources'])}]" if x["sources"] else ""
        if x["key"] == "card":
            c = t["card"]
            parts = ", ".join(f"{BUCKET_LABEL[k]} {won(c['projected'][k])}" for k in (*R.CARD_ORDER, "none", "excluded") if c["projected"][k])
            text = (f"{x['title']}: 올해 예상 {parts}. 최저사용금액(총급여 25%) {won(c['threshold'])}"
                    + (f"을 {won(c['over'])} 넘어 소득공제 {won(c['deduction'])}(한도 {won(c['limit'])}), 세금 약 {won(x['effect'])} 감소."
                       if c["over"] > 0 else f"에 {won(-c['over'])} 모자라 공제 없음 — 남은 기간은 공제율보다 카드 혜택을 보고 써도 됨."))
            if x["extra_saving"]:
                text += f" 남은 기간 신용카드 예상 사용 {won(x['room'])}을 체크·선불로 쓰면 세금 약 {won(x['extra_saving'])} 더 감소."
            elif c["over"] > 0 and c["raw"] >= c["limit"]:
                text += (f" 공제 계산액 {won(c['raw'])}이 한도 {won(c['limit'])}를 넘어 — 남은 기간 체크카드로 바꾸거나 더 써도 공제는 "
                         "늘지 않음(대중교통 추가 한도는 반영).")
        elif x["key"] == "isa":
            text = (f"{x['title']}{src}: 올해 납입 {won(x['paid'])}(연말까지 예상 {won(x['total'])}). 비과세 한도 {won(x['deduction'])}. "
                    f"만기 자금을 연금계좌로 옮기면 공제 한도가 최대 {won(x['room'])} 늘어 최대 약 {won(x['extra_saving'])} 더 세액공제(만기 때).")
        else:
            label = "소득공제" if x["kind"] == "income_deduction" else "세액공제 대상"
            text = (f"{x['title']}{src}{status}: 올해 실제 {won(x['paid'])}, 연말까지 예상 {won(x['total'])} → {label} {won(x['deduction'])}"
                    f"(한도 {won(x['limit'])}), 세금 약 {won(x['effect'])} 감소.")
            if x["extra_saving"]:
                text += f" {won(x['useful'])} 더 내면 세금 약 {won(x['extra_saving'])} 더 감소" + (
                    f"(한도는 {won(x['room'])} 남았지만 그보다 더 내도 낼 세금이 없어 효과 없음)." if x["useful"] < x["room"] - 10_000 else ".")
        lines.append(f"{text} 요건: {x['requirement']}")
    guessed = [m["method"] or "(결제수단 없음)" for m in t["methods"] if m["guessed"]]
    profile = t["profile"]
    lines.append("가정·한계: " + "; ".join([
        "무주택 세대주 " + {True: "예", False: "아니요", None: "입력 안 함(예로 가정)"}[profile.get("homeless_head")],
        f"자녀 {int(profile.get('children') or 0)}명(카드 공제 한도에만 반영, 부양가족 공제는 넣지 않음)",
        f"결제수단 분류를 이름으로 추정한 것 {len(guessed)}개" + (f"({', '.join(guessed[:4])}{' 외' if len(guessed) > 4 else ''})" if guessed else ""),
        "전통시장·해외 사용은 구분하지 못함",
        *t["notes"],
    ]) + ".")
    return lines
