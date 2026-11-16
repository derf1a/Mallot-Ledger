"""뱅크샐러드 '가계부 내보내기' 엑셀 가져오기.

엑셀의 '가계부 내역' 시트(날짜·시간·타입·대분류·소분류·내용·금액·화폐·결제수단·메모)를 이 앱의 거래로 바꾼다.

매핑 규칙
- 지출(−) → 지출. 대분류(+소분류)를 이 앱의 변동비 카테고리로 매핑, 미분류는 비워 두고 내 가맹점 규칙이 채운다.
- 지출(+) → 결제 취소·환불. 같은 내용·금액의 원거래(31일 이내)와 짝이 맞으면 둘 다 상쇄(가져오지 않음),
  짝이 없으면 부분 환불로 보고 정산·환불(refund, 같은 카테고리)로 기록한다.
- 수입(+) → 수입, 수입(−) → 지출(수입 취소), 0원은 건너뛴다.
- 이체
  - 내계좌이체, 카드대금 → 내 계좌 간 이체(±0). 카드대금은 카드 사용 건이 이미 지출로 들어와 있어 지출로 세면 이중 집계다.
  - 뱅크샐러드가 카드대금을 '지출·금융·카드'로 분류하는 경우도 있다: 은행 계좌에서 카드사로 나간 돈이면 같은 이유로 ±0.
  - 저축·투자·현금의 입금(+), 상대가 '내 계좌'(설정)인 이체 → 내 계좌 간 이체(±0)
  - 그 밖의 출금(−) → 타 계좌 이체 (정기지출 자동 매칭 대상, 안 맞으면 '분류 필요')
  - 설정 > '빌린 돈을 받는 상대'에게서 받은 입금 → ±0 (빌린 돈은 수입이 아님. 갚는 출금은 정기지출 매칭 대상)
  - 그 밖의 입금(+) → 정산·환불 (대부분 1/n 정산: 수입이 아니라 변동비에서 빠지는 돈)
- 다시 가져와도 중복되지 않도록 원본 행마다 external_id(날짜·시각·타입·내용·금액·결제수단의 해시)를 둔다.
  뱅크샐러드에서 분류를 바꿔도 같은 거래로 인식하도록 대분류·소분류는 키에 넣지 않는다.
- 한 번의 가져오기는 import_batches 한 행이며, 지우면 그때 들어온 거래가 함께 지워진다(되돌리기).
"""

import hashlib
import io
import json
import sqlite3
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, time

import openpyxl

from app.ledger.rules import normalize
from app.ledger.schemas import TransactionIn
from app.ledger.settings import is_own_account, loan_counterparty

SHEET = "가계부 내역"
HEADER = ("날짜", "시간", "타입", "대분류", "소분류", "내용", "금액", "화폐", "결제수단", "메모")
CANCEL_WINDOW_DAYS = 31

# 뱅크샐러드 대분류 → 이 앱 카테고리 이름 (이 앱 기본 카테고리 정의 기준: 식비에 식료품 포함·카페는 커피로,
# 생활비에 교통·공과금 포함)
CATEGORY_MAP: dict[str, str | None] = {
    "식비": "식비",
    "카페/간식": "커피",
    "생활": "생활비",
    "교통": "생활비",
    "자동차": "생활비",
    "주거/통신": "생활비",
    "의료/건강": "생활비",
    "뷰티/미용": "생활비",
    "교육/학습": "생활비",
    "자녀/육아": "생활비",
    "반려동물": "생활비",
    "온라인쇼핑": "생활비",
    "문화/여가": "여가·유흥",
    "술/유흥": "여가·유흥",
    "쇼핑": "여가·유흥",
    "여행/숙박": "여가·유흥",
    "금융": "기타",
    "경조/선물": "기타",
    "미분류": None,
}
# 소분류가 대분류보다 우선하는 경우
SUBCATEGORY_MAP: dict[tuple[str, str], str] = {
    ("생활", "마트"): "식비",       # 장보기 = 식료품
    ("생활", "식재료"): "식비",
    ("식비", "카페"): "커피",
}
INTERNAL_TRANSFER = {"내계좌이체", "카드대금"}
CARD_ISSUER_HINTS = ("카드",)          # 내용에 카드사 이름이 들어 있으면
BANK_ACCOUNT_HINTS = ("통장", "계좌")   # 결제수단이 은행 계좌이면
INTERNAL_WHEN_INCOMING = {"저축", "투자", "현금"}


class ImportError_(Exception):  # noqa: N801 — 내장 ImportError 와 구분
    """사용자에게 보여줄 가져오기 오류."""


