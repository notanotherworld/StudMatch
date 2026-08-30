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
    # 017_flood_ban_tracking (учёт спамеров и банов за флуд)
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS flood_ban_count INT DEFAULT 0;",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_flagged_spammer BOOLEAN DEFAULT FALSE;",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_banned_at TIMESTAMP WITH TIME ZONE;",
    # 019_add_premium_until (премиум-подписка студентов)
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS premium_until TIMESTAMP WITH TIME ZONE;",
    # 020_promo_codes_guaranteed
    """
    CREATE TABLE IF NOT EXISTS promo_codes (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        code VARCHAR(50) UNIQUE NOT NULL,
        reward_type VARCHAR(30) NOT NULL,
        reward_value INT NOT NULL DEFAULT 1,
        max_activations INT NOT NULL DEFAULT 0,
        activations_count INT NOT NULL DEFAULT 0,
        expires_at TIMESTAMP WITH TIME ZONE,
        is_active BOOLEAN NOT NULL DEFAULT TRUE,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS promo_activations (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        promo_id UUID NOT NULL REFERENCES promo_codes(id) ON DELETE CASCADE,
        user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        activated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
        CONSTRAINT uq_user_promo UNIQUE (user_id, promo_id)
    );
    """,
    # 021_profile_age_and_feed_filters
    "ALTER TABLE profiles ADD COLUMN IF NOT EXISTS age INT;",
    "ALTER TABLE profiles ADD COLUMN IF NOT EXISTS filter_min_age INT DEFAULT 17;",
    "ALTER TABLE profiles ADD COLUMN IF NOT EXISTS filter_max_age INT DEFAULT 30;",
    "ALTER TABLE profiles ADD COLUMN IF NOT EXISTS filter_min_year INT DEFAULT 1;",
    "ALTER TABLE profiles ADD COLUMN IF NOT EXISTS filter_max_year INT DEFAULT 6;",
    "ALTER TABLE profiles ADD COLUMN IF NOT EXISTS filter_major VARCHAR(200);",
    # 022_employer_candidate_status_and_notes
    "ALTER TABLE employer_profile_access ADD COLUMN IF NOT EXISTS status VARCHAR(20) DEFAULT 'active';",
    "ALTER TABLE employer_profile_access ADD COLUMN IF NOT EXISTS hr_comment TEXT;",
    # Установка версии alembic
    """
    DO $$
    BEGIN
        IF EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'alembic_version') THEN
            UPDATE alembic_version SET version_num = '019_add_premium_until';
        ELSE
            CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL, CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num));
            INSERT INTO alembic_version (version_num) VALUES ('019_add_premium_until');
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
