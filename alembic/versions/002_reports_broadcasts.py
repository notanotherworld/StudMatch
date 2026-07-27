"""Add reports and broadcast_logs tables.

Revision ID: 002_reports_broadcasts
Revises: 001_seed
Create Date: 2026-07-24
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "002_reports_broadcasts"
down_revision = "001_seed"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── reports (жалобы) ─────────────────────────────────────────
    op.create_table(
        "reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("reporter_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("reported_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("status", sa.Enum("pending", "resolved", "dismissed", name="reportstatus"),
                  nullable=False, server_default="pending"),
        sa.Column("resolved_by", sa.Integer(), sa.ForeignKey("admins.id"), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("reporter_id", "reported_id", name="uq_report_pair"),
    )
    op.create_index("ix_reports_status", "reports", ["status"])
    op.create_index("ix_reports_reported_id", "reports", ["reported_id"])

    # ── broadcast_logs (история рассылок) ────────────────────────
    op.create_table(
        "broadcast_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("admin_id", sa.Integer(), sa.ForeignKey("admins.id"), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("target", sa.String(50), nullable=False),   # all / verified / career / dating
        sa.Column("sent_count", sa.Integer(), default=0, nullable=False),
        sa.Column("failed_count", sa.Integer(), default=0, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
    )

    # ── data_export_requests (запросы на выгрузку ПД) ────────────
    op.create_table(
        "data_export_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("status", sa.Enum("pending", "sent", name="exportstatus"),
                  nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_data_export_requests_status", "data_export_requests", ["status"])


def downgrade() -> None:
    op.drop_table("data_export_requests")
    op.drop_table("broadcast_logs")
    op.drop_table("reports")
    for enum in ["reportstatus", "exportstatus"]:
        op.execute(f"DROP TYPE IF EXISTS {enum}")
