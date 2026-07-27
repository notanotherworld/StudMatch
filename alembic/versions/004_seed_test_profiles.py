"""Seed 10 test student profiles for browsing and testing.

Revision ID: 004_seed_test_profiles
Revises: 003_swipe_comment
Create Date: 2026-07-28
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import table, column
import uuid
from datetime import datetime, timezone

revision = "004_seed_test_profiles"
down_revision = "003_swipe_comment"
branch_labels = None
depends_on = None

TEST_USERS = [
    {
        "id": 900000001,
        "name": "Алексей Громов",
        "year": 3,
        "major": "Искусственный интеллект и Data Science",
        "goal": "Ищу сильную команду на кейс-чемпионаты и стартап в области ИИ 🚀",
        "rating": 185.0,
        "interests": [1, 2, 3],
        "mode": "career",
    },
    {
        "id": 900000002,
        "name": "Анастасия Соколова",
        "year": 2,
        "major": "Веб-дизайн и UX/UI",
        "goal": "Хочу делать сочный дизайн для хакатон-проектов и общаться ✨",
        "rating": 140.0,
        "interests": [1, 4, 5],
        "mode": "dating",
    },
    {
        "id": 900000003,
        "name": "Михаил Ковалёв",
        "year": 4,
        "major": "Юриспруденция и Международное право",
        "goal": "Ищу единомышленников для правовых кейсов и просто хороших друзей ⚖️",
        "rating": 210.0,
        "interests": [2, 3, 6],
        "mode": "career",
    },
    {
        "id": 900000004,
        "name": "Екатерина Морозова",
        "year": 1,
        "major": "Международный менеджмент",
        "goal": "Готова организовать команду на кейс-чемпионат и взять на себя питчинг! 💼",
        "rating": 95.0,
        "interests": [2, 4, 5],
        "mode": "career",
    },
    {
        "id": 900000005,
        "name": "Дмитрий Волков",
        "year": 3,
        "major": "Разработка ПО и Backend",
        "goal": "Пишу на Python/Go, ищу фронтендера и дизайнера для хакатона! 💻",
        "rating": 160.0,
        "interests": [1, 3, 5],
        "mode": "career",
    },
    {
        "id": 900000006,
        "name": "София Васильева",
        "year": 2,
        "major": "Лечебное дело (Медицинский институт)",
        "goal": "Ищу верных друзей, единомышленников и участие в волонтёрских проектах 🩺",
        "rating": 120.0,
        "interests": [4, 6],
        "mode": "dating",
    },
    {
        "id": 900000007,
        "name": "Артём Романов",
        "year": 4,
        "major": "Прикладная математика и кибернетика",
        "goal": "Ищу сильных аналитиков и бэкендеров для крупных соревнований 🔥",
        "rating": 250.0,
        "interests": [1, 2, 3],
        "mode": "career",
    },
    {
        "id": 900000008,
        "name": "Полина Кравцова",
        "year": 3,
        "major": "Реклама и связи с общественностью",
        "goal": "Сделаю мощный маркетинг и презентацию для любого стартапа 📈",
        "rating": 175.0,
        "interests": [4, 5, 6],
        "mode": "career",
    },
    {
        "id": 900000009,
        "name": "Игорь Мельников",
        "year": 2,
        "major": "Финансы и кредитные рынки",
        "goal": "Люблю анализировать стартапы, ищу интересных людей для нетворкинга 📊",
        "rating": 130.0,
        "interests": [2, 5],
        "mode": "dating",
    },
    {
        "id": 900000010,
        "name": "Алина Белова",
        "year": 1,
        "major": "Лингвистика и Перевод",
        "goal": "Изучаю 3 языка, ищу друзей для общения, прогулок и совместных поездок 🌍",
        "rating": 110.0,
        "interests": [4, 6],
        "mode": "dating",
    },
]


def upgrade() -> None:
    users_table = table(
        "users",
        column("id", sa.BigInteger),
        column("email", sa.String),
        column("email_verified", sa.Boolean),
        column("university_id", sa.Integer),
        column("consent_given", sa.Boolean),
        column("is_active", sa.Boolean),
        column("mode", sa.String),
        column("superlike_balance", sa.Integer),
        column("created_at", sa.DateTime(timezone=True)),
    )

    profiles_table = table(
        "profiles",
        column("id", sa.dialects.postgresql.UUID(as_uuid=True)),
        column("user_id", sa.BigInteger),
        column("name", sa.String),
        column("year", sa.Integer),
        column("major", sa.String),
        column("interest_ids", sa.ARRAY(sa.Integer)),
        column("goal", sa.Text),
        column("rating_score", sa.Float),
        column("is_visible", sa.Boolean),
        column("is_complete", sa.Boolean),
        column("created_at", sa.DateTime(timezone=True)),
    )

    now = datetime.now(timezone.utc)

    for u in TEST_USERS:
        # Вставляем юзера
        op.execute(
            users_table.insert().values(
                id=u["id"],
                email=f"test_{u['id']}@rudn.ru",
                email_verified=True,
                university_id=1,  # РУДН
                consent_given=True,
                is_active=True,
                mode=u["mode"],
                superlike_balance=3,
                created_at=now,
            )
        )

        # Вставляем профиль
        op.execute(
            profiles_table.insert().values(
                id=uuid.uuid4(),
                user_id=u["id"],
                name=u["name"],
                year=u["year"],
                major=u["major"],
                interest_ids=u["interests"],
                goal=u["goal"],
                rating_score=u["rating"],
                is_visible=True,
                is_complete=True,
                created_at=now,
            )
        )


def downgrade() -> None:
    ids = [u["id"] for u in TEST_USERS]
    op.execute(f"DELETE FROM profiles WHERE user_id IN ({','.join(map(str, ids))})")
    op.execute(f"DELETE FROM users WHERE id IN ({','.join(map(str, ids))})")
