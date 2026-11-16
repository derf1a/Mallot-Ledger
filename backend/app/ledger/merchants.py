"""가맹점 분류 규칙 (#2).

사용자가 고른 카테고리를 가맹점별로 기억해 다음 거래에 자동으로 적용한다.
- 규칙 출처: user(사용자가 직접 고름) / llm(AI 제안을 그대로 받아들임 — 약한 규칙, 사용자 규칙을 덮어쓰지 않음)
- 적용 순서: 정확히 같은 가맹점 → 비슷한 가맹점(가맹점 이름이 3글자 이상인 규칙 이름으로 시작) → (없으면) AI 추정
- 거래의 category_source: user / llm / rule — 화면에 분류 출처로 보여준다.

참고: Lesner et al., "Large Scale Personalized Categorization of Financial Transactions", AAAI 2019.
단일 사용자 앱이라 '개인 규칙 우선, 공통 지식(LLM)은 폴백' 구조만 가져왔다.
"""

import re
import sqlite3

_CORP = re.compile(r"\(주\)|㈜|주식회사|\(유\)|유한회사")
_BRACKETS = re.compile(r"\([^)]*\)|\[[^\]]*\]")
_BRANCH = re.compile(r"\s+(\S*점)$")  # "스타벅스 강남점" → "스타벅스"
_SPACES = re.compile(r"\s+")
# '~점'으로 끝나지만 지점명이 아니라 업종인 단어 — 지우면 '롯데 백화점'이 '롯데'가 되어 롯데리아·롯데마트까지 묶인다
_BUSINESS_TYPES = {"백화점", "편의점", "면세점", "대리점", "음식점", "매점", "상점", "서점", "할인점", "전문점", "판매점",
                   "아울렛점"}
# 비슷한 가맹점으로 볼 최소 규칙 키 길이. 2글자 키(롯데, 쿠팡)는 다른 업종 브랜드(롯데리아, 쿠팡이츠)와 겹친다
SIMILAR_MIN_LEN = 3


def merchant_key(name: str | None) -> str:
    """가맹점 이름을 규칙 비교용 키로 정규화한다. 지점명·법인 표기·괄호·공백을 없애고 소문자로."""
    if not name:
        return ""
    s = _BRACKETS.sub(" ", _CORP.sub(" ", name))
    s = _SPACES.sub(" ", s).strip().lower()
    m = _BRANCH.search(s)
    if m and m.group(1) not in _BUSINESS_TYPES and s[: m.start()]:
        s = s[: m.start()]
    return s.replace(" ", "")


def display_name(name: str | None) -> str:
    """화면·항목 이름용 가맹점 이름: 법인 표기만 지우고 공백을 정리한다 ('주식회사 우아한형제들' → '우아한형제들')."""
    return _SPACES.sub(" ", _CORP.sub(" ", name or "")).strip()


def is_similar_key(rule_key: str, key: str) -> bool:
    """규칙 키로 '비슷한 가맹점'인지: 규칙 키가 3글자 이상이고 가맹점 키가 그것으로 시작 (스타벅스 ↔ 스타벅스코리아)."""
    return len(rule_key) >= SIMILAR_MIN_LEN and key != rule_key and key.startswith(rule_key)


def _learnable(data: dict) -> bool:
    """규칙을 배우거나 적용할 수 있는 거래: 정기지출이 아닌 지출 / 타 계좌 이체."""
    return (
        bool(data.get("merchant_key"))
        and data.get("recurring_id") is None
        and (data["type"] == "expense" or data.get("transfer_kind") == "external")
    )


def find_rule(conn: sqlite3.Connection, key: str) -> sqlite3.Row | None:
    if not key:
        return None
    row = conn.execute("SELECT * FROM merchant_rules WHERE merchant_key = ?", (key,)).fetchone()
    if row:
        return row
    # 비슷한 가맹점: 가맹점 키가 규칙 키(3글자 이상)로 시작하면 (예: 규칙 '스타벅스' ↔ '스타벅스코리아'). 가장 긴 것 우선.
    # 중간에 들어 있는 것까지 허용하면 '롯데' 같은 짧은 키가 무관한 가맹점에 퍼진다.
    return conn.execute(
        "SELECT * FROM merchant_rules WHERE length(merchant_key) >= ? AND merchant_key != ? "
        "AND substr(?, 1, length(merchant_key)) = merchant_key ORDER BY length(merchant_key) DESC, hits DESC LIMIT 1",
        (SIMILAR_MIN_LEN, key, key),
    ).fetchone()


