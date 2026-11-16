"""반복 지출 자동 탐지 (#3) — 정기지출로 등록하지 않은 구독·자동이체를 거래 이력에서 찾아 등록을 제안한다.

- 대상: 정기지출에 연결되지 않은 지출·이체(타 계좌·내 계좌). 수입·정산·환불, 빌린 돈 입금, 카드대금은 뺀다.
- 묶기: 정규화 가맹점 키가 같고 금액이 가장 흔한 금액의 ±5% 안. 같은 상대(예: 내 이름)에게 금액이 다른
  자동이체가 여럿일 수 있어서 가맹점 안에서 금액으로 한 번 더 나눈다.
- 주기 (날짜는 달력 기준 — 수입일 기준 기간으로 세면 수입일 근처 결제가 어떤 기간엔 두 번, 어떤 기간엔 0번이 된다.
  그런 경우는 경고를 붙인다. 정기지출은 기간당 한 건만 연결되기 때문)
  - 매월: 같은 날짜 ±3일, 그 날짜가 없는 달은 말일(30일 결제가 2월엔 28일). 3회 이상.
  - 매주: 같은 요일 ±1일. 4회 이상 (3주 동안 같은 커피를 산 습관은 거른다).
  - 한 번 빠짐까지는 이어진 것으로 보고, 마지막으로 이어진 구간만 본다.
- 거르기
  - 끝난 반복: 마지막 결제 뒤로 두 주기 + 여유가 지났으면 뺀다. 기준일은 오늘이 아니라 가장 최근 거래일
    (가져오기를 한동안 안 했으면 모든 구독이 끝난 것처럼 보이므로).
  - 주기에 맞는 거래가 그 구간 같은 묶음 거래의 75% 미만이면(같은 금액 충전을 자주 하는 등) 뺀다.
  - 가장 흔한 금액이 절반 미만이면 뺀다 — 자동결제·자동이체는 금액이 정해져 있고, ±5%는 가끔 붙는 추가 요금이나
    가격 인상을 위한 여유다. 매번 금액이 다른 매달 송금(1/n 정산·배달 주문)이 이 조건으로 걸러진다.
  - 신뢰도 0.4 미만(3회뿐인데 날짜까지 흔들리는 등)은 한 주기 더 지켜본다. 진짜 반복이면 다음 결제로 올라온다.
  - 이미 등록된 정기지출의 키워드에 걸리는 가맹점 (금액만 다르면 사용자가 이미 아는 항목).
  - 같은 날(±1일) 같은 금액 거래가 이미 정기지출에 연결돼 있으면 — 내 계좌 간 이체는 보내는 계좌와 받는 계좌에
    한 번씩 찍혀서, 한쪽만 연결되고 다른 쪽이 후보로 올라온다.
- 후보는 `recurring_candidates`에 남긴다. 거절한 후보는 다시 제안하지 않는다 (같은 가맹점·주기·금액 ±5%).

참고: Tanbeer et al., "Discovering Periodic-Frequent Patterns in Transactional Databases", PAKDD 2009 — 주기성으로
패턴을 고르는 개념만 가져왔다. 가맹점당 수십 건인 가계부에서는 설명하기 쉬운 위 규칙이 더 맞다.
"""

import calendar
import json
import sqlite3
import threading
from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta
from os.path import commonprefix

from app.ledger.merchants import display_name
from app.ledger.settings import current_period, get_settings, loan_counterparty, split_keywords
from app.recurring.matching import assign_periods, link_period

AMOUNT_TOLERANCE = 0.05
MIN_PURITY = 0.75
MIN_SAME_AMOUNT = 0.5  # 가장 흔한 금액의 비율
MIN_CONFIDENCE = 0.4
MAX_GAP = 2  # 이어진 것으로 보는 주기 간격 (2 = 한 번 빠짐까지)
RULES = {"monthly": {"tolerance": 3, "min": 3}, "weekly": {"tolerance": 1, "min": 4}}
WEEKDAYS = "월화수목금토일"
_EPOCH_MONDAY = date(2000, 1, 3)
_SYNC_LOCK = threading.Lock()  # 동시에 들어온 조회가 같은 후보를 두 번 만들지 않도록


@dataclass(frozen=True)
class Tx:
    id: int
    on: date
    amount: int
    merchant: str
    memo: str
    type: str
    transfer_kind: str | None


