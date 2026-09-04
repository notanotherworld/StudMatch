"""Add missing enum values to achievementtype and paymentproduct

Revision ID: 022_add_enum_values
Revises: 021_performance_indexes
"""
from alembic import op

revision = "022_add_enum_values"
down_revision = "021_performance_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        # Новые типы достижений
        for val in [
            "case_participant",
            "place_3",
            "place_2",
            "place_1",
            "volunteer",
            "internship",
            "forum_attender",
            "forum_speaker",
        ]:
            op.execute(f"ALTER TYPE achievementtype ADD VALUE IF NOT EXISTS '{val}'")

        # Новые продукты оплаты
        for val in ["superlike_1", "superlike_5", "premium_1m"]:
            op.execute(f"ALTER TYPE paymentproduct ADD VALUE IF NOT EXISTS '{val}'")


def downgrade() -> None:
    pass
