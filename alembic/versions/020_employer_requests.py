"""Add employer_requests table and status columns

Revision ID: 020_employer_requests
Revises: 019_add_premium_until
"""
from alembic import op
import sqlalchemy as sa

revision = "020_employer_requests"
down_revision = "019_add_premium_until"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS employer_requests (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            employer_id INT NOT NULL REFERENCES employers(id) ON DELETE CASCADE,
            title VARCHAR(150) NOT NULL,
            direction VARCHAR(100) NOT NULL,
            work_format VARCHAR(50) NOT NULL DEFAULT 'Удаленно',
            skills_required TEXT,
            candidates_count INT NOT NULL DEFAULT 5,
            comment TEXT,
            status VARCHAR(30) NOT NULL DEFAULT 'pending',
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        );
    """))
    conn.execute(sa.text("ALTER TABLE employer_profile_accesses ADD COLUMN IF NOT EXISTS status VARCHAR(30) DEFAULT 'active';"))
    conn.execute(sa.text("ALTER TABLE employer_profile_accesses ADD COLUMN IF NOT EXISTS hr_comment TEXT;"))


def downgrade() -> None:
    pass
