"""Delete legacy mock test profiles 900000001-900000010

Revision ID: 014_delete_legacy_mock_profiles
Revises: 013_targeted_broadcasts
"""
from alembic import op
import sqlalchemy as sa

revision = "014_delete_legacy_mock_profiles"
down_revision = "013_targeted_broadcasts"
branch_labels = None
depends_on = None

TEST_IDS = list(range(900000001, 900000011))


def upgrade() -> None:
    conn = op.get_bind()
    ids_tuple = tuple(TEST_IDS)
    conn.execute(sa.text(f"DELETE FROM swipes WHERE from_user_id IN :ids OR to_user_id IN :ids"), {"ids": ids_tuple})
    conn.execute(sa.text(f"DELETE FROM matches WHERE user1_id IN :ids OR user2_id IN :ids"), {"ids": ids_tuple})
    conn.execute(sa.text(f"DELETE FROM achievements WHERE user_id IN :ids"), {"ids": ids_tuple})
    conn.execute(sa.text(f"DELETE FROM reports WHERE reporter_id IN :ids OR reported_id IN :ids"), {"ids": ids_tuple})
    conn.execute(sa.text(f"DELETE FROM email_verification_tokens WHERE user_id IN :ids"), {"ids": ids_tuple})
    conn.execute(sa.text(f"DELETE FROM profiles WHERE user_id IN :ids"), {"ids": ids_tuple})
    conn.execute(sa.text(f"DELETE FROM users WHERE id IN :ids"), {"ids": ids_tuple})


def downgrade() -> None:
    pass
