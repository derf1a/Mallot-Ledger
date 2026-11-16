"""캡쳐 판독 파이프라인과 정확도 측정 (#1).

파이프라인: 이미지 저장 → LLM 판독(raw) → 후처리(형식 검증·내 계좌·가맹점 규칙·중복·저신뢰 경고) → 사용자 확인 → 확정값 기록
기록(extraction_logs)으로 두 가지를 측정한다.
- 운영 지표(stats): 초안과 사용자가 확정한 값을 '같은 초안 번호'끼리 비교 — 필드별 정확도, 완전 일치율, 채택률, 지연
- 재평가(evaluate): 저장해 둔 이미지를 현재 프롬프트·모델로 다시 판독하고, 확정값과 '매칭'해서 정밀도·재현율·필드별 정확도

필드 채점 기준은 ExtractBench(arXiv 2602.12247)처럼 필드 성격에 맞춘다: 금액·날짜·종류는 정확 일치,
가맹점은 정규화 키가 같으면 일치(지점명·공백 차이는 맞은 것으로 본다).
"""

import hashlib
import json
import sqlite3
import time
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path

from app.capture.extractor import PROMPT_VERSION, ExtractContext, ExtractionError, TransactionExtractor
from app.capture.schemas import TransactionDraft
from app.core.db import data_dir
from app.ledger.merchants import find_rule, merchant_key, prompt_rules
from app.ledger.rules import find_duplicate
from app.ledger.settings import is_own_account

FIELDS = ("occurred_on", "type", "transfer_kind", "amount", "merchant", "category_id", "payment_method")
FIELD_LABELS = {
    "occurred_on": "날짜",
    "type": "종류",
    "transfer_kind": "이체 구분",
    "amount": "금액",
    "merchant": "가맹점",
    "category_id": "카테고리",
    "payment_method": "결제수단",
}
EXT = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "image/gif": "gif"}
LARGE_AMOUNT = 5_000_000


# ---------- 파이프라인 ----------

def build_context(conn: sqlite3.Connection, use_rules: bool = True, today: date | None = None) -> ExtractContext:
    categories = [dict(r) for r in conn.execute("SELECT id, name, description FROM categories ORDER BY sort_order")]
    accounts = [
        f"{r['name']} ({r['keyword']})" if r["keyword"] else r["name"]
        for r in conn.execute("SELECT name, keyword FROM accounts")
    ]
    return ExtractContext(
        today=today or date.today(),
        categories=categories,
        own_accounts=accounts,
        rules=prompt_rules(conn) if use_rules else [],
    )


def warnings_for(d: TransactionDraft, today: date) -> list[str]:
    """사람이 한 번 더 봐야 할 값 (저신뢰 표시)."""
    out = []
    day = date.fromisoformat(d.occurred_on)
    if day > today + timedelta(days=1):
        out.append("미래 날짜")
    elif day < today - timedelta(days=120):
        out.append("4개월 넘게 지난 날짜")
    if d.amount == 0:
        out.append("금액 0원")
    elif d.amount >= LARGE_AMOUNT:
        out.append("큰 금액")
    if not d.merchant.strip():
        out.append("가맹점 없음")
    return out


