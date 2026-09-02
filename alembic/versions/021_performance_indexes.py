"""Add performance indexes for swipes, matches and profiles

Revision ID: 021_performance_indexes
Revises: 020_employer_requests
"""
from alembic import op
import sqlalchemy as sa

revision = "021_performance_indexes"
down_revision = "020_employer_requests"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("""
        -- Индексы для таблицы swipes
        CREATE INDEX IF NOT EXISTS idx_swipes_to_user_action 
            ON swipes (to_user_id, action);
            
        CREATE INDEX IF NOT EXISTS idx_swipes_from_user_action 
            ON swipes (from_user_id, action);

        -- Индексы для таблицы matches
        CREATE INDEX IF NOT EXISTS idx_matches_users_1_2 
            ON matches (user1_id, user2_id);
            
        CREATE INDEX IF NOT EXISTS idx_matches_users_2_1 
            ON matches (user2_id, user1_id);
            
        CREATE INDEX IF NOT EXISTS idx_matches_created_at 
            ON matches (created_at DESC);

        -- Индекс для ленты анкет
        CREATE INDEX IF NOT EXISTS idx_profiles_feed_active 
            ON profiles (is_visible, is_complete, rating_score DESC);
    """))


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("""
        DROP INDEX IF EXISTS idx_profiles_feed_active;
        DROP INDEX IF EXISTS idx_matches_created_at;
        DROP INDEX IF EXISTS idx_matches_users_2_1;
        DROP INDEX IF EXISTS idx_matches_users_1_2;
        DROP INDEX IF EXISTS idx_swipes_from_user_action;
        DROP INDEX IF EXISTS idx_swipes_to_user_action;
    """))