@dataclass
class Series:
    merchant_key: str
    cadence: str  # monthly / weekly
    anchor: int  # 매월 n일 / 요일 (0 = 월)
    hits: list[Tx]  # 주기에 맞는 거래 (날짜순, 주기마다 한 건)
    first_slot: int
    last_slot: int
    purity: float  # 그 구간 같은 묶음 거래 중 주기에 맞는 비율
    jitter: float  # 기준 날짜와의 평균 차이 (일)
    exact: int  # 기준 날짜에 딱 맞은 횟수

    @property
    def missing(self) -> int:
        return self.last_slot - self.first_slot + 1 - len(self.hits)

    @property
    def same_amount(self) -> float:
        return Counter(t.amount for t in self.hits).most_common(1)[0][1] / len(self.hits)

    @property
    def amount(self) -> int:
        """제안 금액: 최근 세 번 중 가장 흔한 금액 (같으면 최근). 자동 매칭은 금액이 같아야 해서 다음 결제 금액을 고른다.
        가격이 오른 뒤라면 새 금액, 한 번 튄 추가 요금이면 원래 금액이 된다."""
        recent = [t.amount for t in self.hits[-3:]]
        return max(reversed(recent), key=recent.count)


# ---------- 주기 맞추기 ----------

def _month_due(slot: int, anchor: int) -> date:
    y, m = divmod(slot, 12)
    return date(y, m + 1, min(anchor, calendar.monthrange(y, m + 1)[1]))


def _due(cadence: str, slot: int, anchor: int) -> date:
    return _month_due(slot, anchor) if cadence == "monthly" else _EPOCH_MONDAY + timedelta(weeks=slot, days=anchor)


def _slot(cadence: str, d: date, anchor: int) -> tuple[int, int]:
    """d 와 가장 가까운 기준 날짜(매월 anchor일 / 매주 anchor요일)의 (주기 번호, 날짜 차이)."""
    if cadence == "weekly":
        diff = (d.weekday() - anchor + 3) % 7 - 3  # -3..3
        return ((d - timedelta(days=diff)) - _EPOCH_MONDAY).days // 7, diff
    month = d.year * 12 + d.month - 1
    return min(((s, (d - _month_due(s, anchor)).days) for s in (month - 1, month, month + 1)), key=lambda x: abs(x[1]))


def _fit(key: str, txs: list[Tx], cadence: str, anchor: int) -> Series | None:
    tolerance = RULES[cadence]["tolerance"]
    best: dict[int, tuple[int, Tx]] = {}  # 주기 번호 → (날짜 차이, 거래): 기준 날짜에 가장 가까운 한 건
    for tx in txs:
        slot, diff = _slot(cadence, tx.on, anchor)
        if abs(diff) <= tolerance and (slot not in best or abs(diff) < abs(best[slot][0])):
            best[slot] = (diff, tx)
    if not best:
        return None
    slots = sorted(best)
    run = [slots[-1]]  # 마지막으로 이어진 구간
    for s in reversed(slots[:-1]):
        if run[-1] - s > MAX_GAP:
            break
        run.append(s)
    run.reverse()
    hits = [best[s][1] for s in run]
    in_span = sum(1 for t in txs if hits[0].on <= t.on <= hits[-1].on)
    diffs = [abs(best[s][0]) for s in run]
    return Series(key, cadence, anchor, hits, run[0], run[-1], len(hits) / in_span, sum(diffs) / len(diffs),
                  diffs.count(0))


def _best_series(key: str, txs: list[Tx]) -> Series | None:
    for cadence in ("monthly", "weekly"):
        anchors = {t.on.day if cadence == "monthly" else t.on.weekday() for t in txs}
        fits = [s for a in anchors if (s := _fit(key, txs, cadence, a))]
        ok = [s for s in fits if len(s.hits) >= RULES[cadence]["min"] and s.purity >= MIN_PURITY]
        if ok:
            # 날짜가 앞뒤로 흔들리면 가운데 날짜, 같으면 딱 맞은 횟수가 많은 날짜 (주말에 밀린 결제는 원래 날짜)
            return max(ok, key=lambda s: (len(s.hits), s.purity, -s.jitter, s.exact, -s.anchor))
    return None


def _alive(s: Series, ref: date) -> bool:
    return ref <= _due(s.cadence, s.last_slot + MAX_GAP, s.anchor) + timedelta(days=RULES[s.cadence]["tolerance"])