@dataclass
class Row:
    line: int            # 엑셀 행 번호 (헤더 = 1)
    occurred_on: date
    occurred_time: str | None
    kind: str            # 지출 / 수입 / 이체
    major: str
    minor: str
    content: str
    amount: int          # 부호 포함
    currency: str
    method: str
    memo: str
    external_id: str = ""


@dataclass
class Planned:
    row: Row
    action: str          # insert / cancel_pair / skip_zero / skip_currency / duplicate
    tx: TransactionIn | None = None
    note: str = ""


@dataclass
class Plan:
    items: list[Planned] = field(default_factory=list)
    period: tuple[str, str] | None = None


# ---------- 읽기 ----------

def _xlsx_bytes(data: bytes) -> bytes:
    """xlsx 또는 뱅크샐러드가 보내 주는 zip(안에 xlsx 하나)을 받아 xlsx 바이트를 돌려준다."""
    if not zipfile.is_zipfile(io.BytesIO(data)):
        raise ImportError_("엑셀(xlsx) 또는 뱅크샐러드 압축(zip) 파일이 아닙니다")
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = zf.namelist()
        if "[Content_Types].xml" in names:  # xlsx 자체도 zip 이다
            return data
        inner = [n for n in names if n.lower().endswith(".xlsx")]
        if not inner:
            raise ImportError_("압축 파일 안에 xlsx 가 없습니다")
        try:
            return zf.read(inner[0])
        except RuntimeError:  # 암호가 걸린 zip
            raise ImportError_("압축 파일에 암호가 걸려 있어요. 압축을 푼 xlsx 를 올려 주세요") from None


def _time_str(v) -> str | None:
    if isinstance(v, time):
        return v.strftime("%H:%M:%S")
    if isinstance(v, datetime):
        return v.strftime("%H:%M:%S")
    if isinstance(v, str) and v.strip():
        return v.strip()[:8]
    return None


def _date(v) -> date:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v).strip()[:10])


def read_rows(data: bytes) -> list[Row]:
    wb = openpyxl.load_workbook(io.BytesIO(_xlsx_bytes(data)), read_only=True, data_only=True)
    if SHEET not in wb.sheetnames:
        raise ImportError_(f"'{SHEET}' 시트가 없습니다 — 뱅크샐러드 가계부 내보내기 파일인지 확인해 주세요")
    it = wb[SHEET].iter_rows(values_only=True)
    header = tuple(str(c).strip() if c is not None else "" for c in next(it, ()))
    if header[: len(HEADER)] != HEADER:
        raise ImportError_(f"열 구성이 예상과 다릅니다: {header[:len(HEADER)]}")
    rows: list[Row] = []
    for line, r in enumerate(it, start=2):
        if not r or r[0] is None:
            continue
        try:
            rows.append(Row(
                line=line,
                occurred_on=_date(r[0]),
                occurred_time=_time_str(r[1]),
                kind=str(r[2] or "").strip(),
                major=str(r[3] or "미분류").strip(),
                minor=str(r[4] or "미분류").strip(),
                content=str(r[5] or "").strip(),
                amount=int(round(float(r[6] or 0))),
                currency=str(r[7] or "KRW").strip(),
                method=str(r[8] or "").strip(),
                memo=str(r[9] or "").strip(),
            ))
        except (TypeError, ValueError) as e:
            raise ImportError_(f"{line}행을 읽지 못했습니다: {e}") from None
    _assign_external_ids(rows)
    return rows


def _assign_external_ids(rows: list[Row]) -> None:
    seen: Counter[str] = Counter()
    for r in rows:
        base = "|".join([r.occurred_on.isoformat(), r.occurred_time or "", r.kind, r.content, str(r.amount), r.method])
        seen[base] += 1  # 같은 초에 같은 거래가 여러 번이면 순번으로 구분
        r.external_id = "banksalad:" + hashlib.sha1(f"{base}#{seen[base]}".encode()).hexdigest()[:24]


# ---------- 계획 ----------

def _category_id(conn: sqlite3.Connection, row: Row) -> int | None:
    name = SUBCATEGORY_MAP.get((row.major, row.minor), CATEGORY_MAP.get(row.major))
    if not name:
        return None
    found = conn.execute("SELECT id FROM categories WHERE name = ?", (name,)).fetchone()
    return found[0] if found else None


