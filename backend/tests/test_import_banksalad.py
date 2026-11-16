"""뱅크샐러드 가져오기 — 테스트용으로 만든 가짜 엑셀만 쓴다 (실제 내보내기 파일은 쓰지 않는다)."""

import io
import zipfile
from datetime import datetime, time

import openpyxl
import pytest

from app.core.db import connect, init_db
from app.core.migrations import MIGRATIONS
from app.importer.banksalad import read_rows

HEADER = ["날짜", "시간", "타입", "대분류", "소분류", "내용", "금액", "화폐", "결제수단", "메모"]


def xlsx(rows: list[list], header=HEADER, sheet="가계부 내역") -> bytes:
    wb = openpyxl.Workbook()
    wb.active.title = "뱅샐현황"
    ws = wb.create_sheet(sheet)
    ws.append(header)
    for r in rows:
        d, t, *rest = r
        ws.append([datetime.fromisoformat(d), time.fromisoformat(t), *rest])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


ROWS = [
    ["2026-10-01", "09:00:00", "지출", "식비", "카페", "스타벅스 강남점", -4500, "KRW", "현대카드", ""],
    ["2026-10-01", "12:00:00", "지출", "생활", "마트", "이마트 역삼점", -32000, "KRW", "현대카드", ""],
    ["2026-10-02", "10:00:00", "지출", "미분류", "미분류", "블루보틀 성수", -6000, "KRW", "현대카드", ""],
    ["2026-10-02", "11:00:00", "지출", "문화/여가", "게임", "스팀", -20000, "KRW", "현대카드", ""],
    ["2026-10-03", "11:00:00", "지출", "문화/여가", "게임", "스팀", 20000, "KRW", "현대카드", ""],      # 취소 → 상쇄
    ["2026-10-03", "13:00:00", "지출", "식비", "배달", "배달의민족", 3000, "KRW", "현대카드", ""],      # 짝 없는 환불
    ["2026-10-04", "09:00:00", "수입", "급여", "급여", "(주)회사", 3000000, "KRW", "우리통장", ""],
    ["2026-10-04", "09:00:01", "수입", "미분류", "미분류", "이자", 0, "KRW", "우리통장", ""],           # 0원 → 건너뜀
    ["2026-10-04", "09:00:02", "수입", "미분류", "미분류", "정정", -500, "KRW", "우리통장", ""],         # 음수 수입
    ["2026-10-05", "08:00:00", "이체", "내계좌이체", "미분류", "토스뱅크", -100000, "KRW", "우리통장", ""],
    ["2026-10-05", "08:00:01", "이체", "내계좌이체", "미분류", "우리통장", 100000, "KRW", "토스뱅크", ""],
    ["2026-10-06", "08:00:00", "이체", "카드대금", "미분류", "현대카드", -500000, "KRW", "우리통장", ""],
    ["2026-10-07", "08:00:00", "이체", "이체", "미분류", "김철수", -30000, "KRW", "우리통장", ""],       # 타 계좌 출금
    ["2026-10-07", "09:00:00", "이체", "이체", "미분류", "박영희", 15000, "KRW", "우리통장", ""],        # 남에게서 입금
    ["2026-10-07", "10:00:00", "이체", "투자", "미분류", "미래에셋 ISA", -300000, "KRW", "우리통장", ""], # 정기지출 매칭
    ["2026-10-08", "10:00:00", "이체", "저축", "미분류", "적금 만기", 1000000, "KRW", "우리통장", ""],   # 내 적금에서 돌아옴
    ["2026-10-08", "11:00:00", "이체", "이체", "미분류", "홍길동", 50000, "KRW", "카카오뱅크", ""],      # 내 이름 → 내 계좌
    ["2026-10-08", "12:00:00", "지출", "식비", "해외", "Amazon", -10, "USD", "해외카드", ""],           # 외화 → 건너뜀
    ["2026-10-08", "12:30:00", "지출", "금융", "카드", "삼성카드", -400000, "KRW", "우리 주거래 통장", ""],  # 지출로 분류된 카드대금
    ["2026-10-08", "12:40:00", "지출", "금융", "카드", "KICC(카드)", -12900, "KRW", "네이버페이", ""],      # 카드 결제는 지출
    ["2026-10-08", "13:00:00", "이체", "이체", "미분류", "홍부모", 5000000, "KRW", "우리통장", ""],      # 빌린 돈 입금
    ["2026-10-08", "14:00:00", "이체", "이체", "미분류", "홍부모", -300000, "KRW", "우리통장", ""],      # 갚는 출금
]


