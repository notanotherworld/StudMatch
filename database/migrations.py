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
    "ALTER TABLE employer_profile_access ADD COLUMN IF NOT EXISTS status VARCHAR(20) DEFAULT 'new';",
    "ALTER TABLE employer_profile_access ADD COLUMN IF NOT EXISTS hr_comment TEXT;",
    "ALTER TABLE employer_profile_access ADD COLUMN IF NOT EXISTS hr_rating INT DEFAULT 0;",
    "ALTER TABLE employer_profile_access ADD COLUMN IF NOT EXISTS hr_recommendation VARCHAR(30);",
    "ALTER TABLE employer_profile_access ADD COLUMN IF NOT EXISTS hr_tags TEXT;",
    # 023_employer_requests
    """
    CREATE TABLE IF NOT EXISTS employer_requests (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        employer_id INT NOT NULL REFERENCES employers(id) ON DELETE CASCADE,
        title VARCHAR(255) NOT NULL,
        direction VARCHAR(100) DEFAULT 'IT / Разработка',
        skills_required TEXT,
        work_format VARCHAR(50) DEFAULT 'Любой',
        candidates_count INT DEFAULT 5,
        comment TEXT,
        status VARCHAR(30) DEFAULT 'pending',
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
        updated_at TIMESTAMP WITH TIME ZONE
    );
    """,
    # 024_add_enum_values (добавление новых типов достижений и тарифов в enum-типы PostgreSQL)
    "ALTER TYPE achievementtype ADD VALUE IF NOT EXISTS 'case_participant';",
    "ALTER TYPE achievementtype ADD VALUE IF NOT EXISTS 'place_3';",
    "ALTER TYPE achievementtype ADD VALUE IF NOT EXISTS 'place_2';",
    "ALTER TYPE achievementtype ADD VALUE IF NOT EXISTS 'place_1';",
    "ALTER TYPE achievementtype ADD VALUE IF NOT EXISTS 'volunteer';",
    "ALTER TYPE achievementtype ADD VALUE IF NOT EXISTS 'internship';",
    "ALTER TYPE achievementtype ADD VALUE IF NOT EXISTS 'forum_attender';",
    "ALTER TYPE achievementtype ADD VALUE IF NOT EXISTS 'forum_speaker';",
    "ALTER TYPE paymentproduct ADD VALUE IF NOT EXISTS 'superlike_1';",
    "ALTER TYPE paymentproduct ADD VALUE IF NOT EXISTS 'superlike_5';",
    # 025_swipe_modes_and_recycling (режимы свайпов и умный ресайклинг анкет)
    """
    DO $$ 
    BEGIN 
        IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='swipes' AND column_name='mode') THEN 
            ALTER TABLE swipes ADD COLUMN mode modeenum NOT NULL DEFAULT 'dating'; 
        END IF; 
        UPDATE swipes SET mode = 'dating' WHERE mode IS NULL;
        
        ALTER TABLE swipes DROP CONSTRAINT IF EXISTS uq_swipe_pair;

        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_swipe_pair_mode') THEN 
            ALTER TABLE swipes ADD CONSTRAINT uq_swipe_pair_mode UNIQUE (from_user_id, to_user_id, mode); 
        END IF; 
    END $$;
    """,
    "CREATE INDEX IF NOT EXISTS idx_swipes_viewer_mode_action_created ON swipes (from_user_id, mode, action, created_at);",
    "CREATE INDEX IF NOT EXISTS idx_swipes_target_mode_action ON swipes (to_user_id, mode, action);",
    # Заполнение возраста для анкет без возраста (старые и тестовые анкеты)
    "UPDATE profiles SET age = LEAST(17 + COALESCE(year, 1), 25) WHERE age IS NULL;",
    # 026_in_app_chat_and_telegram_reveal
    "ALTER TABLE matches ADD COLUMN IF NOT EXISTS user1_tg_approved BOOLEAN DEFAULT FALSE;",
    "ALTER TABLE matches ADD COLUMN IF NOT EXISTS user2_tg_approved BOOLEAN DEFAULT FALSE;",
    "ALTER TABLE matches ADD COLUMN IF NOT EXISTS tg_unlocked_at TIMESTAMP WITH TIME ZONE;",
    """
    CREATE TABLE IF NOT EXISTS chat_messages (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        match_id UUID NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
        sender_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        text TEXT NOT NULL,
        msg_type VARCHAR(20) NOT NULL DEFAULT 'text',
        is_read BOOLEAN NOT NULL DEFAULT FALSE,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_chat_messages_match_created ON chat_messages (match_id, created_at);",
    # 027_add_last_active_at
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_active_at TIMESTAMP WITH TIME ZONE;",
    # 028_user_privacy_settings
    """
    CREATE TABLE IF NOT EXISTS user_privacy_settings (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id BIGINT NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
        online_visibility VARCHAR(20) NOT NULL DEFAULT 'all',
        message_permission VARCHAR(20) NOT NULL DEFAULT 'matches',
        allow_employer_access BOOLEAN NOT NULL DEFAULT TRUE,
        hide_age BOOLEAN NOT NULL DEFAULT FALSE,
        hide_course BOOLEAN NOT NULL DEFAULT FALSE,
        hide_email BOOLEAN NOT NULL DEFAULT FALSE,
        private_photos TEXT[] DEFAULT '{}',
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_user_privacy_user_id ON user_privacy_settings (user_id);",
    # 029_support_tickets
    """
    DO $$ 
    BEGIN 
        IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'ticketstatus') THEN
            CREATE TYPE ticketstatus AS ENUM ('open', 'in_progress', 'resolved', 'closed');
        END IF;
    END $$;
    """,
    """
    CREATE TABLE IF NOT EXISTS support_tickets (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        category VARCHAR(50) NOT NULL DEFAULT 'other',
        subject VARCHAR(200),
        message TEXT NOT NULL,
        screenshot_url VARCHAR(500),
        device_info TEXT,
        status ticketstatus NOT NULL DEFAULT 'open',
        admin_reply TEXT,
        resolved_by INTEGER REFERENCES admins(id) ON DELETE SET NULL,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
        resolved_at TIMESTAMP WITH TIME ZONE
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_support_tickets_user_id ON support_tickets (user_id);",
    "CREATE INDEX IF NOT EXISTS idx_support_tickets_status ON support_tickets (status);",
    "CREATE INDEX IF NOT EXISTS idx_support_tickets_created_at ON support_tickets (created_at);",
    # Установка версии alembic
    """
    DO $$
    BEGIN
        IF EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'alembic_version') THEN
            ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(64);
            UPDATE alembic_version SET version_num = '029_support_tickets';
        ELSE
            CREATE TABLE alembic_version (version_num VARCHAR(64) NOT NULL, CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num));
            INSERT INTO alembic_version (version_num) VALUES ('029_support_tickets');
        END IF;
    END $$;
    """
]


async def ensure_database_schema(engine: AsyncEngine) -> None:
    """Выполняет DDL-скрипты добавления новых колонок при старте без остановки приложения."""
    if engine.dialect.name == "sqlite":
        return

    for stmt in MIGRATION_STATEMENTS:
        try:
            async with engine.connect() as conn:
                await conn.execution_options(isolation_level="AUTOCOMMIT")
                await conn.execute(text(stmt))
        except Exception:
            try:
                async with engine.begin() as conn:
                    await conn.execute(text(stmt))
            except Exception as e:
                logger.warning(f"⚠️ Ошибка выполнения миграции '{stmt[:40]}...': {e}")
    logger.info("✅ Схема базы данных успешно проверена и синхронизирована!")