def _amount_groups(txs: list[Tx]) -> list[list[Tx]]:
    """가장 흔한 금액을 중심으로 ±5% 안의 거래를 한 묶음씩 떼어 낸다."""
    groups, left = [], txs
    while left:
        center = Counter(t.amount for t in left).most_common(1)[0][0]
        inside = [t for t in left if abs(t.amount - center) <= center * AMOUNT_TOLERANCE]
        groups.append(inside)
        left = [t for t in left if abs(t.amount - center) > center * AMOUNT_TOLERANCE]
    return groups


def confidence(s: Series) -> float:
    """설명 가능한 점수: 횟수가 많을수록 높고, 빠진 주기·섞인 거래·날짜 흔들림·금액 변동만큼 깎는다."""
    c = 0.55 + 0.1 * min(len(s.hits) - RULES[s.cadence]["min"], 4)  # 최소 횟수 0.55, 한 번 더 맞을 때마다 +0.1
    c -= 0.1 * s.missing + 0.5 * (1 - s.purity) + 0.05 * s.jitter
    if len({t.amount for t in s.hits}) > 1:
        c -= 0.05
    return round(min(max(c, 0.05), 0.99), 2)


# ---------- 탐지 ----------

def _load(conn: sqlite3.Connection) -> dict[str, list[Tx]]:
    by_key: dict[str, list[Tx]] = {}
    rows = conn.execute(
        "SELECT id, occurred_on, amount, merchant, merchant_key, memo, type, transfer_kind FROM transactions "
        "WHERE recurring_id IS NULL AND amount > 0 AND merchant_key != '' AND type IN ('expense', 'transfer') "
        "ORDER BY occurred_on, id"
    )
    for r in rows:
        if r["transfer_kind"] == "internal" and (r["memo"].startswith("카드대금") or loan_counterparty(conn, r["merchant"])):
            continue  # 카드대금(카드 사용분과 중복)·빌린 돈 입금은 반복 지출이 아니다
        by_key.setdefault(r["merchant_key"], []).append(
            Tx(r["id"], date.fromisoformat(r["occurred_on"]), r["amount"], r["merchant"], r["memo"], r["type"],
               r["transfer_kind"]))
    return by_key


def _covered(s: Series, item_keywords: list[list[str]], linked: dict[int, set[date]]) -> bool:
    texts = [f"{t.merchant} {t.memo}".lower() for t in s.hits]
    for keywords in item_keywords:
        if keywords and sum(any(k in text for k in keywords) for text in texts) * 2 >= len(texts):
            return True  # 이미 등록된 정기지출 (금액만 다름)
    mirrored = sum(
        any(abs((t.on - d).days) <= 1 for d in linked.get(t.amount, ())) for t in s.hits
    )
    return mirrored * 2 >= len(s.hits)  # 이미 연결된 이체의 반대쪽 기록


def detect(conn: sqlite3.Connection, today: date | None = None) -> list[Series]:
    today = today or date.today()
    latest = conn.execute("SELECT MAX(occurred_on) FROM transactions").fetchone()[0]
    ref = min(today, date.fromisoformat(latest)) if latest else today
    item_keywords = [split_keywords(r[0]) for r in conn.execute("SELECT match_keyword FROM recurring_items")]
    linked: dict[int, set[date]] = {}
    for r in conn.execute("SELECT amount, occurred_on FROM transactions WHERE recurring_id IS NOT NULL"):
        linked.setdefault(r[0], set()).add(date.fromisoformat(r[1]))

    found = []
    for key, txs in _load(conn).items():
        for group in _amount_groups(txs):
            if len(group) < RULES["monthly"]["min"]:
                continue
            s = _best_series(key, group)
            if (s and s.same_amount >= MIN_SAME_AMOUNT and confidence(s) >= MIN_CONFIDENCE and _alive(s, ref)
                    and not _covered(s, item_keywords, linked)):
                found.append(s)
    return sorted(found, key=lambda s: (-confidence(s), s.merchant_key))


# ---------- 제안 내용 ----------

def _crowded(s: Series, payday: int) -> bool:
    """매월 결제를 기간에 배정했을 때(출금일 직전에 미리 나간 결제는 다음 기간 몫) 한 기간에 두 번 잡히는지."""
    assigned = assign_periods([(i, t.on) for i, t in enumerate(s.hits)], s.anchor, payday)
    return len({p.start for p in assigned.values()}) < len(assigned)