def _base(row: Row, **kw) -> dict:
    return {
        "occurred_on": row.occurred_on.isoformat(),
        "occurred_time": row.occurred_time,
        "amount": abs(row.amount),
        "merchant": row.content,
        "payment_method": row.method,
        "memo": row.memo,
        "source": "import",
        **kw,
    }


def _pair_cancellations(rows: list[Row]) -> set[int]:
    """지출(+)과 같은 내용·금액의 지출(−)을 짝지어 상쇄할 행 번호들을 돌려준다."""
    out: set[int] = set()
    negatives = [r for r in rows if r.kind == "지출" and r.amount < 0]
    for p in (r for r in rows if r.kind == "지출" and r.amount > 0):
        candidates = [
            n for n in negatives
            if n.line not in out and n.content == p.content and -n.amount == p.amount
            and abs((p.occurred_on - n.occurred_on).days) <= CANCEL_WINDOW_DAYS
        ]
        if candidates:
            # 같은 결제수단, 가까운 날짜 순으로 고른다
            best = min(candidates, key=lambda n: (n.method != p.method, abs((p.occurred_on - n.occurred_on).days)))
            out.update({p.line, best.line})
    return out


def plan(conn: sqlite3.Connection, rows: list[Row]) -> Plan:
    cancelled = _pair_cancellations(rows)
    existing = {r[0] for r in conn.execute("SELECT external_id FROM transactions WHERE external_id IS NOT NULL")}
    result = Plan()
    if rows:
        days = [r.occurred_on for r in rows]
        result.period = (min(days).isoformat(), max(days).isoformat())
    # 오래된 것부터 — 정기지출 자동 매칭이 기간의 첫 거래를 잡도록
    for row in sorted(rows, key=lambda r: (r.occurred_on, r.occurred_time or "", r.line)):
        if row.currency != "KRW":
            result.items.append(Planned(row, "skip_currency", note=f"{row.currency} 거래는 아직 지원하지 않음"))
        elif row.amount == 0:
            result.items.append(Planned(row, "skip_zero"))
        elif row.line in cancelled:
            result.items.append(Planned(row, "cancel_pair", note="결제 취소 — 원거래와 상쇄"))
        elif row.external_id in existing:
            result.items.append(Planned(row, "duplicate", note="이미 가져온 거래"))
        else:
            tx, note = _map(conn, row)
            result.items.append(Planned(row, "insert", tx, note))
    return result


def _is_card_bill(row: Row) -> bool:
    """은행 계좌에서 카드사로 나간 돈 = 카드대금."""
    return (row.major == "금융" and row.minor == "카드"
            and any(h in row.content for h in CARD_ISSUER_HINTS)
            and any(h in row.method for h in BANK_ACCOUNT_HINTS))


def _map(conn: sqlite3.Connection, row: Row) -> tuple[TransactionIn, str]:
    incoming = row.amount > 0
    if row.kind == "지출" and not incoming and _is_card_bill(row):
        return (TransactionIn(**_base(row, type="transfer", transfer_kind="internal",
                                      memo=row.memo or "카드대금 — 카드 사용분과 중복이라 ±0")),
                "지출·금융·카드 중 카드대금 → 내 계좌 이체")
    if row.kind == "지출":
        if incoming:  # 부분 환불: 원래 카테고리 예산에서 빠지도록 같은 카테고리로
            cat = _category_id(conn, row)
            return (TransactionIn(**_base(row, type="refund", memo=row.memo or "부분 환불·취소", category_id=cat,
                                          category_source="import" if cat else None)),
                    "짝 없는 결제 취소 → 정산·환불")
        cat = _category_id(conn, row)
        return TransactionIn(**_base(row, type="expense", category_id=cat,
                                     category_source="import" if cat else None)), ""
    if row.kind == "수입":
        if incoming:
            return TransactionIn(**_base(row, type="income")), ""
        return TransactionIn(**_base(row, type="expense", memo=row.memo or "수입 취소")), "음수 수입 → 지출(수입 취소)"
    if row.kind == "이체":
        own = is_own_account(conn, row.content)  # 설정 > 내 계좌에 등록한 이름·키워드 (예: 내 이름으로 받은 이체)
        if row.major in INTERNAL_TRANSFER or own or (incoming and row.major in INTERNAL_WHEN_INCOMING):
            memo = row.memo or ("카드대금 — 카드 사용분과 중복이라 ±0" if row.major == "카드대금" else "")
            return TransactionIn(**_base(row, type="transfer", transfer_kind="internal", memo=memo)), "내 계좌 간 이체"
        if incoming and loan_counterparty(conn, row.content):
            return TransactionIn(**_base(row, type="transfer", transfer_kind="internal",
                                         memo=row.memo or "빌린 돈 (수입 아님)")), "빌린 돈 입금 → ±0"
        if incoming:  # 남에게서 받은 이체 = 대부분 1/n 정산 → 수입이 아니라 변동비에서 빠지는 돈
            return TransactionIn(**_base(row, type="refund", memo=row.memo or "정산 입금")), "이체 입금 → 정산·환불"
        return TransactionIn(**_base(row, type="transfer", transfer_kind="external",
                                     memo=row.memo or (row.major if row.major not in ("이체", "미분류") else ""))), "타 계좌 이체"
    raise ImportError_(f"{row.line}행: 알 수 없는 타입 '{row.kind}'")


