"""외부 데이터 가져오기 API (뱅크샐러드 엑셀)."""

import json
import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile

from app.core.db import get_conn
from app.importer.banksalad import ImportError_, run_import, undo_import

router = APIRouter(prefix="/api/imports", tags=["imports"])
Conn = Annotated[sqlite3.Connection, Depends(get_conn)]
MAX_BYTES = 20 * 1024 * 1024


@router.post("/banksalad")
async def import_banksalad(
    conn: Conn,
    file: Annotated[UploadFile, File()],
    dry_run: Annotated[bool, Query(description="미리보기만 (저장하지 않음)")] = False,
) -> dict:
    data = await file.read()
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "파일이 너무 큽니다 (최대 20MB)")
    try:
        return run_import(conn, data, file.filename or "banksalad.xlsx", dry_run=dry_run)
    except ImportError_ as e:
        raise HTTPException(400, str(e)) from None


@router.get("")
def list_imports(conn: Conn) -> list[dict]:
    rows = conn.execute(
        "SELECT b.*, (SELECT COUNT(*) FROM transactions t WHERE t.import_batch_id = b.id) AS tx_count "
        "FROM import_batches b ORDER BY b.id DESC"
    )
    return [{**{k: r[k] for k in r.keys() if k != "stats_json"}, "stats": json.loads(r["stats_json"])} for r in rows]


@router.delete("/{batch_id}")
def delete_import(batch_id: int, conn: Conn) -> dict:
    """가져오기 한 번을 되돌린다 — 그때 들어온 거래를 모두 지운다."""
    try:
        return {"deleted": undo_import(conn, batch_id)}
    except ImportError_ as e:
        raise HTTPException(404, str(e)) from None
