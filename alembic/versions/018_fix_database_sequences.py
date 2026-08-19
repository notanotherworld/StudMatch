"""Fix PostgreSQL sequence out of sync for interest_tags, universities, admins, employers

Revision ID: 018_fix_database_sequences
Revises: 017_flood_ban_tracking
"""
from alembic import op
import sqlalchemy as sa

revision = "018_fix_database_sequences"
down_revision = "017_flood_ban_tracking"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    tables_to_sync = [
        ("interest_tags", "id", "interest_tags_id_seq"),
        ("universities", "id", "universities_id_seq"),
        ("admins", "id", "admins_id_seq"),
        ("employers", "id", "employers_id_seq"),
    ]
    for table_name, col, seq_name in tables_to_sync:
        conn.execute(sa.text(f"""
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_class WHERE relkind = 'S' AND relname = '{seq_name}') THEN
                    PERFORM setval('{seq_name}', COALESCE((SELECT MAX({col}) FROM {table_name}), 1));
                END IF;
            END $$;
        """))


def downgrade() -> None:
    pass
