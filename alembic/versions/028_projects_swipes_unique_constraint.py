"""Split swipes unique constraint into partial unique indexes for profiles and projects

Revision ID: 028_projects_swipes_unique_constraint
Revises: 027_internal_economy_and_shop
"""
from alembic import op
import sqlalchemy as sa


revision = "028_projects_swipes_unique_constraint"
down_revision = "027_internal_economy_and_shop"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name == "postgresql":
        # 1. Drop the restrictive old unique constraint that blocked multiple project swipes per author
        op.execute("ALTER TABLE swipes DROP CONSTRAINT IF EXISTS uq_swipe_pair_mode;")

        # 2. Clean up any existing duplicate swipes in PostgreSQL (preserving the latest row)
        op.execute("""
            DELETE FROM swipes a USING swipes b
            WHERE a.ctid < b.ctid
              AND a.to_project_id IS NULL
              AND b.to_project_id IS NULL
              AND a.from_user_id = b.from_user_id
              AND a.to_user_id = b.to_user_id
              AND a.mode = b.mode;
        """)
        op.execute("""
            DELETE FROM swipes a USING swipes b
            WHERE a.ctid < b.ctid
              AND a.to_project_id IS NOT NULL
              AND b.to_project_id IS NOT NULL
              AND a.from_user_id = b.from_user_id
              AND a.to_project_id = b.to_project_id;
        """)

        # 3. Create partial unique indexes:
        # One for profile swipes (dating/career): unique per (from_user_id, to_user_id, mode)
        op.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_swipe_pair_mode_user 
            ON swipes (from_user_id, to_user_id, mode) 
            WHERE to_project_id IS NULL;
        """)
        # One for project swipes (projects mode): unique per (from_user_id, to_project_id)
        op.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_swipe_pair_project 
            ON swipes (from_user_id, to_project_id) 
            WHERE to_project_id IS NOT NULL;
        """)
    else:
        # SQLite / tests fallback
        try:
            op.execute("DROP INDEX IF EXISTS uq_swipe_pair_mode;")
        except Exception:
            pass
        try:
            op.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS uq_swipe_pair_mode_user 
                ON swipes (from_user_id, to_user_id, mode) 
                WHERE to_project_id IS NULL;
            """)
            op.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS uq_swipe_pair_project 
                ON swipes (from_user_id, to_project_id) 
                WHERE to_project_id IS NOT NULL;
            """)
        except Exception:
            pass


def downgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS uq_swipe_pair_project;")
        op.execute("DROP INDEX IF EXISTS uq_swipe_pair_mode_user;")
        op.execute("""
            DO $$ 
            BEGIN 
                IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_swipe_pair_mode') THEN 
                    ALTER TABLE swipes ADD CONSTRAINT uq_swipe_pair_mode UNIQUE (from_user_id, to_user_id, mode); 
                END IF; 
            END $$;
        """)
    else:
        try:
            op.execute("DROP INDEX IF EXISTS uq_swipe_pair_project;")
            op.execute("DROP INDEX IF EXISTS uq_swipe_pair_mode_user;")
        except Exception:
            pass
