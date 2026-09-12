"""Add in-app chat messages and telegram reveal approval columns

Revision ID: 024_in_app_chat_and_telegram_reveal
Revises: 023_swipe_modes_and_recycling
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "024_in_app_chat_and_telegram_reveal"
down_revision = "023_swipe_modes_and_recycling"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name == "postgresql":
        op.execute("ALTER TABLE matches ADD COLUMN IF NOT EXISTS user1_tg_approved BOOLEAN DEFAULT FALSE;")
        op.execute("ALTER TABLE matches ADD COLUMN IF NOT EXISTS user2_tg_approved BOOLEAN DEFAULT FALSE;")
        op.execute("ALTER TABLE matches ADD COLUMN IF NOT EXISTS tg_unlocked_at TIMESTAMP WITH TIME ZONE;")
        op.execute("UPDATE matches SET user1_tg_approved = FALSE WHERE user1_tg_approved IS NULL;")
        op.execute("UPDATE matches SET user2_tg_approved = FALSE WHERE user2_tg_approved IS NULL;")
        op.execute("""
            CREATE TABLE IF NOT EXISTS chat_messages (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                match_id UUID NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
                sender_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                text TEXT NOT NULL,
                msg_type VARCHAR(20) NOT NULL DEFAULT 'text',
                is_read BOOLEAN NOT NULL DEFAULT FALSE,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            );
        """)
        op.execute("CREATE INDEX IF NOT EXISTS idx_chat_messages_match_created ON chat_messages (match_id, created_at);")
        op.execute("CREATE INDEX IF NOT EXISTS idx_chat_messages_unread ON chat_messages (match_id, sender_id, is_read);")
    else:
        # SQLite / fallback
        try:
            op.add_column("matches", sa.Column("user1_tg_approved", sa.Boolean(), server_default="0", nullable=True))
            op.add_column("matches", sa.Column("user2_tg_approved", sa.Boolean(), server_default="0", nullable=True))
            op.add_column("matches", sa.Column("tg_unlocked_at", sa.DateTime(timezone=True), nullable=True))
        except Exception:
            pass


def downgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name == "postgresql":
        op.execute("DROP TABLE IF EXISTS chat_messages CASCADE;")
        op.execute("ALTER TABLE matches DROP COLUMN IF EXISTS user1_tg_approved;")
        op.execute("ALTER TABLE matches DROP COLUMN IF EXISTS user2_tg_approved;")
        op.execute("ALTER TABLE matches DROP COLUMN IF EXISTS tg_unlocked_at;")
    else:
        pass
