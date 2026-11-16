"""설정 > OCR — Unlimited-OCR-2 서버 상태와 판독 시험. 주소 · 키는 .env 로만 바꾼다 (손님에게는 주소도 보내지 않는다)."""

import asyncio

from fastapi import APIRouter, HTTPException, Request, UploadFile

from app.core.access import is_viewer
from app.ocr import client

router = APIRouter(prefix="/api/ocr", tags=["ocr"])
MAX_IMAGE = 10 * 1024 * 1024
IMAGE_TYPES = ("image/png", "image/jpeg", "image/webp")


@router.get("")
def read_status(request: Request) -> dict:
    out = client.status()
    out["url"] = None if is_viewer(request) else (client.base_url() or None)
    out["env_keys"] = ["MLG_OCR_URL", "MLG_OCR_MODEL", "MLG_OCR_API_KEY", "MLG_OCR_MODE", "MLG_OCR_CROP_MODE"]
    return out


@router.post("/test")
async def test_read(file: UploadFile) -> dict:
    """이미지 한 장을 OCR 로만 읽어 글을 돌려준다 (거래로 저장하지 않음)."""
    if file.content_type not in IMAGE_TYPES:
        raise HTTPException(415, "PNG · JPEG · WEBP 이미지만 읽어요")
    image = await file.read()
    if len(image) > MAX_IMAGE:
        raise HTTPException(413, "이미지가 10MB 를 넘어요")
    try:
        return await asyncio.to_thread(client.read_text, image, file.content_type)
    except client.OcrError as e:
        raise HTTPException(502, str(e)) from None
