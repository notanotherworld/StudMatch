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
    # 1. Add mode column to swipes using existing modeenum
    mode_enum = postgresql.ENUM("career", "dating", name="modeenum", create_type=False)
    op.add_column(
        "swipes",
        sa.Column("mode", mode_enum, nullable=False, server_default="dating"),
    )

    # 2. Update unique constraint: drop uq_swipe_pair, add uq_swipe_pair_mode
    op.drop_constraint("uq_swipe_pair", "swipes", type_="unique")
    op.create_unique_constraint(
        "uq_swipe_pair_mode", "swipes", ["from_user_id", "to_user_id", "mode"]
    )

    # 3. Create performance indexes for smart recycling & incoming likes
    op.create_index(
        "idx_swipes_viewer_mode_action_created",
        "swipes",
        ["from_user_id", "mode", "action", "created_at"],
    )
    op.create_index(
        "idx_swipes_target_mode_action",
        "swipes",
        ["to_user_id", "mode", "action"],
    )


def downgrade() -> None:
    op.drop_index("idx_swipes_target_mode_action", table_name="swipes")
    op.drop_index("idx_swipes_viewer_mode_action_created", table_name="swipes")
    op.drop_constraint("uq_swipe_pair_mode", "swipes", type_="unique")
    op.create_unique_constraint("uq_swipe_pair", "swipes", ["from_user_id", "to_user_id"])
    op.drop_column("swipes", "mode")
