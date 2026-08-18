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
    conn.execute(sa.text("UPDATE users SET referrer_id = NULL WHERE referrer_id IN :ids"), {"ids": ids_tuple})
    conn.execute(sa.text("DELETE FROM swipes WHERE from_user_id IN :ids OR to_user_id IN :ids"), {"ids": ids_tuple})
    conn.execute(sa.text("DELETE FROM matches WHERE user1_id IN :ids OR user2_id IN :ids"), {"ids": ids_tuple})
    conn.execute(sa.text("DELETE FROM achievements WHERE user_id IN :ids"), {"ids": ids_tuple})
    conn.execute(sa.text("DELETE FROM payments WHERE user_id IN :ids"), {"ids": ids_tuple})
    conn.execute(sa.text("DELETE FROM reports WHERE reporter_id IN :ids OR reported_id IN :ids"), {"ids": ids_tuple})
    conn.execute(sa.text("DELETE FROM data_export_requests WHERE user_id IN :ids"), {"ids": ids_tuple})
    conn.execute(sa.text("DELETE FROM email_tokens WHERE user_id IN :ids"), {"ids": ids_tuple})
    conn.execute(sa.text("DELETE FROM promo_activations WHERE user_id IN :ids"), {"ids": ids_tuple})
    conn.execute(sa.text("DELETE FROM profiles WHERE user_id IN :ids"), {"ids": ids_tuple})
    conn.execute(sa.text("DELETE FROM users WHERE id IN :ids"), {"ids": ids_tuple})


def downgrade() -> None:
    pass
