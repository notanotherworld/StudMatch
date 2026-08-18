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
    # 014_delete_legacy_mock_profiles (полное каскадное удаление старых тестовых анкет 900000001..900000010)
    "UPDATE users SET referrer_id = NULL WHERE referrer_id BETWEEN 900000001 AND 900000010;",
    "DELETE FROM swipes WHERE from_user_id BETWEEN 900000001 AND 900000010 OR to_user_id BETWEEN 900000001 AND 900000010;",
    "DELETE FROM matches WHERE user1_id BETWEEN 900000001 AND 900000010 OR user2_id BETWEEN 900000001 AND 900000010;",
    "DELETE FROM achievements WHERE user_id BETWEEN 900000001 AND 900000010;",
    "DELETE FROM payments WHERE user_id BETWEEN 900000001 AND 900000010;",
    "DELETE FROM reports WHERE reporter_id BETWEEN 900000001 AND 900000010 OR reported_id BETWEEN 900000001 AND 900000010;",
    "DELETE FROM data_export_requests WHERE user_id BETWEEN 900000001 AND 900000010;",
    "DELETE FROM email_tokens WHERE user_id BETWEEN 900000001 AND 900000010;",
    "DELETE FROM promo_activations WHERE user_id BETWEEN 900000001 AND 900000010;",
    "DELETE FROM profiles WHERE user_id BETWEEN 900000001 AND 900000010;",
    "DELETE FROM users WHERE id BETWEEN 900000001 AND 900000010;",
    # 015_profile_multi_media (до 3 фото и 1 видео в профиле)
    "ALTER TABLE profiles ADD COLUMN IF NOT EXISTS photos TEXT[];",
    "ALTER TABLE profiles ADD COLUMN IF NOT EXISTS video_file_id VARCHAR(200);",
    # 016_emergency_shield_settings (параметры экстренной остановки и защиты от атак)
    "INSERT INTO system_settings (key, value, description) VALUES ('emergency_mode', 'false', 'Экстренная остановка бота') ON CONFLICT (key) DO NOTHING;",
    "INSERT INTO system_settings (key, value, description) VALUES ('freeze_registrations', 'false', 'Заморозка новых регистраций') ON CONFLICT (key) DO NOTHING;",
    "INSERT INTO system_settings (key, value, description) VALUES ('anti_flood_strict', 'false', 'Усиленный режим защиты от атак и флуда') ON CONFLICT (key) DO NOTHING;",
    "INSERT INTO system_settings (key, value, description) VALUES ('emergency_message', '🚨 <b>Сервер временно недоступен</b>\n\nВключён режим защиты от перегрузки. Мы восстановим доступ в ближайшее время!', 'Сообщение при экстренной остановке') ON CONFLICT (key) DO NOTHING;",
    # Установка версии alembic
    """
    DO $$
    BEGIN
        IF EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'alembic_version') THEN
            UPDATE alembic_version SET version_num = '016_emergency_shield_settings';
        ELSE
            CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL, CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num));
            INSERT INTO alembic_version (version_num) VALUES ('016_emergency_shield_settings');
        END IF;
    END $$;
    """
]


async def ensure_database_schema(engine: AsyncEngine) -> None:
    """Выполняет DDL-скрипты добавления новых колонок при старте без остановки приложения."""
    for stmt in MIGRATION_STATEMENTS:
        try:
            async with engine.begin() as conn:
                await conn.execute(text(stmt))
        except Exception as e:
            logger.warning(f"⚠️ Ошибка выполнения миграции '{stmt[:40]}...': {e}")
    logger.info("✅ Схема базы данных успешно проверена и синхронизирована!")
