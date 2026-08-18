"""Add flood_ban_count, is_flagged_spammer, and last_banned_at columns to User model

Revision ID: 017_flood_ban_tracking
Revises: 016_emergency_shield_settings
"""
from alembic import op
import sqlalchemy as sa

revision = "017_flood_ban_tracking"
down_revision = "016_emergency_shield_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("ALTER TABLE users ADD COLUMN IF NOT EXISTS flood_ban_count INT DEFAULT 0;"))
    conn.execute(sa.text("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_flagged_spammer BOOLEAN DEFAULT FALSE;"))
    conn.execute(sa.text("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_banned_at TIMESTAMP WITH TIME ZONE;"))


def downgrade() -> None:
    pass
