"""MinIO клиент для загрузки документов (дипломы, справки)."""
import io
import uuid
from minio import Minio
from minio.error import S3Error

from bot.config import settings

_client: Minio | None = None


def get_minio_client() -> Minio:
    global _client
    if _client is None:
        _client = Minio(
            endpoint=settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=settings.MINIO_SECURE,
        )
    return _client


async def ensure_bucket(bucket: str) -> None:
    """Создать бакет если не существует."""
    client = get_minio_client()
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)


async def upload_document(
    file_bytes: bytes,
    original_filename: str,
    user_id: int,
) -> str:
    """
    Загрузить документ в MinIO.
    Возвращает URL вида: /documents/{user_id}/{uuid}.{ext}
    """
    client = get_minio_client()
    bucket = settings.MINIO_BUCKET_DOCUMENTS

    await ensure_bucket(bucket)

    raw_ext = original_filename.rsplit(".", 1)[-1].lower() if "." in original_filename else "pdf"
    ALLOWED_EXTENSIONS = {"pdf", "jpg", "jpeg", "png"}
    ext = raw_ext if raw_ext in ALLOWED_EXTENSIONS else "pdf"
    object_name = f"{user_id}/{uuid.uuid4()}.{ext}"

    client.put_object(
        bucket_name=bucket,
        object_name=object_name,
        data=io.BytesIO(file_bytes),
        length=len(file_bytes),
        content_type=_get_content_type(ext),
    )

    return f"{bucket}/{object_name}"


def get_presigned_url(object_path: str, expires_hours: int = 1) -> str:
    """Получить временный URL для просмотра документа."""
    from datetime import timedelta
    client = get_minio_client()
    parts = object_path.split("/", 1)
    bucket = parts[0]
    obj = parts[1] if len(parts) > 1 else parts[0]

    return client.presigned_get_object(
        bucket_name=bucket,
        object_name=obj,
        expires=timedelta(hours=expires_hours),
    )


def _get_content_type(ext: str) -> str:
    types = {
        "pdf": "application/pdf",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
    }
    return types.get(ext, "application/octet-stream")
