import pytest

from app.capture.extractor import get_extractor
from app.ledger.merchants import merchant_key


@pytest.mark.parametrize(
    ("raw", "key"),
    [
        ("스타벅스 강남점", "스타벅스"),
        ("스타벅스  역삼점", "스타벅스"),
        ("GS25 역삼점", "gs25"),
        ("(주)우아한형제들", "우아한형제들"),
        ("㈜쿠팡 [로켓배송]", "쿠팡"),
        ("배달의민족", "배달의민족"),
        ("토스뱅크 홍길동", "토스뱅크홍길동"),
        ("편의점", "편의점"),  # 지점명만 남는 경우는 그대로 둔다
        ("롯데 백화점", "롯데백화점"),  # 업종 단어는 지점명이 아니다
        ("CU 편의점", "cu편의점"),
        ("롯데리아 강남점", "롯데리아"),
        ("", ""),
        (None, ""),
    ],
)
def test_merchant_key(raw, key):
    assert merchant_key(raw) == key


def cat(client, name):
    return next(c["id"] for c in client.get("/api/categories").json() if c["name"] == name)


def add(client, **fields):
    body = {"occurred_on": "2026-10-01", "type": "expense", "amount": 5000, **fields}
    res = client.post("/api/transactions", json=body)
    assert res.status_code == 201, res.text
    return res.json()


def test_user_choice_becomes_rule_and_applies_to_variants(client):
    food = cat(client, "식비")
    add(client, merchant="스타벅스 강남점", category_id=food, category_source="user")

    same = add(client, merchant="스타벅스 역삼점")  # 지점이 달라도 같은 가맹점
    assert (same["category_id"], same["category_source"]) == (food, "rule")
    similar = add(client, merchant="스타벅스코리아")  # 규칙 이름을 포함하는 가맹점
    assert similar["category_source"] == "rule"
    other = add(client, merchant="이디야")
    assert (other["category_id"], other["category_source"]) == (None, None)

    rule = client.get("/api/merchant-rules").json()[0]
    assert (rule["merchant_key"], rule["source"], rule["category_name"]) == ("스타벅스", "user", "식비")
    assert rule["hits"] == 3  # 규칙이 그대로 쓰인 '역삼점'·'스타벅스코리아'에서 한 번씩 더 확인됨


def test_llm_accept_does_not_override_user_rule(client):
    food, life = cat(client, "식비"), cat(client, "생활비")
    add(client, merchant="쿠팡", category_id=life, category_source="user")
    add(client, merchant="쿠팡", category_id=food, category_source="llm")
    rule = client.get("/api/merchant-rules").json()[0]
    assert (rule["category_id"], rule["source"]) == (life, "user")

    add(client, merchant="다이소", category_id=life, category_source="llm")
    assert {r["merchant_key"]: r["source"] for r in client.get("/api/merchant-rules").json()}["다이소"] == "llm"


def test_changing_category_updates_rule_and_offers_past(client):
    food, fun = cat(client, "식비"), cat(client, "여가·유흥")
    a = add(client, merchant="강남 이자카야", category_id=food, category_source="user")
    add(client, merchant="강남 이자카야", occurred_on="2026-10-02")  # 규칙으로 식비
    add(client, merchant="강남 이자카야", occurred_on="2026-10-03")

    body = {"occurred_on": a["occurred_on"], "type": "expense", "amount": a["amount"], "merchant": a["merchant"],
            "category_id": fun, "category_source": "user", "reviewed": True}
    res = client.put(f"/api/transactions/{a['id']}", json=body).json()
    assert res["similar_count"] == 2
    rule = client.get("/api/merchant-rules", params={"q": "이자카야"}).json()[0]
    assert (rule["category_id"], rule["hits"]) == (fun, 1)

    assert client.post("/api/merchant-rules/apply-past",
                       json={"merchant": "강남 이자카야", "category_id": fun}).json() == {"updated": 2}
    txs = client.get("/api/transactions", params={"on": "2026-10-01"}).json()["transactions"]
    assert {t["category_id"] for t in txs if t["merchant_key"] == "강남이자카야"} == {fun}


