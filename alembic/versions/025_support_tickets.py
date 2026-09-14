"""Add support_tickets table for Support Deck

Revision ID: 025_support_tickets
Revises: 024_in_app_chat_and_tg_reveal
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "025_support_tickets"
down_revision = "024_in_app_chat_and_tg_reveal"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name == "postgresql":
        op.execute("""
            DO $$ BEGIN
                CREATE TYPE ticketstatus AS ENUM ('open', 'in_progress', 'resolved', 'closed');
            EXCEPTION
                WHEN duplicate_object THEN null;
            END $$;
        """)
        op.execute("""
            CREATE TABLE IF NOT EXISTS support_tickets (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                category VARCHAR(50) NOT NULL DEFAULT 'other',
                subject VARCHAR(200),
                message TEXT NOT NULL,
                screenshot_url VARCHAR(500),
                device_info TEXT,
                status ticketstatus NOT NULL DEFAULT 'open',
                admin_reply TEXT,
                resolved_by INTEGER REFERENCES admins(id) ON DELETE SET NULL,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                resolved_at TIMESTAMP WITH TIME ZONE
            );
        """)
        op.execute("CREATE INDEX IF NOT EXISTS idx_support_tickets_user_id ON support_tickets (user_id);")
        op.execute("CREATE INDEX IF NOT EXISTS idx_support_tickets_status ON support_tickets (status);")
        op.execute("CREATE INDEX IF NOT EXISTS idx_support_tickets_created_at ON support_tickets (created_at);")
    else:
        # SQLite / tests fallback
        try:
            op.create_table(
                "support_tickets",
                sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
                sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False),
                sa.Column("category", sa.String(length=50), server_default="other", nullable=False),
                sa.Column("subject", sa.String(length=200), nullable=True),
                sa.Column("message", sa.Text(), nullable=False),
                sa.Column("screenshot_url", sa.String(length=500), nullable=True),
                sa.Column("device_info", sa.Text(), nullable=True),
                sa.Column("status", sa.Enum("open", "in_progress", "resolved", "closed", name="ticketstatus"), server_default="open", index=True, nullable=False),
                sa.Column("admin_reply", sa.Text(), nullable=True),
                sa.Column("resolved_by", sa.Integer(), sa.ForeignKey("admins.id", ondelete="SET NULL"), nullable=True),
                sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), index=True, nullable=False),
                sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
                sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
            )
        except Exception:
            pass


def downgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name == "postgresql":
        op.execute("DROP TABLE IF EXISTS support_tickets CASCADE;")
        op.execute("DROP TYPE IF EXISTS ticketstatus CASCADE;")
    else:
        op.drop_table("support_tickets")
