"""기간 요약: 수입·정기지출·변동비(카테고리 예산 대비)·분류 필요."""

import sqlite3
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core.db import get_conn
from app.ledger.settings import current_period
from app.ledger.summary import summary

router = APIRouter(prefix="/api", tags=["summary"])
Conn = Annotated[sqlite3.Connection, Depends(get_conn)]
On = Annotated[date | None, Query(description="이 날짜가 속한 기간 (기본: 오늘)")]


@router.get("/summary")
def read_summary(conn: Conn, on: On = None) -> dict:
    return summary(conn, current_period(conn, on))
