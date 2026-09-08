"""Add mode to swipes and support smart recycling

Revision ID: 023_swipe_modes_and_recycling
Revises: 022_add_enum_values
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "023_swipe_modes_and_recycling"
down_revision = "022_add_enum_values"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name == "postgresql":
        op.execute("""
            DO $$ 
            BEGIN 
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns 
                    WHERE table_name = 'swipes' AND column_name = 'mode'
                ) THEN 
                    ALTER TABLE swipes ADD COLUMN mode modeenum NOT NULL DEFAULT 'dating'; 
                END IF; 
                
                ALTER TABLE swipes DROP CONSTRAINT IF EXISTS uq_swipe_pair;

                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint WHERE conname = 'uq_swipe_pair_mode'
                ) THEN 
                    ALTER TABLE swipes ADD CONSTRAINT uq_swipe_pair_mode UNIQUE (from_user_id, to_user_id, mode); 
                END IF; 
            END $$;
        """)
        op.execute("CREATE INDEX IF NOT EXISTS idx_swipes_viewer_mode_action_created ON swipes (from_user_id, mode, action, created_at);")
        op.execute("CREATE INDEX IF NOT EXISTS idx_swipes_target_mode_action ON swipes (to_user_id, mode, action);")
    else:
        try:
            mode_enum = sa.Enum("career", "dating", name="modeenum")
            op.add_column("swipes", sa.Column("mode", mode_enum, nullable=False, server_default="dating"))
        except Exception:
            pass


def downgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS idx_swipes_target_mode_action;")
        op.execute("DROP INDEX IF EXISTS idx_swipes_viewer_mode_action_created;")
        op.execute("ALTER TABLE swipes DROP CONSTRAINT IF EXISTS uq_swipe_pair_mode;")
        op.execute("""
            DO $$ 
            BEGIN 
                IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_swipe_pair') THEN 
                    ALTER TABLE swipes ADD CONSTRAINT uq_swipe_pair UNIQUE (from_user_id, to_user_id); 
                END IF; 
            END $$;
        """)
        op.execute("ALTER TABLE swipes DROP COLUMN IF EXISTS mode;")
    else:
        pass
