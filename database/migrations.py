"""
Автоматическая синхронизация схемы базы данных при старте приложения.
Гарантирует наличие всех колонок (включая is_fake, auto_match_mode, career_*)
без блокировки event loop и сбоев Alembic.
"""
import logging
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)

MIGRATION_STATEMENTS = [
    # 011_dual_profiles
    "ALTER TABLE profiles ADD COLUMN IF NOT EXISTS career_avatar_file_id VARCHAR(200);",
    "ALTER TABLE profiles ADD COLUMN IF NOT EXISTS career_goal TEXT;",
    "ALTER TABLE profiles ADD COLUMN IF NOT EXISTS career_skills INTEGER[];",
    "ALTER TABLE profiles ADD COLUMN IF NOT EXISTS career_custom_skills TEXT;",
    "ALTER TABLE profiles ADD COLUMN IF NOT EXISTS career_portfolio_url VARCHAR(300);",
    "ALTER TABLE profiles ADD COLUMN IF NOT EXISTS career_work_format VARCHAR(50);",
    "ALTER TABLE profiles ADD COLUMN IF NOT EXISTS career_is_complete BOOLEAN DEFAULT FALSE;",
    # 012_fake_users
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_fake BOOLEAN DEFAULT FALSE;",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS auto_match_mode VARCHAR(20) DEFAULT 'instant';",
    # 013_targeted_broadcasts
    "ALTER TABLE broadcast_logs ADD COLUMN IF NOT EXISTS target_filters TEXT;",
    "ALTER TABLE broadcast_logs ADD COLUMN IF NOT EXISTS photo_url VARCHAR(300);",
    "ALTER TABLE broadcast_logs ADD COLUMN IF NOT EXISTS button_text VARCHAR(100);",
    "ALTER TABLE broadcast_logs ADD COLUMN IF NOT EXISTS button_url VARCHAR(500);",
    "ALTER TABLE broadcast_logs ADD COLUMN IF NOT EXISTS scheduled_at TIMESTAMP WITH TIME ZONE;",
    "ALTER TABLE broadcast_logs ADD COLUMN IF NOT EXISTS status VARCHAR(20) DEFAULT 'completed';",
    # Установка версии alembic
    """
    DO $$
    BEGIN
        IF EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'alembic_version') THEN
            UPDATE alembic_version SET version_num = '013_targeted_broadcasts';
        ELSE
            CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL, CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num));
            INSERT INTO alembic_version (version_num) VALUES ('013_targeted_broadcasts');
        END IF;
    END $$;
    """
]


async def ensure_database_schema(engine: AsyncEngine) -> None:
    """Выполняет DDL-скрипты добавления новых колонок при старте."""
    try:
        async with engine.begin() as conn:
            for stmt in MIGRATION_STATEMENTS:
                await conn.execute(text(stmt))
        logger.info("✅ Схема базы данных успешно проверена и синхронизирована!")
    except Exception as e:
        logger.error(f"❌ Ошибка синхронизации схемы базы данных: {e}", exc_info=True)