def cat(client, name):
    return next(c["id"] for c in client.get("/api/categories").json() if c["name"] == name)


def upload(client, data: bytes, dry_run=False, name="export.xlsx"):
    return client.post("/api/imports/banksalad", params={"dry_run": dry_run}, files={"file": (name, data)})


@pytest.fixture
def ready(client):
    client.put("/api/settings", json={"payday": 1, "loan_counterparties": "홍부모"})
    client.post("/api/accounts", json={"name": "홍길동 다른 은행", "keyword": "홍길동"})
    item = next(r for r in client.get("/api/recurring-items").json() if r["name"] == "ISA 자동이체")
    client.put(f"/api/recurring-items/{item['id']}", json={**{k: item[k] for k in (
        "name", "group_id", "icon", "memo", "active", "sort_order")}, "amount": 300000, "day_of_month": 7, "match_keyword": "ISA"})
    # '블루보틀'은 사용자 규칙으로 식비
    client.post("/api/transactions", json={"occurred_on": "2026-09-01", "type": "expense", "amount": 1,
                                           "merchant": "블루보틀 성수", "category_id": cat(client, "식비"),
                                           "category_source": "user"})
    return client


def by_merchant(client, merchant):
    txs = client.get("/api/transactions", params={"on": "2026-10-05"}).json()["transactions"]
    return [t for t in txs if t["merchant"] == merchant and t["source"] == "import"]


def test_dry_run_does_not_write(ready):
    rep = upload(ready, xlsx(ROWS), dry_run=True).json()
    assert rep["dry_run"] is True and rep["rows"] == len(ROWS)
    assert rep["actions"] == {"insert": 18, "cancel_pair": 2, "skip_zero": 1, "skip_currency": 1}
    assert ready.get("/api/imports").json() == []


def test_import_maps_every_case(ready):
    rep = upload(ready, xlsx(ROWS)).json()
    assert rep["inserted"] == 18 and rep["actions"]["cancel_pair"] == 2
    food, coffee = cat(ready, "식비"), cat(ready, "커피")

    star = by_merchant(ready, "스타벅스 강남점")[0]                                    # 식비/카페 → 커피
    assert (star["type"], star["category_id"], star["category_source"], star["occurred_time"]) == ("expense", coffee, "import", "09:00:00")
    assert by_merchant(ready, "이마트 역삼점")[0]["category_id"] == food              # 생활/마트 → 식비
    blue = by_merchant(ready, "블루보틀 성수")[0]
    assert (blue["category_id"], blue["category_source"]) == (food, "rule")           # 미분류 → 내 규칙
    assert by_merchant(ready, "스팀") == []                                           # 결제·취소 상쇄
    refund = by_merchant(ready, "배달의민족")[0]
    assert (refund["type"], refund["memo"], refund["category_id"]) == ("refund", "부분 환불·취소", food)
    assert by_merchant(ready, "(주)회사")[0]["type"] == "income"
    assert by_merchant(ready, "이자") == []
    assert by_merchant(ready, "정정")[0]["type"] == "expense"
    assert {t["transfer_kind"] for t in by_merchant(ready, "토스뱅크") + by_merchant(ready, "우리통장")} == {"internal"}
    card = by_merchant(ready, "현대카드")[0]
    assert card["transfer_kind"] == "internal" and "중복" in card["memo"]
    kim = by_merchant(ready, "김철수")[0]
    assert (kim["transfer_kind"], kim["needs_review"]) == ("external", True)
    friend = by_merchant(ready, "박영희")[0]
    assert (friend["type"], friend["memo"]) == ("refund", "정산 입금")    # 1/n 정산은 수입이 아니다
    isa = by_merchant(ready, "미래에셋 ISA")[0]
    assert isa["recurring_name"] == "ISA 자동이체" and isa["needs_review"] is False
    assert by_merchant(ready, "적금 만기")[0]["transfer_kind"] == "internal"
    assert by_merchant(ready, "홍길동")[0]["transfer_kind"] == "internal"            # 내 계좌 설정
    assert by_merchant(ready, "Amazon") == []
    assert by_merchant(ready, "삼성카드")[0]["transfer_kind"] == "internal"
    kicc = by_merchant(ready, "KICC(카드)")[0]
    assert (kicc["type"], kicc["category_id"]) == ("expense", cat(ready, "기타"))
    loan = sorted(by_merchant(ready, "홍부모"), key=lambda t: t["occurred_time"])
    assert (loan[0]["transfer_kind"], loan[0]["memo"]) == ("internal", "빌린 돈 (수입 아님)")    # 받은 돈은 ±0
    assert loan[1]["transfer_kind"] == "external"                                             # 갚는 돈은 그대로
    assert rep["recurring_matched"] == 1 and rep["filled_by_rule"] == 1


