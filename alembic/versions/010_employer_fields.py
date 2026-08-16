"""Add company_description, vacancies_description, tg_contact, and website to employers table

Revision ID: 010_employer_fields
Revises: 009_promo_and_settings
"""
from alembic import op
import sqlalchemy as sa

revision = "010_employer_fields"
down_revision = "009_promo_and_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("employers", sa.Column("company_description", sa.Text(), nullable=True))
    op.add_column("employers", sa.Column("vacancies_description", sa.Text(), nullable=True))
    op.add_column("employers", sa.Column("tg_contact", sa.String(length=100), nullable=True))
    op.add_column("employers", sa.Column("website", sa.String(length=200), nullable=True))


def downgrade() -> None:
    op.drop_column("employers", "website")
    op.drop_column("employers", "tg_contact")
    op.drop_column("employers", "vacancies_description")
    op.drop_column("employers", "company_description")
