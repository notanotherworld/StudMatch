"""Add photos and video_file_id columns to Profile model

Revision ID: 015_profile_multi_media
Revises: 014_delete_legacy_mock_profiles
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "015_profile_multi_media"
down_revision = "014_delete_legacy_mock_profiles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("ALTER TABLE profiles ADD COLUMN IF NOT EXISTS photos TEXT[];"))
    conn.execute(sa.text("ALTER TABLE profiles ADD COLUMN IF NOT EXISTS video_file_id VARCHAR(200);"))


def downgrade() -> None:
    pass
