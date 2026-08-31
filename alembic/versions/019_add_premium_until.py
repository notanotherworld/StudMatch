"""Add premium_until column to users table

Revision ID: 019_add_premium_until
Revises: 018_fix_database_sequences
"""
from alembic import op
import sqlalchemy as sa

revision = "019_add_premium_until"
down_revision = "018_fix_database_sequences"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("ALTER TABLE users ADD COLUMN IF NOT EXISTS premium_until TIMESTAMP WITH TIME ZONE;"))


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("ALTER TABLE users DROP COLUMN IF EXISTS premium_until;"))
