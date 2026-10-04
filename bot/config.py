from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator
from typing import List, Any
from dotenv import load_dotenv

load_dotenv()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    DEBUG: bool = False

    # Bot
    BOT_TOKEN: str
    BOT_USERNAME: str = "edudating_bot"
    ADMIN_TG_IDS: str = ""  # "123,456"
    MASTER_VERIFY_CODE: str = ""  # Резервный мастер-код для саппорта (например: "777888")
    EMAIL_VERIFICATION_ENABLED: bool = False  # Временное отключение email-верификации (True для включения)

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

    @field_validator("YOOKASSA_SHOP_ID", mode="before")
    @classmethod
    def clean_yookassa_shop_id(cls, v: Any) -> str:
        if v is None:
            return ""
        s = str(v).strip().strip("\"'").strip()
        if "#" in s:
            s = s.split("#")[0].strip().strip("\"'").strip()
        return s

    @field_validator("YOOKASSA_SECRET_KEY", mode="before")
    @classmethod
    def clean_yookassa_secret_key(cls, v: Any) -> str:
        if v is None:
            return ""
        s = str(v).strip().strip("\"'").strip()
        if "#" in s:
            s = s.split("#")[0].strip().strip("\"'").strip()
        return s

    @field_validator("YOOKASSA_RETURN_URL", mode="before")
    @classmethod
    def clean_yookassa_return_url(cls, v: Any) -> str:
        if not v:
            return "https://yourdomain.com/payment/success"
        s = str(v).strip().strip("\"'").strip()
        if "#" in s:
            s = s.split("#")[0].strip().strip("\"'").strip()
        return s

    # Web
    SECRET_KEY: str = "change_me"

    @field_validator("SECRET_KEY", mode="before")
    @classmethod
    def ensure_secure_secret_key(cls, v: Any) -> str:
        s = str(v or "").strip().strip("\"'").strip()
        insecure_defaults = {"change_me", "change_this_to_random_secret_64chars", "secret", "default", ""}
        if not s or s in insecure_defaults or len(s) < 32:
            import secrets, os, logging
            new_key = secrets.token_hex(32)
            logging.getLogger(__name__).warning(
                "[SECURITY] Insecure or missing SECRET_KEY detected. Automatically generated a strong 64-character secret key."
            )
            env_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env"))
            try:
                if os.path.exists(env_path) and os.access(env_path, os.W_OK):
                    with open(env_path, "r", encoding="utf-8") as f:
                        content = f.read()
                    if "SECRET_KEY=" in content:
                        lines = content.splitlines()
                        new_lines = []
                        for line in lines:
                            if line.strip().startswith("SECRET_KEY="):
                                new_lines.append(f"SECRET_KEY={new_key}")
                            else:
                                new_lines.append(line)
                        new_content = "\n".join(new_lines) + ("\n" if content.endswith("\n") else "")
                    else:
                        new_content = content + f"\nSECRET_KEY={new_key}\n"
                    with open(env_path, "w", encoding="utf-8") as f:
                        f.write(new_content)
                    logging.getLogger(__name__).info(f"[SECURITY] Successfully persisted generated SECRET_KEY to {env_path}")
            except Exception as e:
                logging.getLogger(__name__).warning(f"[SECURITY] Could not persist SECRET_KEY to .env: {e}")
            return new_key
        return s
    WEB_HOST: str = "0.0.0.0"
    WEB_PORT: int = 8000
    DOMAIN: str = "https://stud-match.ru"

    @property
    def webapp_url(self) -> str:
        domain = (self.DOMAIN or "").strip()
        if "yourdomain.com" in domain or not domain:
            domain = "stud-match.ru"
        clean = domain.replace("https://", "").replace("http://", "").strip("/")
        return f"https://{clean}/app"

    # Prices (RUB)
    PRICE_SUPERLIKE_3: int = 99
    PRICE_SUPERLIKE_10: int = 249
    PRICE_BOOST_24H: int = 149

    SUPERADMIN_ID: int = 149620234

    @property
    def admin_ids(self) -> List[int]:
        ids = [self.SUPERADMIN_ID]
        if self.ADMIN_TG_IDS:
            ids.extend([int(x.strip()) for x in self.ADMIN_TG_IDS.split(",") if x.strip() and x.strip().isdigit()])
        return list(set(ids))

    @property
    def ADMIN_IDS(self) -> str:
        return self.ADMIN_TG_IDS or ""



settings = Settings()
