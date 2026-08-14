"""Create promo_codes, promo_activations, and system_settings tables

Revision ID: 009_promo_and_settings
Revises: 008_admin_audit_logs
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import table, column

revision = "009_promo_and_settings"
down_revision = "008_admin_audit_logs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── promo_codes ─────────────────────────────────────────────
    op.create_table(
        "promo_codes",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("reward_type", sa.String(length=30), nullable=False),
        sa.Column("reward_value", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("max_activations", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("activations_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_promo_codes_code", "promo_codes", ["code"], unique=True)

    # ── promo_activations ───────────────────────────────────────
    op.create_table(
        "promo_activations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("promo_id", UUID(as_uuid=True), sa.ForeignKey("promo_codes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "promo_id", name="uq_user_promo"),
    )
    op.create_index("ix_promo_activations_user_id", "promo_activations", ["user_id"])

    # ── system_settings ─────────────────────────────────────────
    system_settings_table = op.create_table(
        "system_settings",
        sa.Column("key", sa.String(length=100), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # ── Seed initial system settings ────────────────────────────
    op.bulk_insert(
        system_settings_table,
        [
            {"key": "maintenance_mode", "value": "false", "description": "Режим технических работ (true/false)"},
            {"key": "maintenance_message", "value": "🛠 <b>Бот на техническом обслуживании</b>\n\nМы проводим плановое обновление. Бот скоро возобновит работу!", "description": "Сообщение при техработах"},
            {"key": "price_superlike_3", "value": "99", "description": "Цена 3 суперлайков (руб.)"},
            {"key": "price_superlike_10", "value": "249", "description": "Цена 10 суперлайков (руб.)"},
            {"key": "price_boost_24h", "value": "149", "description": "Цена буста анкеты на 24 часа (руб.)"},
            {"key": "referral_reward_superlikes", "value": "3", "description": "Количество суперлайков за приглашённого друга"},
            {"key": "require_email_verification", "value": "true", "description": "Обязательная верификация email студента (true/false)"},
            {"key": "reward_score_gpa", "value": "20", "description": "Баллы за отличную успеваемость (GPA)"},
            {"key": "reward_score_olympiad", "value": "50", "description": "Баллы за олимпиаду"},
            {"key": "reward_score_competition", "value": "40", "description": "Баллы за соревнование / хакатон"},
            {"key": "reward_score_participation", "value": "15", "description": "Баллы за активность / участие"},
        ],
    )


def downgrade() -> None:
    op.drop_table("system_settings")
    op.drop_table("promo_activations")
    op.drop_table("promo_codes")