def test_reimport_is_idempotent_and_undo_removes_batch(ready):
    first = upload(ready, xlsx(ROWS)).json()
    again = upload(ready, xlsx(ROWS)).json()
    assert again["inserted"] == 0 and again["actions"]["duplicate"] == 18

    # 뱅크샐러드에서 분류만 바꿔 다시 내보내도 같은 거래로 본다
    changed = [r[:3] + ["생활", "편의점"] + r[5:] if r[5] == "스타벅스 강남점" else r for r in ROWS]
    assert upload(ready, xlsx(changed)).json()["inserted"] == 0

    batches = ready.get("/api/imports").json()
    assert batches[-1]["id"] == first["batch_id"] and batches[-1]["tx_count"] == 18
    assert ready.delete(f"/api/imports/{first['batch_id']}").json() == {"deleted": 18}
    assert by_merchant(ready, "스타벅스 강남점") == []
    assert ready.delete(f"/api/imports/{first['batch_id']}").status_code == 404


def test_zip_wrapper_and_bad_files(ready):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("2025-10-08~2026-10-08.xlsx", xlsx(ROWS[:2]))
    assert upload(ready, buf.getvalue(), name="export.zip").json()["inserted"] == 2

    assert upload(ready, b"not a spreadsheet").status_code == 400
    assert "시트" in upload(ready, xlsx(ROWS, sheet="다른 시트")).json()["detail"]
    assert "열 구성" in upload(ready, xlsx([], header=["날짜", "금액"])).json()["detail"]


def test_identical_rows_in_one_file_get_distinct_ids():
    same = ["2026-10-01", "09:00:00", "지출", "식비", "카페", "자판기", -1000, "KRW", "현금", ""]
    rows = read_rows(xlsx([same, same]))
    assert len({r.external_id for r in rows}) == 2


def test_v7_rebuild_keeps_existing_transactions():
    conn = connect()
    conn.execute("PRAGMA foreign_keys = OFF")
    for i, sql in enumerate(MIGRATIONS[:6], start=1):
        conn.executescript(f"BEGIN; {sql} PRAGMA user_version = {i}; COMMIT;")
    conn.execute("INSERT INTO transactions (occurred_on, type, amount, merchant, source) "
                 "VALUES ('2026-10-01', 'expense', 1000, '기존 거래', 'image')")
    conn.commit()
    conn.close()
    init_db()
    with connect() as conn:
        row = conn.execute("SELECT merchant, source, occurred_time, external_id FROM transactions").fetchone()
        assert tuple(row) == ("기존 거래", "image", None, None)
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