def postprocess(
    conn: sqlite3.Connection, raw: list[dict], use_rules: bool = True, today: date | None = None
) -> list[TransactionDraft]:
    """LLM 원본 출력 → 저장 전 초안. 형식이 깨진 항목은 버린다."""
    today = today or date.today()
    by_name = {r["name"]: r["id"] for r in conn.execute("SELECT id, name FROM categories")}
    drafts = []
    for item in raw:
        try:
            date.fromisoformat(item["occurred_on"])
            d = TransactionDraft(
                occurred_on=item["occurred_on"],
                type=item["type"],
                transfer_kind=item.get("transfer_kind") if item["type"] == "transfer" else None,
                amount=abs(int(item["amount"])),
                merchant=item.get("merchant") or "",
                category_id=by_name.get(item.get("category") or ""),
                payment_method=item.get("payment_method") or "",
                memo=item.get("memo") or "",
            )
        except (KeyError, ValueError, TypeError):
            continue
        if d.type == "transfer" and is_own_account(conn, d.merchant):
            d.transfer_kind = "internal"
        if d.transfer_kind == "internal" or d.type == "income":
            d.category_id = None
        elif d.type == "refund":  # 정산·환불: 규칙은 지출용이라 쓰지 않고 AI가 고른 카테고리만
            d.category_source = "llm" if d.category_id is not None else None
        elif use_rules and (rule := find_rule(conn, merchant_key(d.merchant))):
            d.category_id, d.category_source = rule["category_id"], "rule"  # 내 규칙이 AI 추정보다 우선
        elif d.category_id is not None:
            d.category_source = "llm"
        d.duplicate_of = find_duplicate(conn, d.occurred_on, d.amount, d.merchant)
        d.warnings = warnings_for(d, today)
        drafts.append(d)
    return drafts


def save_image(image: bytes, media_type: str) -> tuple[str, str]:
    """이미지를 data/extractions/<sha256>.<ext> 로 저장 (같은 이미지는 한 번만). (sha, 상대 경로)"""
    sha = hashlib.sha256(image).hexdigest()
    rel = f"extractions/{sha}.{EXT.get(media_type, 'bin')}"
    path = data_dir() / rel
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(image)
    return sha, rel


async def run_extraction(
    conn: sqlite3.Connection, extractor: TransactionExtractor, image: bytes, media_type: str
) -> tuple[int, list[TransactionDraft]]:
    """판독 1회. 성공·실패 모두 기록한다. (기록 id, 초안)"""
    sha, rel = save_image(image, media_type)
    model = getattr(extractor, "model", type(extractor).__name__)
    cur = conn.execute(
        "INSERT INTO extraction_logs (image_sha256, image_path, media_type, model, prompt_version) VALUES (?, ?, ?, ?, ?)",
        (sha, rel, media_type, model, getattr(extractor, "prompt_version", PROMPT_VERSION)),
    )
    log_id = cur.lastrowid
    conn.commit()
    started = time.perf_counter()
    try:
        raw = await extractor.extract(image, media_type, build_context(conn))
        drafts = postprocess(conn, raw)
    except Exception as e:  # noqa: BLE001 — CLI 없음·SDK 오류 등 무엇이든 'pending'으로 남기지 않고 실패로 기록한다
        message = str(e) if isinstance(e, ExtractionError) else f"{type(e).__name__}: {e}"
        conn.execute(
            "UPDATE extraction_logs SET status = 'failed', error = ?, duration_ms = ? WHERE id = ?",
            (message, int((time.perf_counter() - started) * 1000), log_id),
        )
        conn.commit()
        if isinstance(e, ExtractionError):
            raise
        raise ExtractionError(f"이미지 판독 실패: {message}") from e
    conn.execute(
        "UPDATE extraction_logs SET duration_ms = ?, raw_json = ?, drafts_json = ?, ocr_text = ?, note = ?, model = ?, "
        "prompt_version = ? WHERE id = ?",
        (
            int((time.perf_counter() - started) * 1000),
            json.dumps(raw, ensure_ascii=False),
            json.dumps([d.model_dump() for d in drafts], ensure_ascii=False),
            getattr(extractor, "last_text", None),
            getattr(extractor, "note", None),
            getattr(extractor, "model", model),  # auto 에서 Vision 으로 넘어갔으면 실제로 읽은 쪽
            getattr(extractor, "prompt_version", PROMPT_VERSION),
            log_id,
        ),
    )
    conn.commit()
    return log_id, drafts


# ---------- 채점 ----------

def field_equal(field: str, predicted, actual) -> bool:
    if field == "merchant":
        return merchant_key(predicted) == merchant_key(actual)
    if field == "payment_method":
        return (predicted or "").replace(" ", "") == (actual or "").replace(" ", "")
    return predicted == actual


