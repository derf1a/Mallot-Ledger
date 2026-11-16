import shutil
import sqlite3
from datetime import datetime
from importlib.metadata import PackageNotFoundError, version
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse

from app.core.access import is_viewer
from app.core.db import data_dir, db_path, get_conn
from app.llm.client import model_label, uses_local

router = APIRouter(prefix="/api", tags=["system"])
BACKUP_KEEP = 10  # data/backups 에 남겨 둘 백업 버튼 스냅샷 수
Conn = Annotated[sqlite3.Connection, Depends(get_conn)]


@router.get("/system")
def system_info(conn: Conn, request: Request) -> dict:
    path = db_path()
    try:
        sdk_version = version("claude-agent-sdk")
    except PackageNotFoundError:
        sdk_version = None
    return {
        "db": {
            "path": None if is_viewer(request) else str(path),  # 손님에게는 서버 경로를 보내지 않는다
            "size_bytes": path.stat().st_size if path.exists() else 0,
            "schema_version": conn.execute("PRAGMA user_version").fetchone()[0],
            "transactions": conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0],
        },
        "llm": {
            "provider": "로컬 LLM (mlx-lm)" if uses_local() else "Claude Agent SDK (로컬 Claude Code 로그인)",
            "model": model_label(),
            "sdk_version": sdk_version,
            "claude_cli": shutil.which("claude") is not None,
        },
    }


@router.get("/system/backup")
def download_backup(conn: Conn) -> FileResponse:
    """현재 DB를 일관된 스냅샷으로 data/backups 에 남기고 내려준다. 버튼 스냅샷은 최근 BACKUP_KEEP 개만 보관."""
    folder = data_dir() / "backups"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"wt-backup-{datetime.now():%Y%m%d-%H%M%S}.db"
    backup = sqlite3.connect(target)
    try:
        conn.backup(backup)
    finally:
        backup.close()
    for old in sorted(folder.glob("wt-backup-*.db"))[:-BACKUP_KEEP]:
        old.unlink(missing_ok=True)
    return FileResponse(target, filename=target.name, media_type="application/octet-stream")
