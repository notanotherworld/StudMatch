from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Bot
    BOT_TOKEN: str
    BOT_USERNAME: str = "edudating_bot"
    ADMIN_TG_IDS: str = ""  # "123,456"

    # Database
    DATABASE_URL: str

    # Redis
    REDIS_URL: str = "redis://redis:6379/0"

    # MinIO
    MINIO_ENDPOINT: str = "minio:9000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin"
    MINIO_BUCKET_DOCUMENTS: str = "documents"
    MINIO_SECURE: bool = False

    # SMTP (Яндекс Почта по умолчанию)
    SMTP_HOST: str = "smtp.yandex.ru"
    SMTP_PORT: int = 465
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = "СтудМэч <no-reply@studmatch.ru>"
    SMTP_USE_SSL: bool = True

    # YooKassa
    YOOKASSA_SHOP_ID: str = ""
    YOOKASSA_SECRET_KEY: str = ""
    YOOKASSA_RETURN_URL: str = "https://yourdomain.com/payment/success"

    # Web
    SECRET_KEY: str = "change_me"
    WEB_HOST: str = "0.0.0.0"
    WEB_PORT: int = 8000
    DOMAIN: str = "https://yourdomain.com"

    # Prices (RUB)
    PRICE_SUPERLIKE_3: int = 99
    PRICE_SUPERLIKE_10: int = 249
    PRICE_BOOST_24H: int = 149

    @property
    def admin_ids(self) -> List[int]:
        if not self.ADMIN_TG_IDS:
            return []
        return [int(x.strip()) for x in self.ADMIN_TG_IDS.split(",") if x.strip()]


settings = Settings()