def compare(predicted: dict, actual: dict) -> dict[str, bool]:
    return {f: field_equal(f, predicted.get(f), actual.get(f)) for f in FIELDS}


def _pct(n: int, d: int) -> float | None:
    return round(n / d, 4) if d else None


def stats(conn: sqlite3.Connection, days: int = 90) -> dict:
    """운영 지표: 초안 vs 사용자 확정값 (같은 초안 번호끼리)."""
    since = (date.today() - timedelta(days=days)).isoformat()
    logs = conn.execute(
        "SELECT * FROM extraction_logs WHERE created_at >= ? ORDER BY created_at", (since,)
    ).fetchall()
    field_ok = dict.fromkeys(FIELDS, 0)
    by_source: dict[str, list[int]] = {}
    included = excluded = duplicates_excluded = exact = drafts_total = 0
    warned = warned_wrong = 0
    durations = []
    per_day: dict[str, list[int]] = {}
    for log in logs:
        if log["duration_ms"] is not None and log["status"] != "failed":
            durations.append(log["duration_ms"])
        if log["status"] != "confirmed":
            continue
        drafts = json.loads(log["drafts_json"] or "[]")
        confirmed = json.loads(log["confirmed_json"] or "[]")
        for d, c in zip(drafts, confirmed, strict=False):
            drafts_total += 1
            if c is None:
                excluded += 1
                duplicates_excluded += d.get("duplicate_of") is not None
                continue
            included += 1
            result = compare(d, c)
            for f, ok in result.items():
                field_ok[f] += ok
            all_ok = all(result.values())
            exact += all_ok
            day = log["created_at"][:10]
            per_day.setdefault(day, [0, 0])
            per_day[day][0] += all_ok
            per_day[day][1] += 1
            if d.get("category_id") is not None or c.get("category_id") is not None:
                src = d.get("category_source") or "none"
                by_source.setdefault(src, [0, 0])
                by_source[src][0] += result["category_id"]
                by_source[src][1] += 1
            if d.get("warnings"):
                warned += 1
                warned_wrong += not all_ok
    durations.sort()
    counts = {s: conn.execute("SELECT COUNT(*) FROM extraction_logs WHERE status = ? AND created_at >= ?",
                              (s, since)).fetchone()[0]
              for s in ("pending", "confirmed", "discarded", "failed")}
    return {
        "days": days,
        "logs": counts,
        "drafts": drafts_total,
        "included": included,
        "excluded": excluded,
        "duplicates_excluded": duplicates_excluded,
        # 중복이 아닌데 제외한 초안 = 오검출로 추정
        "false_positive_rate": _pct(excluded - duplicates_excluded, drafts_total),
        "exact_match_rate": _pct(exact, included),
        "fields": [{"field": f, "label": FIELD_LABELS[f], "accuracy": _pct(field_ok[f], included)} for f in FIELDS],
        "category_by_source": [
            {"source": s, "accuracy": _pct(ok, n), "count": n} for s, (ok, n) in sorted(by_source.items())
        ],
        # 경고가 붙은 초안이 실제로 틀린 비율 — 경고가 쓸모 있는지 보는 지표
        "warning_precision": _pct(warned_wrong, warned),
        "latency_ms": {
            "count": len(durations),
            "p50": durations[len(durations) // 2] if durations else None,
            "p95": durations[min(len(durations) - 1, int(len(durations) * 0.95))] if durations else None,
        },
        "failure_rate": _pct(counts["failed"], sum(counts.values())),
        "daily": [{"day": k, "exact_match_rate": _pct(v[0], v[1]), "count": v[1]} for k, v in sorted(per_day.items())],
        "prompt_version": PROMPT_VERSION,
    }


# ---------- 재평가 (저장된 이미지로 다시 판독) ----------

def match(predicted: list[dict], actual: list[dict]) -> list[tuple[int, int]]:
    """예측과 정답을 1:1로 짝짓는다 (금액 4 · 날짜 2 · 가맹점 1 가중치, 점수 높은 순 탐욕적).

    금액이 같거나, 날짜와 가맹점이 둘 다 같을 때만 짝짓는다(점수 3 이상). 한 캡쳐의 거래는 보통 날짜가 같아서
    날짜만 같은 것을 짝지으면 지어낸 거래가 실제 거래와 엮여 정밀도가 부풀려진다.
    """
    scored = []
    for i, p in enumerate(predicted):
        for j, a in enumerate(actual):
            s = 4 * (p.get("amount") == a.get("amount")) + 2 * (p.get("occurred_on") == a.get("occurred_on"))
            s += merchant_key(p.get("merchant")) == merchant_key(a.get("merchant"))
            if s >= 3:
                scored.append((s, i, j))
    pairs, used_p, used_a = [], set(), set()
    for _, i, j in sorted(scored, reverse=True):
        if i not in used_p and j not in used_a:
            pairs.append((i, j))
            used_p.add(i)
            used_a.add(j)
    return pairs


def golden_set(conn: sqlite3.Connection, limit: int | None = None) -> list[sqlite3.Row]:
    """재평가에 쓸 수 있는 기록: 확정됐고 이미지가 남아 있는 것."""
    rows = conn.execute(
        "SELECT * FROM extraction_logs WHERE status = 'confirmed' AND image_path IS NOT NULL ORDER BY id DESC"
    ).fetchall()
    rows = [r for r in rows if (data_dir() / r["image_path"]).exists()]
    return rows[:limit] if limit else rows


async def evaluate(
    conn: sqlite3.Connection,
    extractor: TransactionExtractor,
    limit: int | None = None,
    use_rules: bool = True,
    on_progress: Callable[[int, int, dict], None] | None = None,
) -> dict:
    """저장된 이미지를 다시 판독해 확정값과 비교한다. LLM을 실제로 호출한다."""
    logs = golden_set(conn, limit)
    totals = {"predicted": 0, "actual": 0, "matched": 0, "exact": 0, "failed": 0}
    field_ok = dict.fromkeys(FIELDS, 0)
    for n, log in enumerate(logs, start=1):
        actual = [c for c in json.loads(log["confirmed_json"] or "[]") if c is not None]
        image = Path(data_dir() / log["image_path"]).read_bytes()
        try:
            raw = await extractor.extract(image, log["media_type"], build_context(conn, use_rules=use_rules,
                                                                                 today=date.fromisoformat(log["created_at"][:10])))
            predicted = [d.model_dump() for d in postprocess(conn, raw, use_rules=use_rules)]
        except Exception:  # noqa: BLE001 — 한 장이 실패해도 재평가 전체를 멈추지 않고 실패로 센다
            totals["failed"] += 1
            totals["actual"] += len(actual)
            continue
        pairs = match(predicted, actual)
        totals["predicted"] += len(predicted)
        totals["actual"] += len(actual)
        totals["matched"] += len(pairs)
        for i, j in pairs:
            result = compare(predicted[i], actual[j])
            for f, ok in result.items():
                field_ok[f] += ok
            totals["exact"] += all(result.values())
        if on_progress:
            on_progress(n, len(logs), {"log_id": log["id"], "predicted": len(predicted), "actual": len(actual),
                                       "matched": len(pairs)})
    m = totals["matched"]
    return {
        "images": len(logs),
        "use_rules": use_rules,
        "prompt_version": PROMPT_VERSION,
        "model": getattr(extractor, "model", type(extractor).__name__),
        **totals,
        "precision": _pct(m, totals["predicted"]),
        "recall": _pct(m, totals["actual"]),
        "exact_match_rate": _pct(totals["exact"], m),
        "fields": [{"field": f, "label": FIELD_LABELS[f], "accuracy": _pct(field_ok[f], m)} for f in FIELDS],
    }
