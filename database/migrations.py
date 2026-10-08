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
        ALTER TABLE swipes DROP CONSTRAINT IF EXISTS uq_swipe_pair_mode;
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
    # 026_projects_mode_and_tables
    "ALTER TYPE modeenum ADD VALUE IF NOT EXISTS 'projects';",
    """
    CREATE TABLE IF NOT EXISTS projects (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        title VARCHAR(200) NOT NULL,
        pitch VARCHAR(300) NOT NULL,
        description TEXT NOT NULL,
        stage VARCHAR(50) NOT NULL DEFAULT 'idea',
        required_roles VARCHAR[],
        conditions VARCHAR(100),
        demo_url VARCHAR(300),
        pitchdeck_url TEXT,
        cover_url VARCHAR(300),
        is_active BOOLEAN NOT NULL DEFAULT true,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_projects_user_id ON projects (user_id);",
    "CREATE INDEX IF NOT EXISTS idx_projects_active_created ON projects (is_active, created_at);",
    "CREATE INDEX IF NOT EXISTS idx_projects_stage ON projects (stage);",
    "ALTER TABLE profiles ADD COLUMN IF NOT EXISTS project_role VARCHAR(100);",
    "ALTER TABLE profiles ADD COLUMN IF NOT EXISTS project_skills TEXT;",
    "ALTER TABLE profiles ADD COLUMN IF NOT EXISTS project_bio TEXT;",
    "ALTER TABLE profiles ADD COLUMN IF NOT EXISTS project_is_complete BOOLEAN DEFAULT FALSE;",
    "ALTER TABLE swipes ADD COLUMN IF NOT EXISTS to_project_id UUID REFERENCES projects(id) ON DELETE CASCADE;",
    "CREATE INDEX IF NOT EXISTS idx_swipes_to_project_id ON swipes (to_project_id);",
    "ALTER TABLE matches ADD COLUMN IF NOT EXISTS project_id UUID REFERENCES projects(id) ON DELETE SET NULL;",
    "CREATE INDEX IF NOT EXISTS idx_matches_project_id ON matches (project_id);",
    # 027_internal_economy_and_shop
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS credits_balance INT DEFAULT 0;",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS streak_days INT DEFAULT 0;",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_streak_date TIMESTAMP WITH TIME ZONE;",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS streak_freeze_count INT DEFAULT 0;",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS equipped_frame VARCHAR(50);",
    """
    CREATE TABLE IF NOT EXISTS shop_items (
        id SERIAL PRIMARY KEY,
        code VARCHAR(50) UNIQUE NOT NULL,
        title VARCHAR(100) NOT NULL,
        description TEXT,
        category VARCHAR(30) NOT NULL DEFAULT 'consumable',
        price_credits INT NOT NULL DEFAULT 0,
        price_rub INT,
        icon VARCHAR(20) DEFAULT '🛍',
        bonus_type VARCHAR(50),
        bonus_value INT DEFAULT 1,
        duration_days INT,
        is_active BOOLEAN NOT NULL DEFAULT TRUE,
        sort_order INT DEFAULT 0,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_shop_items_category ON shop_items (category);",
    """
    CREATE TABLE IF NOT EXISTS economy_transactions (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        amount INT NOT NULL,
        balance_after INT NOT NULL,
        tx_type VARCHAR(30) NOT NULL,
        reference_id VARCHAR(100),
        description VARCHAR(255) NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_econ_tx_user_created ON economy_transactions (user_id, created_at);",
    "CREATE INDEX IF NOT EXISTS idx_econ_tx_type ON economy_transactions (tx_type);",
    """
    CREATE TABLE IF NOT EXISTS user_daily_quests (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        quest_date TIMESTAMP WITH TIME ZONE NOT NULL,
        quest_key VARCHAR(50) NOT NULL,
        current_progress INT DEFAULT 0,
        target_progress INT NOT NULL DEFAULT 1,
        reward_credits INT NOT NULL DEFAULT 10,
        is_claimed BOOLEAN NOT NULL DEFAULT FALSE,
        claimed_at TIMESTAMP WITH TIME ZONE,
        CONSTRAINT uq_user_daily_quest UNIQUE (user_id, quest_date, quest_key)
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_daily_quests_user_date ON user_daily_quests (user_id, quest_date);",
    """
    CREATE TABLE IF NOT EXISTS user_permanent_quests (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        quest_key VARCHAR(50) NOT NULL,
        current_progress INT DEFAULT 0,
        target_progress INT NOT NULL DEFAULT 1,
        reward_credits INT NOT NULL DEFAULT 50,
        reward_badge VARCHAR(100),
        is_claimed BOOLEAN NOT NULL DEFAULT FALSE,
        claimed_at TIMESTAMP WITH TIME ZONE,
        CONSTRAINT uq_user_permanent_quest UNIQUE (user_id, quest_key)
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_perm_quests_user ON user_permanent_quests (user_id);",
    """
    CREATE TABLE IF NOT EXISTS user_inventory (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        item_code VARCHAR(50) NOT NULL,
        quantity INT NOT NULL DEFAULT 1,
        expires_at TIMESTAMP WITH TIME ZONE,
        is_equipped BOOLEAN NOT NULL DEFAULT FALSE,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_inventory_user_code ON user_inventory (user_id, item_code);",
    # Начальный посев товаров в магазин
    """
    INSERT INTO shop_items (code, title, description, category, price_credits, price_rub, icon, bonus_type, bonus_value, duration_days, sort_order)
    VALUES
        ('superlike_1', '⭐️ Суперлайк', 'Мгновенное уведомление с вашим сообщением прямо на экран', 'consumable', 15, NULL, '⭐️', 'superlike', 1, NULL, 10),
        ('superlike_5', '⭐️ Пакет 5 суперлайков', 'Выгодный пакет из 5 суперлайков', 'consumable', 65, NULL, '⭐️', 'superlike', 5, NULL, 20),
        ('rewind', '🔄 «Шпора» (Откат свайпа)', 'Возможность отменить последний случайный дизлайк или пропуск', 'consumable', 10, NULL, '🔄', 'rewind', 1, NULL, 30),
        ('boost_24h', '⚡️ Буст анкеты 24ч', 'Показ анкеты первым в ленте на 24 часа', 'consumable', 80, 99, '⚡️', 'boost', 24, NULL, 40),
        ('freeze_streak', '🩺 «Справка от врача»', 'Защита серии посещений: спасает стрик при пропуске одного дня', 'insurance', 25, NULL, '🩺', 'freeze', 1, NULL, 50),
        ('premium_1d', '💎 Премиум 1 день', 'Суточный тест-драйв всех премиум возможностей', 'subscription', 30, NULL, '💎', 'premium', 1, 1, 60),
        ('premium_7d', '💎 Премиум 7 дней', 'Неделя безлимитных лайков, фильтров и режима инкогнито', 'subscription', 120, NULL, '💎', 'premium', 7, 7, 70),
        ('premium_30d', '💎 Премиум 30 дней', 'Месяц максимального комфорта и привилегий', 'subscription', 400, 199, '💎', 'premium', 30, 30, 80),
        ('frame_gold', '🥇 Рамка «Отличник»', 'Золотая статусная рамка профиля на 30 дней', 'cosmetic', 150, NULL, '🥇', 'frame', 1, 30, 90),
        ('frame_headman', '👔 Рамка «Староста»', 'Официальный бейдж лидера на 30 дней', 'cosmetic', 150, NULL, '👔', 'frame', 1, 30, 100),
        ('frame_neon', '🌌 Неоновый стиль', 'Яркий киберпанк градиент карточки на 30 дней', 'cosmetic', 200, NULL, '🌌', 'frame', 1, 30, 110)
    ON CONFLICT (code) DO NOTHING;
    """,
    # 028_credit_packs_and_starter_pack
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS has_bought_starter_pack BOOLEAN DEFAULT FALSE;",
    "ALTER TYPE paymentproduct ADD VALUE IF NOT EXISTS 'starter_pack_99';",
    "ALTER TYPE paymentproduct ADD VALUE IF NOT EXISTS 'credits_100';",
    "ALTER TYPE paymentproduct ADD VALUE IF NOT EXISTS 'credits_300';",
    "ALTER TYPE paymentproduct ADD VALUE IF NOT EXISTS 'credits_700';",
    "ALTER TYPE paymentproduct ADD VALUE IF NOT EXISTS 'credits_1500';",
    "ALTER TYPE paymentproduct ADD VALUE IF NOT EXISTS 'credits_3000';",
    "ALTER TYPE paymentproduct ADD VALUE IF NOT EXISTS 'credits_6000';",
    # 029_fortune_wheel_and_gifts
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_fortune_spin_at TIMESTAMP WITH TIME ZONE;",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS fortune_spins_count INT DEFAULT 0;",
    """
    CREATE TABLE IF NOT EXISTS user_received_gifts (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        sender_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
        recipient_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        gift_code VARCHAR(50) NOT NULL,
        gift_title VARCHAR(100) NOT NULL,
        gift_icon VARCHAR(20) NOT NULL,
        message VARCHAR(200),
        is_anonymous BOOLEAN DEFAULT FALSE,
        is_pinned BOOLEAN DEFAULT FALSE,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_gifts_recipient_created ON user_received_gifts (recipient_id, created_at);",
    "CREATE INDEX IF NOT EXISTS idx_gifts_sender_created ON user_received_gifts (sender_id, created_at);",
    # 028_fix_projects_swipes_unique_constraint (Раздельные уникальные индексы для анкет и проектов)
    "ALTER TABLE swipes DROP CONSTRAINT IF EXISTS uq_swipe_pair_mode;",
    """
    DELETE FROM swipes a USING swipes b
    WHERE a.ctid < b.ctid
      AND a.to_project_id IS NULL
      AND b.to_project_id IS NULL
      AND a.from_user_id = b.from_user_id
      AND a.to_user_id = b.to_user_id
      AND a.mode = b.mode;
    """,
    """
    DELETE FROM swipes a USING swipes b
    WHERE a.ctid < b.ctid
      AND a.to_project_id IS NOT NULL
      AND b.to_project_id IS NOT NULL
      AND a.from_user_id = b.from_user_id
      AND a.to_project_id = b.to_project_id;
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_swipe_pair_mode_user 
    ON swipes (from_user_id, to_user_id, mode) 
    WHERE to_project_id IS NULL;
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_swipe_pair_project 
    ON swipes (from_user_id, to_project_id) 
    WHERE to_project_id IS NOT NULL;
    """,
    # 030_economy_onboarding_unique_idx (Защита от дублирования разовых наград H4)
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_econ_tx_onboarding 
    ON economy_transactions (user_id, reference_id) 
    WHERE tx_type IN ('onboarding', 'referral');
    """,
    # 031_duolingo_streak_retention_system
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS today_swipes_count INT DEFAULT 0;",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_activity_date TIMESTAMP WITH TIME ZONE;",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS streak_broken_at TIMESTAMP WITH TIME ZONE;",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS streak_repair_available BOOLEAN DEFAULT FALSE;",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS streak_milestones_claimed INT[];",
    # Установка версии alembic
    """
    DO $$
    BEGIN
        IF EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'alembic_version') THEN
            ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(64);
            UPDATE alembic_version SET version_num = '031_duolingo_streak_retention_system';
        ELSE
            CREATE TABLE alembic_version (version_num VARCHAR(64) NOT NULL, CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num));
            INSERT INTO alembic_version (version_num) VALUES ('031_duolingo_streak_retention_system');
        END IF;
    END $$;
    """
]


async def ensure_database_schema(engine: AsyncEngine) -> None:
    """Выполняет DDL-скрипты добавления новых колонок при старте без остановки приложения."""
    if engine.dialect.name == "sqlite":
        from database.models import Base, ShopItem, Admin, AdminRole
        from database.session import AsyncSessionLocal
        from sqlalchemy import select, update
        import bcrypt

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

            def sync_sqlite_columns(sync_conn):
                for table_name, table in Base.metadata.tables.items():
                    res = sync_conn.exec_driver_sql(f"PRAGMA table_info('{table_name}')").fetchall()
                    if not res:
                        continue
                    existing_cols = {row[1] for row in res}
                    for col in table.columns:
                        if col.name not in existing_cols:
                            col_type = col.type.compile(engine.dialect)
                            default_clause = ""
                            if col.server_default is not None and hasattr(col.server_default, "arg"):
                                default_clause = f" DEFAULT {col.server_default.arg}"
                            elif col.default is not None and hasattr(col.default, "arg") and not callable(col.default.arg):
                                val = col.default.arg
                                if isinstance(val, bool):
                                    default_clause = f" DEFAULT {'1' if val else '0'}"
                                elif isinstance(val, (int, float)):
                                    default_clause = f" DEFAULT {val}"
                                elif isinstance(val, str):
                                    default_clause = f" DEFAULT '{val}'"
                            sql = f"ALTER TABLE {table_name} ADD COLUMN {col.name} {col_type}{default_clause}"
                            try:
                                sync_conn.exec_driver_sql(sql)
                                logger.info(f"Добавлена колонка {table_name}.{col.name} ({col_type})")
                            except Exception as e:
                                logger.warning(f"Не удалось добавить колонку {table_name}.{col.name}: {e}")

            await conn.run_sync(sync_sqlite_columns)

            def create_sqlite_indexes(sync_conn):
                try:
                    sync_conn.exec_driver_sql(
                        "CREATE UNIQUE INDEX IF NOT EXISTS uq_econ_tx_onboarding "
                        "ON economy_transactions (user_id, reference_id) "
                        "WHERE tx_type IN ('onboarding', 'referral');"
                    )
                except Exception as e:
                    logger.debug(f"SQLite unique index note: {e}")

            await conn.run_sync(create_sqlite_indexes)

        async with AsyncSessionLocal() as session:
            # Посев каталога товаров
            items_count = (await session.execute(select(ShopItem))).scalars().first()
            if not items_count:
                default_items = [
                    ShopItem(code="superlike_1", title="⭐️ Суперлайк", description="Мгновенное уведомление с вашим сообщением прямо на экран", category="consumable", price_credits=15, icon="⭐️", bonus_type="superlike", bonus_value=1, sort_order=10),
                    ShopItem(code="superlike_5", title="⭐️ Пакет 5 суперлайков", description="Выгодный пакет из 5 суперлайков", category="consumable", price_credits=65, icon="⭐️", bonus_type="superlike", bonus_value=5, sort_order=20),
                    ShopItem(code="rewind", title="🔄 «Шпора» (Откат свайпа)", description="Возможность отменить последний случайный дизлайк или пропуск", category="consumable", price_credits=10, icon="🔄", bonus_type="rewind", bonus_value=1, sort_order=30),
                    ShopItem(code="boost_24h", title="⚡️ Буст анкеты 24ч", description="Показ анкеты первым в ленте на 24 часа", category="consumable", price_credits=80, price_rub=99, icon="⚡️", bonus_type="boost", bonus_value=24, sort_order=40),
                    ShopItem(code="freeze_streak", title="🩺 «Справка от врача»", description="Защита серии посещений: спасает стрик при пропуске одного дня", category="insurance", price_credits=25, icon="🩺", bonus_type="freeze", bonus_value=1, sort_order=50),
                    ShopItem(code="premium_7d", title="💎 Премиум 7 дней", description="Неделя безлимитных лайков, фильтров и режима инкогнито", category="subscription", price_credits=120, icon="💎", bonus_type="premium", bonus_value=7, duration_days=7, sort_order=70),
                    ShopItem(code="premium_30d", title="💎 Премиум 30 дней", description="Месяц максимального комфорта и привилегий", category="subscription", price_credits=250, price_rub=199, icon="💎", bonus_type="premium", bonus_value=30, duration_days=30, sort_order=80),
                    ShopItem(code="frame_gold", title="🥇 Рамка «Отличник»", description="Золотая статусная рамка профиля на 30 дней", category="cosmetic", price_credits=150, icon="🥇", bonus_type="frame", bonus_value=1, duration_days=30, sort_order=90),
                    ShopItem(code="frame_headman", title="👔 Рамка «Староста»", description="Официальный бейдж лидера на 30 дней", category="cosmetic", price_credits=150, icon="👔", bonus_type="frame", bonus_value=1, duration_days=30, sort_order=100),
                    ShopItem(code="frame_neon", title="🌌 Неоновый стиль", description="Яркий киберпанк градиент карточки на 30 дней", category="cosmetic", price_credits=200, icon="🌌", bonus_type="frame", bonus_value=1, duration_days=30, sort_order=110),
                ]
                session.add_all(default_items)
                await session.commit()
            else:
                # Синхронизация цен и деактивация 1-дневного премиума во избежание фарма x3 квестов
                await session.execute(
                    update(ShopItem).where(ShopItem.code == "premium_1d").values(is_active=False)
                )
                await session.execute(
                    update(ShopItem).where(ShopItem.code == "premium_30d").values(price_credits=250)
                )
                await session.commit()

            # H12: Предсказуемый пароль по умолчанию удален во избежание уязвимости.
            # Администраторы создаются только вручную через scripts/create_admin.py
            admin_check = (await session.execute(select(Admin).limit(1))).scalars().first()
            if not admin_check:
                logger.info("ℹ️ В базе данных нет учётных записей администратора. Создайте её через: python create_admin.py")
        logger.info("✅ SQLite база данных и начальные данные успешно инициализированы!")
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
