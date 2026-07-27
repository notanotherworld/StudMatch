"""Seed: добавляем РУДН и базовые теги интересов.

Revision ID: 001_seed
Revises: 
Create Date: 2026-07-23
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import table, column
from sqlalchemy import String, Integer, Boolean, Text

revision = "001_seed"
down_revision = "000_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Таблица universities ──────────────────────────────────────
    universities_table = table(
        "universities",
        column("id", Integer),
        column("name", Text),
        column("short_name", String),
        column("email_domains", Text),
        column("city", String),
        column("is_active", Boolean),
    )

    op.bulk_insert(
        universities_table,
        [
            {
                "id": 1,
                "name": "Российский университет дружбы народов",
                "short_name": "РУДН",
                "email_domains": "@rudn.ru,@pfur.ru,@student.rudn.ru",
                "city": "Москва",
                "is_active": True,
            }
        ],
    )

    # ── Теги интересов ─────────────────────────────────────────────
    tags_table = table(
        "interest_tags",
        column("id", Integer),
        column("name", String),
        column("emoji", String),
    )

    op.bulk_insert(
        tags_table,
        [
            {"id": 1,  "name": "IT",          "emoji": "💻"},
            {"id": 2,  "name": "Бизнес",      "emoji": "💼"},
            {"id": 3,  "name": "Спорт",       "emoji": "⚽"},
            {"id": 4,  "name": "Музыка",      "emoji": "🎵"},
            {"id": 5,  "name": "Кино",        "emoji": "🎬"},
            {"id": 6,  "name": "Игры",        "emoji": "🎮"},
            {"id": 7,  "name": "Наука",       "emoji": "🔬"},
            {"id": 8,  "name": "Медицина",    "emoji": "🏥"},
            {"id": 9,  "name": "Право",       "emoji": "⚖️"},
            {"id": 10, "name": "Дизайн",      "emoji": "🎨"},
            {"id": 11, "name": "Путешествия", "emoji": "✈️"},
            {"id": 12, "name": "Кулинария",   "emoji": "🍳"},
            {"id": 13, "name": "Языки",       "emoji": "🌍"},
            {"id": 14, "name": "Экология",    "emoji": "🌿"},
            {"id": 15, "name": "Финансы",     "emoji": "📈"},
        ],
    )


def downgrade() -> None:
    op.execute("DELETE FROM interest_tags WHERE id <= 15")
    op.execute("DELETE FROM universities WHERE id = 1")
