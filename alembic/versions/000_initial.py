"""Initial schema: создание всех таблиц СтудМэч.

Revision ID: 000_initial
Revises:
Create Date: 2026-07-23
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "000_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── universities ─────────────────────────────────────────────
    op.create_table(
        "universities",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("short_name", sa.String(20), nullable=False),
        sa.Column("email_domains", sa.Text(), nullable=False),
        sa.Column("city", sa.String(100), nullable=False),
        sa.Column("is_active", sa.Boolean(), default=True, nullable=False),
    )

    # ── interest_tags ────────────────────────────────────────────
    op.create_table(
        "interest_tags",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(50), nullable=False, unique=True),
        sa.Column("emoji", sa.String(10), default="🏷", nullable=False),
    )

    # ── admins ───────────────────────────────────────────────────
    op.create_table(
        "admins",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("login", sa.String(64), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.Enum("superadmin", "moderator", name="adminrole"), nullable=False, server_default="moderator"),
        sa.Column("tg_user_id", sa.BigInteger(), nullable=True),
        sa.Column("last_login", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), default=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    # ── employers ────────────────────────────────────────────────
    op.create_table(
        "employers",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("company_name", sa.String(200), nullable=False),
        sa.Column("contact_name", sa.String(100), nullable=False),
        sa.Column("login", sa.String(64), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("admins.id"), nullable=True),
        sa.Column("is_active", sa.Boolean(), default=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    # ── users ────────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tg_username", sa.String(64), nullable=True),
        sa.Column("email", sa.String(255), nullable=True, unique=True),
        sa.Column("email_verified", sa.Boolean(), default=False, nullable=False),
        sa.Column("university_id", sa.Integer(), sa.ForeignKey("universities.id"), nullable=True),
        sa.Column("consent_given", sa.Boolean(), default=False, nullable=False),
        sa.Column("consent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), default=True, nullable=False),
        sa.Column("mode", sa.Enum("career", "dating", name="modeenum"), nullable=False, server_default="dating"),
        sa.Column("superlike_balance", sa.Integer(), default=0, nullable=False),
        sa.Column("boost_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    # ── profiles ─────────────────────────────────────────────────
    op.create_table(
        "profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False, unique=True),
        sa.Column("name", sa.String(100), nullable=True),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("major", sa.String(200), nullable=True),
        sa.Column("interest_ids", postgresql.ARRAY(sa.Integer()), nullable=True),
        sa.Column("goal", sa.Text(), nullable=True),
        sa.Column("avatar_file_id", sa.String(200), nullable=True),
        sa.Column("rating_score", sa.Float(), default=0.0, nullable=False),
        sa.Column("is_visible", sa.Boolean(), default=True, nullable=False),
        sa.Column("is_complete", sa.Boolean(), default=False, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    # ── email_tokens ─────────────────────────────────────────────
    op.create_table(
        "email_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("token", sa.String(6), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used", sa.Boolean(), default=False, nullable=False),
    )

    # ── achievements ─────────────────────────────────────────────
    op.create_table(
        "achievements",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("type", sa.Enum("gpa", "competition", "case", "olympiad", "diploma", "publication", "participation", name="achievementtype"), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("document_url", sa.Text(), nullable=True),
        sa.Column("score", sa.Float(), default=0.0, nullable=False),
        sa.Column("verified", sa.Enum("pending", "approved", "rejected", name="verifiedstatus"), nullable=False, server_default="pending"),
        sa.Column("verified_by", sa.Integer(), sa.ForeignKey("admins.id"), nullable=True),
        sa.Column("reject_reason", sa.Text(), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    # ── swipes ───────────────────────────────────────────────────
    op.create_table(
        "swipes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("from_user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("to_user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("action", sa.Enum("like", "superlike", "skip", name="swipeaction"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("from_user_id", "to_user_id", name="uq_swipe_pair"),
    )

    # ── matches ──────────────────────────────────────────────────
    op.create_table(
        "matches",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user1_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("user2_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("mode", sa.Enum("career", "dating", name="modeenum"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    # ── employer_profile_access ───────────────────────────────────
    op.create_table(
        "employer_profile_access",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("employer_id", sa.Integer(), sa.ForeignKey("employers.id"), nullable=False),
        sa.Column("profile_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("profiles.id"), nullable=False),
        sa.Column("granted_by", sa.Integer(), sa.ForeignKey("admins.id"), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("granted_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("viewed_at", sa.DateTime(timezone=True), nullable=True),
    )

    # ── payments ─────────────────────────────────────────────────
    op.create_table(
        "payments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("yookassa_payment_id", sa.String(100), nullable=True, unique=True),
        sa.Column("product", sa.Enum("superlike_3", "superlike_10", "boost_24h", name="paymentproduct"), nullable=False),
        sa.Column("amount_rub", sa.Numeric(10, 2), nullable=False),
        sa.Column("status", sa.Enum("pending", "succeeded", "canceled", name="paymentstatus"), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )

    # ── Индексы для производительности ───────────────────────────
    op.create_index("ix_users_email", "users", ["email"])
    op.create_index("ix_users_university_id", "users", ["university_id"])
    op.create_index("ix_profiles_rating_score", "profiles", ["rating_score"])
    op.create_index("ix_achievements_user_id", "achievements", ["user_id"])
    op.create_index("ix_swipes_from_user_id", "swipes", ["from_user_id"])
    op.create_index("ix_swipes_to_user_id", "swipes", ["to_user_id"])
    op.create_index("ix_employer_profile_access_employer_id", "employer_profile_access", ["employer_id"])


def downgrade() -> None:
    op.drop_table("payments")
    op.drop_table("employer_profile_access")
    op.drop_table("matches")
    op.drop_table("swipes")
    op.drop_table("achievements")
    op.drop_table("email_tokens")
    op.drop_table("profiles")
    op.drop_table("users")
    op.drop_table("employers")
    op.drop_table("admins")
    op.drop_table("interest_tags")
    op.drop_table("universities")

    for enum in ["adminrole", "modeenum", "achievementtype", "verifiedstatus", "swipeaction", "paymentproduct", "paymentstatus"]:
        op.execute(f"DROP TYPE IF EXISTS {enum}")