def _keyword(merchants: list[str]) -> str:
    """매칭 키워드: 가맹점 표기들의 공통 앞부분 (모든 결제의 가맹점에 들어 있어야 자동 매칭된다)."""
    names = [m.lower().replace(",", " ").strip() for m in merchants]
    prefix = commonprefix(names).strip()
    return prefix if len(prefix) >= 2 else Counter(names).most_common(1)[0][0]


def _group_for(conn: sqlite3.Connection, s: Series) -> int | None:
    groups = conn.execute("SELECT id, name, kind FROM recurring_groups ORDER BY sort_order, id").fetchall()
    last = s.hits[-1]
    if last.transfer_kind == "internal":  # 내 계좌로 매달 보내는 돈 = 적금·투자 같은 저금
        picks = [g for g in groups if g["kind"] == "saving"]
    elif last.type == "expense" and s.amount <= 30000:  # 작은 금액의 정기 카드 결제는 대부분 구독
        picks = [g for g in groups if g["name"] == "구독"]
    else:
        picks = []
    picks = (picks or [g for g in groups if g["name"] == "기타"] or [g for g in groups if g["kind"] == "expense"]
             or groups)
    return picks[0]["id"] if picks else None


def _similar_item(conn: sqlite3.Connection, amount: int) -> dict | None:
    """금액이 ±5% 안인 정기지출 — 키워드가 비었거나 맞지 않아 연결되지 못한 같은 항목일 수 있다."""
    rows = conn.execute(
        "SELECT id, name, group_id, icon, amount, day_of_month, match_keyword, memo, active, sort_order "
        "FROM recurring_items WHERE active = 1 AND amount > 0"
    ).fetchall()
    near = [r for r in rows if abs(r["amount"] - amount) <= r["amount"] * AMOUNT_TOLERANCE]
    if not near:
        return None
    best = min(near, key=lambda r: (abs(r["amount"] - amount), r["match_keyword"] != "", r["id"]))
    return {**dict(best), "active": bool(best["active"])}


def describe(conn: sqlite3.Connection, s: Series) -> dict:
    """후보 한 건의 근거와 등록 제안 (DB stats_json 에 그대로 남긴다)."""
    payday = int(get_settings(conn)["payday"])
    last = s.hits[-1]
    amounts = [t.amount for t in s.hits]
    name = display_name(Counter(t.merchant for t in s.hits).most_common(1)[0][0]) or s.merchant_key
    keyword = _keyword([t.merchant for t in s.hits])
    warnings = []
    if s.cadence == "weekly":
        warnings.append("정기지출은 한 기간에 한 건만 연결돼요. 매주 나가는 지출은 첫 건만 확인되고 나머지는 변동비로 남아요.")
    if len(set(amounts)) > 1:
        warnings.append(f"금액이 {min(amounts):,}~{max(amounts):,}원으로 조금씩 달라요. 자동 매칭은 금액이 같을 때만 돼서, "
                        "금액이 다른 달은 가계부에서 그 거래의 정기지출을 직접 골라 주세요.")
    if s.cadence == "monthly" and _crowded(s, payday):
        warnings.append(f"결제일이 수입일({payday}일) 앞뒤로 오가서 어떤 기간엔 두 번 잡히고 어떤 기간은 비어요. "
                        "빈 기간은 미확인으로 보일 수 있어요.")
    return {
        "merchant": name,
        "amount": s.amount,
        "keyword": keyword,
        "anchor": s.anchor,
        "occurrences": len(s.hits),
        "first_on": s.hits[0].on.isoformat(),
        "last_on": last.on.isoformat(),
        "next_on": _due(s.cadence, s.last_slot + 1, s.anchor).isoformat(),
        "confidence": confidence(s),
        "stats": {
            "tx_ids": [t.id for t in s.hits],
            "dates": [t.on.isoformat() for t in s.hits],
            "amount_min": min(amounts),
            "amount_max": max(amounts),
            "missing": s.missing,
            "purity": round(s.purity, 2),
            "jitter": round(s.jitter, 2),
            "type": last.type,
            "transfer_kind": last.transfer_kind,
            "warnings": warnings,
            "suggestion": {
                "name": name,
                "group_id": _group_for(conn, s),
                "icon": "",
                "amount": s.amount,
                "day_of_month": s.anchor if s.cadence == "monthly" else None,
                "match_keyword": keyword,
                "memo": f"매주 {WEEKDAYS[s.anchor]}요일" if s.cadence == "weekly" else "",
                "active": True,
                "sort_order": 99,
            },
            "similar_item": _similar_item(conn, s.amount),
        },
    }


