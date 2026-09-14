"""Add projects mode to modeenum, create projects table, and add project fields

Revision ID: 026_projects_mode_and_tables
Revises: 025_support_tickets
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "026_projects_mode_and_tables"
down_revision = "025_support_tickets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name == "postgresql":
        # 1. Add 'projects' to modeenum (must be executed in autocommit block in PostgreSQL)
        with op.get_context().autocommit_block():
            op.execute("ALTER TYPE modeenum ADD VALUE IF NOT EXISTS 'projects';")

        # 2. Create projects table
        op.execute("""
            CREATE TABLE IF NOT EXISTS projects (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                title VARCHAR(200) NOT NULL,
                pitch VARCHAR(300) NOT NULL,
                description TEXT NOT NULL,
                stage VARCHAR(50) NOT NULL DEFAULT 'idea',
                required_roles VARCHAR[],
                conditions VARCHAR(100),
                demo_url VARCHAR(300),
                pitchdeck_url TEXT,
                cover_url VARCHAR(300),
                is_active BOOLEAN NOT NULL DEFAULT true,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            );
        """)
        op.execute("CREATE INDEX IF NOT EXISTS idx_projects_user_id ON projects (user_id);")
        op.execute("CREATE INDEX IF NOT EXISTS idx_projects_active_created ON projects (is_active, created_at);")
        op.execute("CREATE INDEX IF NOT EXISTS idx_projects_stage ON projects (stage);")

        # 3. Add project fields to profiles
        op.execute("""
            ALTER TABLE profiles 
            ADD COLUMN IF NOT EXISTS project_role VARCHAR(100),
            ADD COLUMN IF NOT EXISTS project_skills TEXT,
            ADD COLUMN IF NOT EXISTS project_bio TEXT,
            ADD COLUMN IF NOT EXISTS project_is_complete BOOLEAN NOT NULL DEFAULT false;
        """)

        # 4. Add to_project_id to swipes
        op.execute("""
            ALTER TABLE swipes 
            ADD COLUMN IF NOT EXISTS to_project_id UUID REFERENCES projects(id) ON DELETE CASCADE;
        """)
        op.execute("CREATE INDEX IF NOT EXISTS idx_swipes_to_project_id ON swipes (to_project_id);")

        # 5. Add project_id to matches
        op.execute("""
            ALTER TABLE matches 
            ADD COLUMN IF NOT EXISTS project_id UUID REFERENCES projects(id) ON DELETE SET NULL;
        """)
        op.execute("CREATE INDEX IF NOT EXISTS idx_matches_project_id ON matches (project_id);")
    else:
        # SQLite / tests fallback
        try:
            op.create_table(
                "projects",
                sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
                sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False),
                sa.Column("title", sa.String(200), nullable=False),
                sa.Column("pitch", sa.String(300), nullable=False),
                sa.Column("description", sa.Text(), nullable=False),
                sa.Column("stage", sa.String(50), server_default="idea", nullable=False),
                sa.Column("required_roles", sa.JSON(), nullable=True),
                sa.Column("conditions", sa.String(100), nullable=True),
                sa.Column("demo_url", sa.String(300), nullable=True),
                sa.Column("pitchdeck_url", sa.Text(), nullable=True),
                sa.Column("cover_url", sa.String(300), nullable=True),
                sa.Column("is_active", sa.Boolean(), server_default="1", nullable=False),
                sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
                sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            )
        except Exception:
            pass

        try:
            op.add_column("profiles", sa.Column("project_role", sa.String(100), nullable=True))
            op.add_column("profiles", sa.Column("project_skills", sa.Text(), nullable=True))
            op.add_column("profiles", sa.Column("project_bio", sa.Text(), nullable=True))
            op.add_column("profiles", sa.Column("project_is_complete", sa.Boolean(), server_default="0", nullable=False))
        except Exception:
            pass

        try:
            op.add_column("swipes", sa.Column("to_project_id", sa.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=True))
        except Exception:
            pass

        try:
            op.add_column("matches", sa.Column("project_id", sa.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="SET NULL"), nullable=True))
        except Exception:
            pass


def downgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name == "postgresql":
        op.execute("ALTER TABLE matches DROP COLUMN IF EXISTS project_id;")
        op.execute("ALTER TABLE swipes DROP COLUMN IF EXISTS to_project_id;")
        op.execute("""
            ALTER TABLE profiles 
            DROP COLUMN IF EXISTS project_role,
            DROP COLUMN IF EXISTS project_skills,
            DROP COLUMN IF EXISTS project_bio,
            DROP COLUMN IF EXISTS project_is_complete;
        """)
        op.execute("DROP TABLE IF EXISTS projects CASCADE;")
    else:
        pass
