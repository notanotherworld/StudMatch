"""Add internal economy, shop items, transactions, daily quests, and inventory

Revision ID: 027_internal_economy_and_shop
Revises: 026_projects_mode_and_tables
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "027_internal_economy_and_shop"
down_revision = "026_projects_mode_and_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name == "postgresql":
        # 1. Add economy fields to users
        op.execute("""
            ALTER TABLE users 
            ADD COLUMN IF NOT EXISTS credits_balance INT DEFAULT 0,
            ADD COLUMN IF NOT EXISTS streak_days INT DEFAULT 0,
            ADD COLUMN IF NOT EXISTS last_streak_date TIMESTAMP WITH TIME ZONE,
            ADD COLUMN IF NOT EXISTS streak_freeze_count INT DEFAULT 0,
            ADD COLUMN IF NOT EXISTS equipped_frame VARCHAR(50);
        """)

        # 2. Create shop_items table
        op.execute("""
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
        """)
        op.execute("CREATE INDEX IF NOT EXISTS idx_shop_items_category ON shop_items (category);")

        # 3. Create economy_transactions table
        op.execute("""
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
        """)
        op.execute("CREATE INDEX IF NOT EXISTS idx_econ_tx_user_created ON economy_transactions (user_id, created_at);")
        op.execute("CREATE INDEX IF NOT EXISTS idx_econ_tx_type ON economy_transactions (tx_type);")

        # 4. Create user_daily_quests table
        op.execute("""
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
        """)
        op.execute("CREATE INDEX IF NOT EXISTS idx_daily_quests_user_date ON user_daily_quests (user_id, quest_date);")

        # 5. Create user_inventory table
        op.execute("""
            CREATE TABLE IF NOT EXISTS user_inventory (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                item_code VARCHAR(50) NOT NULL,
                quantity INT NOT NULL DEFAULT 1,
                expires_at TIMESTAMP WITH TIME ZONE,
                is_equipped BOOLEAN NOT NULL DEFAULT FALSE,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            );
        """)
        op.execute("CREATE INDEX IF NOT EXISTS idx_inventory_user_code ON user_inventory (user_id, item_code);")

        # 6. Seed shop items
        op.execute("""
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
        """)


def downgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name == "postgresql":
        op.execute("DROP TABLE IF EXISTS user_inventory CASCADE;")
        op.execute("DROP TABLE IF EXISTS user_daily_quests CASCADE;")
        op.execute("DROP TABLE IF EXISTS economy_transactions CASCADE;")
        op.execute("DROP TABLE IF EXISTS shop_items CASCADE;")
        op.execute("""
            ALTER TABLE users 
            DROP COLUMN IF EXISTS credits_balance,
            DROP COLUMN IF EXISTS streak_days,
            DROP COLUMN IF EXISTS last_streak_date,
            DROP COLUMN IF EXISTS streak_freeze_count,
            DROP COLUMN IF EXISTS equipped_frame;
        """)
