import asyncio
from datetime import date, timedelta

import pytest

from app.capture.extraction import evaluate, match
from app.capture.extractor import ExtractionError, get_extractor
from app.core.db import connect, data_dir

TODAY = date.today()


def item(**kw):
    base = {"occurred_on": TODAY.isoformat(), "type": "expense", "transfer_kind": None, "amount": 4500,
            "merchant": "스타벅스 강남점", "category": "식비", "payment_method": "신한카드", "memo": ""}
    return {**base, **kw}


class Fake:
    model = "fake-model"

    def __init__(self, items=None, error=None):
        self.items, self.error, self.calls = items or [], error, 0

    async def extract(self, image, media_type, ctx):
        self.calls += 1
        if self.error:
            raise ExtractionError(self.error)
        return self.items


@pytest.fixture
def use_fake(client):
    def _use(fake):
        client.app.dependency_overrides[get_extractor] = lambda: fake
        return fake
    yield _use
    client.app.dependency_overrides.clear()


def upload(client, content=b"\x89PNG-1"):
    return client.post("/api/transactions/extract", files={"image": ("s.png", content, "image/png")})


def cat(client, name):
    return next(c["id"] for c in client.get("/api/categories").json() if c["name"] == name)


def tx_from(draft, **changes):
    keys = ("occurred_on", "type", "transfer_kind", "amount", "merchant", "category_id", "payment_method", "memo",
            "category_source")
    return {**{k: draft[k] for k in keys}, "source": "image", "reviewed": True, **changes}


def test_extract_logs_and_confirm_records_corrections(client, use_fake):
    use_fake(Fake([item(), item(amount=3200, merchant="GS25", category="생활비"),
                   item(amount=0, merchant="", occurred_on=(TODAY + timedelta(days=3)).isoformat())]))
    res = upload(client).json()
    log_id, drafts = res["extraction_id"], res["drafts"]
    assert drafts[2]["warnings"] == ["미래 날짜", "금액 0원", "가맹점 없음"]
    assert drafts[0]["warnings"] == []

    log = client.get(f"/api/extractions/{log_id}").json()
    assert (log["status"], log["model"], log["has_image"]) == ("pending", "fake-model", True)
    assert len(log["raw"]) == 3 and log["duration_ms"] is not None

    # 0번은 그대로, 1번은 금액을 고쳐서, 2번은 제외
    saved = client.post(f"/api/extractions/{log_id}/confirm", json={"items": [
        {"draft_index": 0, "include": True, "transaction": tx_from(drafts[0])},
        {"draft_index": 1, "include": True, "transaction": tx_from(drafts[1], amount=3300)},
        {"draft_index": 2, "include": False},
    ]})
    assert saved.status_code == 201 and len(saved.json()) == 2
    assert all(t["extraction_id"] == log_id for t in saved.json())
    assert client.post(f"/api/extractions/{log_id}/confirm", json={"items": []}).status_code == 409

    s = client.get("/api/extractions/stats").json()
    fields = {f["field"]: f["accuracy"] for f in s["fields"]}
    assert (s["included"], s["excluded"], s["drafts"]) == (2, 1, 3)
    assert fields["amount"] == 0.5 and fields["merchant"] == 1.0
    assert s["exact_match_rate"] == 0.5
    assert s["false_positive_rate"] == round(1 / 3, 4)
    assert {c["source"]: c["accuracy"] for c in s["category_by_source"]} == {"llm": 1.0}
    assert s["warning_precision"] is None  # 경고가 붙은 초안(2번)은 제외돼 채점되지 않음
    assert s["logs"]["confirmed"] == 1


def test_failed_extraction_is_logged(client, use_fake):
    use_fake(Fake(error="모델 오류"))
    assert upload(client).status_code == 502
    log = client.get("/api/extractions").json()[0]
    assert (log["status"], log["error"]) == ("failed", "모델 오류")
    assert client.get("/api/extractions/stats").json()["failure_rate"] == 1.0


def test_discard_and_bad_confirm(client, use_fake):
    use_fake(Fake([item()]))
    log_id = upload(client).json()["extraction_id"]
    bad = client.post(f"/api/extractions/{log_id}/confirm", json={"items": [{"draft_index": 5, "include": False}]})
    assert bad.status_code == 400
    assert client.post(f"/api/extractions/{log_id}/discard").status_code == 204
    assert client.get(f"/api/extractions/{log_id}").json()["status"] == "discarded"


def test_same_image_stored_once_and_can_be_deleted(client, use_fake):
    use_fake(Fake([item()]))
    upload(client, b"same")
    upload(client, b"same")
    assert client.get("/api/extractions/storage").json()["images"] == 1
    assert client.delete("/api/extractions/images").json() == {"removed": 1}
    log_id = client.get("/api/extractions").json()[0]["id"]
    assert client.get(f"/api/extractions/{log_id}/image").status_code == 404


def test_match_pairs_by_amount_then_date():
    predicted = [{"amount": 1000, "occurred_on": "2026-10-01", "merchant": "A"},
                 {"amount": 2000, "occurred_on": "2026-10-02", "merchant": "B"},
                 {"amount": 9999, "occurred_on": "2026-01-01", "merchant": "Z"}]
    actual = [{"amount": 2000, "occurred_on": "2026-10-02", "merchant": "B 지점"},
              {"amount": 1000, "occurred_on": "2026-10-01", "merchant": "A"}]
    assert sorted(match(predicted, actual)) == [(0, 1), (1, 0)]


def test_evaluate_rereads_stored_images(client, use_fake):
    use_fake(Fake([item(), item(amount=3200, merchant="GS25", category="생활비")]))
    res = upload(client).json()
    d = res["drafts"]
    client.post(f"/api/extractions/{res['extraction_id']}/confirm", json={"items": [
        {"draft_index": 0, "include": True, "transaction": tx_from(d[0])},
        {"draft_index": 1, "include": True, "transaction": tx_from(d[1], category_id=cat(client, "식비"),
                                                                    category_source="user")},
    ]})

    # 새 모델(가짜)은 GS25를 놓치고 없는 거래를 하나 만들어 낸다
    new = Fake([item(), item(amount=777, merchant="유령")])
    progress = []
    with connect() as conn:
        report = asyncio.run(evaluate(conn, new, on_progress=lambda n, total, info: progress.append((n, total))))
    assert (report["images"], report["predicted"], report["actual"], report["matched"]) == (1, 2, 2, 1)
    assert (report["precision"], report["recall"]) == (0.5, 0.5)
    assert progress == [(1, 1)]
    assert (data_dir() / "extractions").exists()


def test_match_does_not_pair_by_date_alone():
    predicted = [{"amount": 777, "occurred_on": "2026-10-01", "merchant": "유령"}]
    actual = [{"amount": 3200, "occurred_on": "2026-10-01", "merchant": "GS25"}]
    assert match(predicted, actual) == []
    # 금액이 틀려도 날짜와 가맹점이 같으면 같은 거래로 본다 (금액 오독)
    assert match([{"amount": 3300, "occurred_on": "2026-10-01", "merchant": "GS25 역삼점"}], actual) == [(0, 0)]


class Crashing:
    model = "crash"

    async def extract(self, image, media_type, ctx):
        raise FileNotFoundError("claude CLI 없음")


def test_unexpected_extractor_error_is_logged_as_failed(client, use_fake):
    use_fake(Crashing())
    res = upload(client)
    assert res.status_code == 502 and "FileNotFoundError" in res.json()["detail"]
    log = client.get("/api/extractions").json()[0]
    assert log["status"] == "failed" and "claude CLI 없음" in log["error"]
