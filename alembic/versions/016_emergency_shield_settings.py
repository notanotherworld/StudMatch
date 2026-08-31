"""Add emergency shield and attack protection settings to system_settings

Revision ID: 016_emergency_shield_settings
Revises: 015_profile_multi_media
"""
from alembic import op
import sqlalchemy as sa

revision = "016_emergency_shield_settings"
down_revision = "015_profile_multi_media"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("INSERT INTO system_settings (key, value, description) VALUES ('emergency_mode', 'false', 'Экстренная остановка бота') ON CONFLICT (key) DO NOTHING;"))
    conn.execute(sa.text("INSERT INTO system_settings (key, value, description) VALUES ('freeze_registrations', 'false', 'Заморозка новых регистраций') ON CONFLICT (key) DO NOTHING;"))
    conn.execute(sa.text("INSERT INTO system_settings (key, value, description) VALUES ('anti_flood_strict', 'false', 'Усиленный режим защиты от атак и флуда') ON CONFLICT (key) DO NOTHING;"))
    conn.execute(sa.text("INSERT INTO system_settings (key, value, description) VALUES ('emergency_message', '🚨 <b>Сервер временно недоступен</b>\\n\\nВключён режим защиты от перегрузки. Мы восстановим доступ в ближайшее время!', 'Сообщение при экстренной остановке') ON CONFLICT (key) DO NOTHING;"))


def downgrade() -> None:
    pass