# ---------- 후보 저장 ----------

def _same(row: sqlite3.Row, s: Series, amount: int) -> bool:
    return (row["merchant_key"] == s.merchant_key and row["cadence"] == s.cadence
            and abs(row["amount"] - amount) <= row["amount"] * AMOUNT_TOLERANCE)


def candidate_dict(row: sqlite3.Row) -> dict:
    stats = json.loads(row["stats_json"])
    return {k: row[k] for k in row.keys() if k != "stats_json"} | stats


def sync(conn: sqlite3.Connection, today: date | None = None) -> None:
    """탐지 결과로 후보 표를 맞춘다: 새 후보 추가, 대기 중 후보 갱신, 더는 안 보이는 대기 후보 삭제.
    수락·거절한 후보는 그대로 둔다 (거절한 반복은 다시 탐지돼도 제안하지 않는다)."""
    with _SYNC_LOCK:
        rows = conn.execute("SELECT * FROM recurring_candidates").fetchall()
        seen: set[int] = set()
        for s in detect(conn, today):
            d = describe(conn, s)
            row = next((r for r in rows if r["id"] not in seen and _same(r, s, d["amount"])), None)
            values = (d["merchant"], d["amount"], d["keyword"], d["anchor"], d["occurrences"], d["first_on"],
                      d["last_on"], d["next_on"], d["confidence"], json.dumps(d["stats"], ensure_ascii=False))
            if row is None:
                cur = conn.execute(
                    "INSERT INTO recurring_candidates (merchant_key, cadence, merchant, amount, keyword, anchor, "
                    "occurrences, first_on, last_on, next_on, confidence, stats_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (s.merchant_key, s.cadence, *values),
                )
                seen.add(cur.lastrowid)
                continue
            seen.add(row["id"])
            if row["status"] == "pending":
                conn.execute(
                    "UPDATE recurring_candidates SET merchant = ?, amount = ?, keyword = ?, anchor = ?, occurrences = ?, "
                    "first_on = ?, last_on = ?, next_on = ?, confidence = ?, stats_json = ?, "
                    "updated_at = datetime('now', 'localtime') WHERE id = ? AND status = 'pending'",
                    (*values, row["id"]),
                )
        # 읽은 뒤 다른 요청에서 수락·거절했을 수 있으니 상태를 다시 확인하며 지운다
        stale = [r["id"] for r in rows if r["status"] == "pending" and r["id"] not in seen]
        conn.executemany("DELETE FROM recurring_candidates WHERE id = ? AND status = 'pending'", [(i,) for i in stale])
        conn.commit()


def link_series(conn: sqlite3.Connection, item_id: int, tx_ids: list[int], link_past: bool) -> int:
    """후보의 결제를 정기지출에 연결한다. 기간마다 한 건(이미 연결된 기간은 건너뜀), link_past 가 아니면 이번 기간만.
    연결된 거래는 변동비 집계에서 빠지고 '분류 필요'도 풀린다 (자동 매칭과 같다)."""
    now = current_period(conn)
    day = conn.execute("SELECT day_of_month FROM recurring_items WHERE id = ?", (item_id,)).fetchone()[0]
    placeholders = ",".join("?" * len(tx_ids)) or "NULL"
    rows = conn.execute(
        f"SELECT id, occurred_on FROM transactions WHERE id IN ({placeholders}) AND recurring_id IS NULL "
        "ORDER BY occurred_on, id",
        tx_ids,
    ).fetchall()
    linked = 0
    for r in rows:
        # 자동 매칭과 같은 배정: 출금일 직전에 미리 나간 결제는 다음 기간 몫, 이미 결제가 있는 기간이면 건너뜀
        period = link_period(conn, item_id, day, date.fromisoformat(r["occurred_on"]))
        if period is None or (not link_past and period != now):
            continue
        conn.execute("UPDATE transactions SET recurring_id = ?, needs_review = 0 WHERE id = ?", (item_id, r["id"]))
        linked += 1
    return linked