def test_external_transfer_with_user_rule_needs_no_review(client):
    fun = cat(client, "여가·유흥")
    first = add(client, type="transfer", transfer_kind="external", merchant="김철수", amount=30000)
    assert first["needs_review"] is True and first["category_source"] is None  # '기타'는 임시 분류
    add(client, type="transfer", transfer_kind="external", merchant="김철수", amount=20000,
        category_id=fun, category_source="user", reviewed=True)
    nxt = add(client, type="transfer", transfer_kind="external", merchant="김철수", amount=10000)
    assert (nxt["category_id"], nxt["needs_review"]) == (fun, False)


def test_recurring_and_internal_are_not_learned(client):
    food = cat(client, "식비")
    client.post("/api/accounts", json={"name": "비상금", "keyword": "토스뱅크"})
    add(client, type="transfer", merchant="토스뱅크 나", category_id=food, category_source="user")
    assert client.get("/api/merchant-rules").json() == []


def test_rules_api_crud_suggest_and_cascade(client):
    food, life = cat(client, "식비"), cat(client, "생활비")
    add(client, merchant="이마트 역삼점", category_id=food, category_source="user")
    rule = client.get("/api/merchant-rules").json()[0]
    assert rule["tx_count"] == 1

    assert client.get("/api/merchant-rules/suggest", params={"merchant": "이마트 성수점"}).json()["category_id"] == food
    assert client.get("/api/merchant-rules/suggest", params={"merchant": "홈플러스"}).json() is None

    updated = client.put(f"/api/merchant-rules/{rule['id']}", json={"category_id": life}).json()
    assert updated["category_name"] == "생활비"
    assert client.put(f"/api/merchant-rules/{rule['id']}", json={"category_id": 9999}).status_code == 400

    client.delete(f"/api/categories/{life}")  # 카테고리를 지우면 그 규칙도 사라진다
    assert client.get("/api/merchant-rules").json() == []


class FakeExtractor:
    def __init__(self, items):
        self.items, self.ctx = items, None

    async def extract(self, image, media_type, ctx):
        self.ctx = ctx
        return self.items


def test_extract_prefers_user_rule_over_llm(client):
    food, life = cat(client, "식비"), cat(client, "생활비")
    add(client, merchant="GS25 역삼점", category_id=life, category_source="user")
    fake = FakeExtractor([
        {"occurred_on": "2026-10-05", "type": "expense", "transfer_kind": None, "amount": 3200,
         "merchant": "GS25 선릉점", "category": "식비", "payment_method": "", "memo": ""},
        {"occurred_on": "2026-10-05", "type": "expense", "transfer_kind": None, "amount": 6300,
         "merchant": "스타벅스", "category": "식비", "payment_method": "", "memo": ""},
    ])
    client.app.dependency_overrides[get_extractor] = lambda: fake
    try:
        drafts = client.post("/api/transactions/extract", files={"image": ("a.png", b"x", "image/png")}).json()["drafts"]
    finally:
        client.app.dependency_overrides.clear()
    assert (drafts[0]["category_id"], drafts[0]["category_source"]) == (life, "rule")
    assert (drafts[1]["category_id"], drafts[1]["category_source"]) == (food, "llm")
    assert ("gs25", "생활비") in fake.ctx.rules


def test_short_or_infix_rule_keys_do_not_spread(client):
    fun = cat(client, "여가·유흥")
    add(client, merchant="롯데", category_id=fun, category_source="user")       # 2글자 키
    add(client, merchant="마트", category_id=fun, category_source="user")
    assert add(client, merchant="롯데리아 강남점")["category_source"] is None    # 짧은 키는 비슷한 가맹점으로 안 본다
    assert add(client, merchant="이마트 역삼점")["category_source"] is None      # 중간에 들어 있는 것도 아님


def test_editing_unrelated_fields_does_not_inflate_rule_hits(client):
    food = cat(client, "식비")
    tx = add(client, merchant="스타벅스", category_id=food, category_source="user")
    body = {k: tx[k] for k in ("occurred_on", "type", "amount", "merchant", "category_id", "category_source")}
    for memo in ("a", "b", "c"):
        client.put(f"/api/transactions/{tx['id']}", json={**body, "memo": memo})
    assert client.get("/api/merchant-rules").json()[0]["hits"] == 1
