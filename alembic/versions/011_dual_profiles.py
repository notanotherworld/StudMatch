"""Add career fields to profiles table for dual profiles (Dating vs Career)

Revision ID: 011_dual_profiles
Revises: 010_employer_fields
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY

revision = "011_dual_profiles"
down_revision = "010_employer_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("profiles", sa.Column("career_avatar_file_id", sa.String(length=200), nullable=True))
    op.add_column("profiles", sa.Column("career_goal", sa.Text(), nullable=True))
    op.add_column("profiles", sa.Column("career_skills", ARRAY(sa.Integer()), nullable=True))
    op.add_column("profiles", sa.Column("career_custom_skills", sa.Text(), nullable=True))
    op.add_column("profiles", sa.Column("career_portfolio_url", sa.String(length=300), nullable=True))
    op.add_column("profiles", sa.Column("career_work_format", sa.String(length=50), nullable=True))
    op.add_column("profiles", sa.Column("career_is_complete", sa.Boolean(), nullable=False, server_default="false"))


def downgrade() -> None:
    op.drop_column("profiles", "career_is_complete")
    op.drop_column("profiles", "career_work_format")
    op.drop_column("profiles", "career_portfolio_url")
    op.drop_column("profiles", "career_custom_skills")
    op.drop_column("profiles", "career_skills")
    op.drop_column("profiles", "career_goal")
    op.drop_column("profiles", "career_avatar_file_id")
