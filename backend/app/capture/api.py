"""캡쳐 판독: 이미지 → 저장 전 초안, 사용자 확인·저장/버리기, 판독 기록·정확도 통계·이미지 보관."""

import json
import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from app.capture.extraction import run_extraction, stats
from app.capture.extractor import ExtractionError, TransactionExtractor, get_extractor
from app.capture.schemas import ExtractionConfirm, ExtractionResult
from app.core.db import data_dir, get_conn
from app.ledger.transactions import get_transaction, insert_transaction

router = APIRouter(prefix="/api", tags=["extractions"])
Conn = Annotated[sqlite3.Connection, Depends(get_conn)]

MAX_IMAGE_BYTES = 10 * 1024 * 1024
IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}

SUMMARY_COLS = "id, created_at, image_sha256, image_path, media_type, model, prompt_version, duration_ms, status, error, confirmed_at"


def _log(conn: sqlite3.Connection, log_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM extraction_logs WHERE id = ?", (log_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "판독 기록을 찾을 수 없습니다")
    return row


def _detail(row: sqlite3.Row) -> dict:
    out = dict(row)
    for k in ("raw_json", "drafts_json", "confirmed_json"):
        out[k.removesuffix("_json")] = json.loads(out.pop(k)) if row[k] else None
    out["has_image"] = bool(row["image_path"]) and (data_dir() / row["image_path"]).exists()
    return out


@router.get("/extractions")
def list_logs(conn: Conn, limit: Annotated[int, Query(le=500)] = 50) -> list[dict]:
    rows = conn.execute(f"SELECT {SUMMARY_COLS}, drafts_json, confirmed_json FROM extraction_logs "
                        "ORDER BY id DESC LIMIT ?", (limit,))
    out = []
    for r in rows:
        drafts = json.loads(r["drafts_json"] or "[]")
        confirmed = json.loads(r["confirmed_json"] or "[]")
        d = {k: r[k] for k in r.keys() if not k.endswith("_json")}
        d["draft_count"] = len(drafts)
        d["included_count"] = sum(c is not None for c in confirmed)
        out.append(d)
    return out


@router.get("/extractions/stats")
def read_stats(conn: Conn, days: Annotated[int, Query(ge=1, le=3650)] = 90) -> dict:
    return stats(conn, days)


@router.get("/extractions/storage")
def storage(conn: Conn) -> dict:
    folder = data_dir() / "extractions"
    files = list(folder.glob("*")) if folder.exists() else []
    return {
        "images": len(files),
        "bytes": sum(f.stat().st_size for f in files),
        "logs": conn.execute("SELECT COUNT(*) FROM extraction_logs").fetchone()[0],
    }


@router.delete("/extractions/images")
def delete_images(conn: Conn) -> dict:
    """판독 이미지 파일만 지운다 (기록과 정확도 통계는 남는다. 재평가는 할 수 없게 됨)."""
    folder = data_dir() / "extractions"
    removed = 0
    for f in folder.glob("*") if folder.exists() else []:
        f.unlink()
        removed += 1
    conn.execute("UPDATE extraction_logs SET image_path = NULL")
    conn.commit()
    return {"removed": removed}


@router.get("/extractions/{log_id}")
def read_log(log_id: int, conn: Conn) -> dict:
    return _detail(_log(conn, log_id))


@router.get("/extractions/{log_id}/image")
def read_image(log_id: int, conn: Conn) -> FileResponse:
    row = _log(conn, log_id)
    if not row["image_path"] or not (data_dir() / row["image_path"]).exists():
        raise HTTPException(404, "이미지가 남아 있지 않습니다")
    return FileResponse(data_dir() / row["image_path"], media_type=row["media_type"])


@router.post("/extractions/{log_id}/confirm", status_code=201)
def confirm(log_id: int, body: ExtractionConfirm, conn: Conn) -> list[dict]:
    """사용자가 확인한 초안을 저장하고, 초안 대비 확정값을 기록한다."""
    row = _log(conn, log_id)
    if row["status"] != "pending":
        raise HTTPException(409, f"이미 처리된 판독입니다 ({row['status']})")
    drafts = json.loads(row["drafts_json"] or "[]")
    confirmed: list[dict | None] = [None] * len(drafts)
    ids = []
    for item in body.items:
        if not 0 <= item.draft_index < len(drafts):
            raise HTTPException(400, f"없는 초안 번호입니다: {item.draft_index}")
        if not item.include:
            continue
        if item.transaction is None:
            raise HTTPException(400, "저장할 거래 값이 없습니다")
        tx_id = insert_transaction(conn, item.transaction)
        conn.execute("UPDATE transactions SET extraction_id = ? WHERE id = ?", (log_id, tx_id))
        ids.append(tx_id)
        confirmed[item.draft_index] = item.transaction.model_dump(exclude={"reviewed"})
    conn.execute(
        "UPDATE extraction_logs SET status = 'confirmed', confirmed_json = ?, confirmed_at = datetime('now', 'localtime') "
        "WHERE id = ?",
        (json.dumps(confirmed, ensure_ascii=False), log_id),
    )
    conn.commit()
    return [get_transaction(conn, i) for i in ids]


@router.post("/extractions/{log_id}/discard", status_code=204)
def discard(log_id: int, conn: Conn) -> None:
    """판독 결과를 저장하지 않고 닫았을 때."""
    if _log(conn, log_id)["status"] == "pending":
        conn.execute("UPDATE extraction_logs SET status = 'discarded' WHERE id = ?", (log_id,))
        conn.commit()


@router.post("/transactions/extract")
async def extract_from_image(
    conn: Conn,
    extractor: Annotated[TransactionExtractor, Depends(get_extractor)],
    image: Annotated[UploadFile, File()],
) -> ExtractionResult:
    """캡쳐 이미지를 판독해 저장 전 초안을 돌려준다. 저장은 사용자가 확인한 뒤 /api/extractions/{id}/confirm 으로 한다."""
    media_type = (image.content_type or "").lower()
    if media_type not in IMAGE_TYPES:
        raise HTTPException(415, "PNG, JPEG, WEBP, GIF 이미지만 올릴 수 있습니다")
    data = await image.read()
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(413, "이미지가 너무 큽니다 (최대 10MB)")
    try:
        log_id, drafts = await run_extraction(conn, extractor, data, media_type)
    except ExtractionError as e:
        raise HTTPException(502, str(e)) from None
    return ExtractionResult(extraction_id=log_id, drafts=drafts)