# ---------- 실행 ----------

INSERT_COLUMNS = ("occurred_on", "occurred_time", "type", "transfer_kind", "amount", "merchant", "merchant_key",
                  "category_id", "category_source", "recurring_id", "payment_method", "memo", "needs_review",
                  "source", "import_batch_id", "external_id")


def summarize(conn: sqlite3.Connection, p: Plan) -> dict:
    actions = Counter(i.action for i in p.items)
    inserts = [i for i in p.items if i.action == "insert"]
    cat_names = {r[0]: r[1] for r in conn.execute("SELECT id, name FROM categories")}
    mapping: Counter[str] = Counter()
    for i in inserts:
        tx = i.tx
        assert tx is not None
        if tx.type == "expense":
            target = cat_names.get(tx.category_id, "미분류(규칙으로 채움)")
        elif tx.type == "transfer":
            target = "내 계좌 이체(±0)" if tx.transfer_kind == "internal" else "타 계좌 이체"
        elif tx.type == "refund":
            target = "정산·환불(변동비 −)"
        else:
            target = "수입"
        mapping[f"{i.row.kind}·{i.row.major} → {target}"] += 1
    return {
        "rows": len(p.items),
        "period": {"from": p.period[0], "to": p.period[1]} if p.period else None,
        "actions": dict(actions),
        "by_type": dict(Counter(i.tx.type for i in inserts if i.tx)),
        "mapping": [{"rule": k, "count": v} for k, v in mapping.most_common()],
    }


def run_import(conn: sqlite3.Connection, data: bytes, file_name: str, dry_run: bool = False) -> dict:
    rows = read_rows(data)
    if not rows:
        raise ImportError_("가져올 거래가 없습니다")
    p = plan(conn, rows)
    report = summarize(conn, p)
    if dry_run:
        report["dry_run"] = True
        return report

    sha = hashlib.sha256(data).hexdigest()
    cur = conn.execute(
        "INSERT INTO import_batches (source, file_name, file_sha256, period_from, period_to) VALUES (?, ?, ?, ?, ?)",
        ("banksalad", file_name, sha, *(p.period or (None, None))),
    )
    batch_id = cur.lastrowid
    inserted = needs_review = recurring = by_rule = 0
    for item in p.items:
        if item.action != "insert" or item.tx is None:
            continue
        data_row = normalize(conn, item.tx)
        data_row.update(import_batch_id=batch_id, external_id=item.row.external_id)
        conn.execute(
            f"INSERT INTO transactions ({', '.join(INSERT_COLUMNS)}) VALUES ({', '.join('?' * len(INSERT_COLUMNS))})",
            [data_row.get(c) for c in INSERT_COLUMNS],
        )
        inserted += 1
        needs_review += bool(data_row["needs_review"])
        recurring += data_row["recurring_id"] is not None
        by_rule += data_row.get("category_source") == "rule"
    report.update(batch_id=batch_id, inserted=inserted, needs_review=needs_review, recurring_matched=recurring,
                  filled_by_rule=by_rule, dry_run=False)
    conn.execute("UPDATE import_batches SET stats_json = ? WHERE id = ?", (json.dumps(report, ensure_ascii=False), batch_id))
    conn.commit()
    return report


def undo_import(conn: sqlite3.Connection, batch_id: int) -> int:
    """가져오기 한 번을 되돌린다 (그때 들어온 거래를 모두 지운다). 지운 거래 수."""
    n = conn.execute("SELECT COUNT(*) FROM transactions WHERE import_batch_id = ?", (batch_id,)).fetchone()[0]
    cur = conn.execute("DELETE FROM import_batches WHERE id = ?", (batch_id,))
    if cur.rowcount == 0:
        raise ImportError_("가져오기 기록을 찾을 수 없습니다")
    conn.commit()
    return n