def apply_rule(conn: sqlite3.Connection, data: dict) -> bool:
    """카테고리가 비어 있으면 규칙으로 채운다. 사용자 규칙으로 채웠는지(= 이미 사람이 분류한 것과 같음)를 돌려준다."""
    if data.get("category_id") is not None:
        if data.get("category_source") == "rule":
            rule = find_rule(conn, data["merchant_key"])
            return bool(rule and rule["source"] == "user" and rule["category_id"] == data["category_id"])
        return False
    if not _learnable(data):
        return False
    rule = find_rule(conn, data["merchant_key"])
    if rule is None:
        return False
    data["category_id"] = rule["category_id"]
    data["category_source"] = "rule"
    return rule["source"] == "user"


def learn(conn: sqlite3.Connection, data: dict) -> None:
    """저장된 거래에서 규칙을 배운다."""
    if not _learnable(data) or data.get("category_id") is None:
        return
    key, cat, src = data["merchant_key"], data["category_id"], data.get("category_source")
    if src == "user":
        conn.execute(
            """
            INSERT INTO merchant_rules (merchant_key, category_id, source, hits) VALUES (?, ?, 'user', 1)
            ON CONFLICT(merchant_key) DO UPDATE SET
                hits = CASE WHEN category_id = excluded.category_id THEN hits + 1 ELSE 1 END,
                category_id = excluded.category_id,
                source = 'user',
                updated_at = datetime('now', 'localtime')
            """,
            (key, cat),
        )
    elif src == "llm":
        # AI 제안을 그대로 받아들인 것 — 기존 규칙(특히 사용자 규칙)은 건드리지 않는다
        conn.execute("INSERT OR IGNORE INTO merchant_rules (merchant_key, category_id, source) VALUES (?, ?, 'llm')",
                     (key, cat))
    elif src == "rule":
        rule = find_rule(conn, key)
        if rule and rule["category_id"] == cat:
            conn.execute("UPDATE merchant_rules SET hits = hits + 1 WHERE id = ?", (rule["id"],))


_SAME_MERCHANT = (
    "merchant_key = ? AND recurring_id IS NULL AND (type = 'expense' OR transfer_kind = 'external') "
    "AND category_id IS NOT ?"
)


def similar_count(conn: sqlite3.Connection, key: str, category_id: int | None, exclude_id: int) -> int:
    """같은 가맹점인데 카테고리가 다른 다른 거래 수 — '과거 거래도 바꿀까요?' 안내에 쓴다."""
    if not key or category_id is None:
        return 0
    return conn.execute(
        f"SELECT COUNT(*) FROM transactions WHERE {_SAME_MERCHANT} AND id != ?", (key, category_id, exclude_id)
    ).fetchone()[0]


def apply_past(conn: sqlite3.Connection, key: str, category_id: int) -> int:
    """같은 가맹점의 과거 거래 카테고리를 한꺼번에 바꾼다. 바꾼 건수를 돌려준다."""
    cur = conn.execute(
        f"UPDATE transactions SET category_id = ?, category_source = 'rule', needs_review = 0 WHERE {_SAME_MERCHANT}",
        (category_id, key, category_id),
    )
    return cur.rowcount


def prompt_rules(conn: sqlite3.Connection, limit: int = 40) -> list[tuple[str, str]]:
    """LLM 프롬프트에 넣을 사용자 분류 규칙 (가맹점 키, 카테고리 이름). 많이 쓴 순."""
    rows = conn.execute(
        "SELECT r.merchant_key, c.name FROM merchant_rules r JOIN categories c ON c.id = r.category_id "
        "WHERE r.source = 'user' ORDER BY r.hits DESC, r.updated_at DESC LIMIT ?",
        (limit,),
    )
    return [(r[0], r[1]) for r in rows]
