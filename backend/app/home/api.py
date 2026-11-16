import sqlite3
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core.db import get_conn
from app.home import trend as home
from app.ledger.settings import current_period

router = APIRouter(prefix="/api", tags=["home"])
Conn = Annotated[sqlite3.Connection, Depends(get_conn)]


@router.get("/home")
def read_home(conn: Conn, on: Annotated[date | None, Query(description="이 날짜가 속한 기간 (기본: 오늘)")] = None) -> dict:
    """홈 화면 추세: 날마다 쓴 변동비(이번·지난 기간), 카테고리별 지난 기간·많이 쓴 곳, 최근 6개 기간 흐름."""
    return home.overview(conn, current_period(conn, on))
