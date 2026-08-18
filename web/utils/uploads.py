"""Утилита для сохранения загруженных аватарок и изображений."""
import os
import uuid
from typing import Optional
from fastapi import UploadFile

UPLOAD_DIR = os.path.join("web", "static", "uploads", "avatars")
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
ALLOWED_MIME_TYPES = {"image/jpeg", "image/png", "image/webp", "image/jpg"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB


def ensure_upload_dir_exists():
    os.makedirs(UPLOAD_DIR, exist_ok=True)

ensure_upload_dir_exists()


async def save_avatar_upload(upload_file: Optional[UploadFile]) -> Optional[str]:
    """
    Валидирует и сохраняет загруженный файл аватарки.
    Возвращает URL-путь вида '/static/uploads/avatars/<uuid>.<ext>' или None.
    """
    if not upload_file or not upload_file.filename:
        return None

    filename = upload_file.filename.lower()
    ext = os.path.splitext(filename)[1]
    if ext not in ALLOWED_EXTENSIONS:
        return None

    if upload_file.content_type and upload_file.content_type.lower() not in ALLOWED_MIME_TYPES:
        return None

    ensure_upload_dir_exists()

    content = await upload_file.read()
    if len(content) == 0 or len(content) > MAX_FILE_SIZE:
        return None

    unique_filename = f"{uuid.uuid4().hex}{ext}"
    target_path = os.path.join(UPLOAD_DIR, unique_filename)

    with open(target_path, "wb") as f:
        f.write(content)

    return f"/static/uploads/avatars/{unique_filename}"
