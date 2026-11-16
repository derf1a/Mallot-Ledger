"""반복 지출 후보 (#3) — 거래 이력에서 찾은 매월·매주 반복을 정기지출 등록 제안으로 보여주고 수락·거절한다."""

import json
import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.core.db import get_conn
from app.recurring.detect import candidate_dict, link_series, sync
from app.recurring.matching import RECURRING_COLS, RECURRING_SELECT
from app.recurring.schemas import CandidateAccept

router = APIRouter(prefix="/api/recurring-candidates", tags=["recurring"])
Conn = Annotated[sqlite3.Connection, Depends(get_conn)]


def _candidate(conn: sqlite3.Connection, cand_id: int, status: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM recurring_candidates WHERE id = ?", (cand_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "후보를 찾을 수 없습니다")
    if row["status"] != status:
        raise HTTPException(409, "이미 처리한 후보입니다" if status == "pending" else "거절한 후보가 아닙니다")
    return row


def _decide(conn: sqlite3.Connection, cand_id: int, status: str, recurring_id: int | None = None) -> dict:
    conn.execute(
        "UPDATE recurring_candidates SET status = ?, recurring_id = ?, "
        "decided_at = CASE WHEN ? = 'pending' THEN NULL ELSE datetime('now', 'localtime') END WHERE id = ?",
        (status, recurring_id, status, cand_id),
    )
    conn.commit()
    return candidate_dict(conn.execute("SELECT * FROM recurring_candidates WHERE id = ?", (cand_id,)).fetchone())


@router.get("")
def list_candidates(conn: Conn) -> dict:
    """탐지를 다시 돌려 후보 표를 맞춘 뒤, 대기 중 후보(신뢰도 순)와 거절한 후보(되돌리기용)를 돌려준다."""
    sync(conn)
    rows = conn.execute(
        "SELECT * FROM recurring_candidates WHERE status != 'accepted' ORDER BY confidence DESC, id"
    ).fetchall()
    items = [candidate_dict(r) for r in rows]
    return {"pending": [c for c in items if c["status"] == "pending"],
            "rejected": [c for c in items if c["status"] == "rejected"]}


@router.post("/{cand_id}/accept")
def accept_candidate(cand_id: int, body: CandidateAccept, conn: Conn) -> dict:
    """정기지출 항목을 새로 만들거나(item_id 없음) 기존 항목을 고친 값으로 바꾼다(키워드 추가·금액 맞춤 등).
    후보의 결제를 그 항목에 연결해 이번 기간이 바로 '확인됨'이 되고, link_past 면 지난 기간 결제도 연결한다."""
    row = _candidate(conn, cand_id, "pending")
    if not conn.execute("SELECT 1 FROM recurring_groups WHERE id = ?", (body.item.group_id,)).fetchone():
        raise HTTPException(400, "없는 정기지출 카테고리입니다")
    values = [getattr(body.item, c) for c in RECURRING_COLS]
    if body.item_id is None:
        item_id = conn.execute(
            f"INSERT INTO recurring_items ({', '.join(RECURRING_COLS)}) VALUES ({', '.join('?' * len(RECURRING_COLS))})",
            values,
        ).lastrowid
    else:
        if not conn.execute("SELECT 1 FROM recurring_items WHERE id = ?", (body.item_id,)).fetchone():
            raise HTTPException(404, "정기지출 항목을 찾을 수 없습니다")
        item_id = body.item_id
        conn.execute(f"UPDATE recurring_items SET {', '.join(f'{c} = ?' for c in RECURRING_COLS)} WHERE id = ?",
                     [*values, item_id])
    linked = link_series(conn, item_id, json.loads(row["stats_json"])["tx_ids"], body.link_past)
    candidate = _decide(conn, cand_id, "accepted", item_id)
    item = conn.execute(f"{RECURRING_SELECT} WHERE r.id = ?", (item_id,)).fetchone()
    return {"candidate": candidate, "item": {**dict(item), "active": bool(item["active"])}, "linked": linked}


@router.post("/{cand_id}/reject")
def reject_candidate(cand_id: int, conn: Conn) -> dict:
    """반복 지출이 아니라고 표시한다. 같은 반복(가맹점·주기·금액 ±5%)은 다시 탐지돼도 제안하지 않는다."""
    _candidate(conn, cand_id, "pending")
    return _decide(conn, cand_id, "rejected")


@router.post("/{cand_id}/restore")
def restore_candidate(cand_id: int, conn: Conn) -> dict:
    """거절을 되돌린다. 다음 조회 때 다시 탐지되지 않으면 사라진다."""
    _candidate(conn, cand_id, "rejected")
    return _decide(conn, cand_id, "pending")
