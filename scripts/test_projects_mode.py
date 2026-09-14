"""
Комплексный тест функционала третьего режима «💡 Проекты»:
- Модели и миграции (ModeEnum.projects, Project, project_* поля профиля, to_project_id, project_id)
- CRUD операции: create_project, get_projects_feed, get_project_candidates, founder_swipe_candidate
- Двусторонний свайп: Кандидат лайкает проект -> Фаундер одобряет -> Создается взаимный Match
- Bot хелперы и клавиатуры
"""
import os
import sys
import uuid
import json
import asyncio

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

os.environ["BOT_TOKEN"] = "123456:TEST_TOKEN_FOR_PROJECTS_MODE"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///test_projects_mode.db"

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import sqlite3
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.types import ARRAY
from sqlalchemy.dialects.postgresql import UUID

sqlite3.register_adapter(list, json.dumps)
sqlite3.register_converter("JSON", json.loads)

@compiles(ARRAY, "sqlite")
def compile_array_sqlite(type_, compiler, **kw):
    return "JSON"

@compiles(UUID, "sqlite")
def compile_uuid_sqlite(type_, compiler, **kw):
    return "VARCHAR(36)"

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import select
from database.models import Base, User, Profile, Project, Swipe, Match, ModeEnum, SwipeAction
from database.migrations import ensure_database_schema
from database.crud import (
    create_project, get_project, get_user_projects, get_projects_feed,
    get_project_candidates, founder_swipe_candidate, create_swipe, update_profile
)
from bot.keyboards.swipe import project_swipe_card_keyboard, founder_candidate_keyboard
from bot.handlers.browse import _build_project_caption


TEST_DB_PATH = "test_projects_mode.db"
TEST_DB_URL = "sqlite+aiosqlite:///" + TEST_DB_PATH


async def run_tests():
    print("=" * 70)
    print("🚀 ТЕСТИРОВАНИЕ РЕЖИМА «💡 ПРОЕКТЫ» (StudMatch)")
    print("=" * 70)

    if os.path.exists(TEST_DB_PATH):
        try:
            os.remove(TEST_DB_PATH)
        except Exception:
            pass

    engine = create_async_engine(TEST_DB_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await ensure_database_schema(engine)
    print("✅ Схема БД и миграции успешно применены.")

    async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with async_session() as session:
        # 1. Создаем двух тестовых пользователей: Фаундера и Кандидата
        founder = User(id=80001, tg_username="founder_alex", mode=ModeEnum.projects)
        candidate = User(id=80002, tg_username="dev_maria", mode=ModeEnum.projects)
        session.add_all([founder, candidate])
        await session.commit()

        f_prof = Profile(
            user_id=founder.id, name="Алексей", year=3, is_complete=True,
            project_role="Tech Lead", project_skills="Python, FastAPI, React",
            project_bio="Делаю AI стартапы", project_is_complete=True
        )
        c_prof = Profile(
            user_id=candidate.id, name="Мария", year=2, is_complete=True,
            project_role="UI/UX Designer", project_skills="Figma, UI Design",
            project_bio="Хочу сделать крутой pet-проект", project_is_complete=True
        )
        session.add_all([f_prof, c_prof])
        await session.commit()
        print("✅ Тестовые пользователи (Фаундер и Кандидат) созданы с проектными профилями.")

        # 2. Фаундер создает проект
        proj = await create_project(
            session,
            user_id=founder.id,
            title="UniRent",
            pitch="Сервис совместной аренды жилья студентами без комиссий",
            description="Платформа проверяет студенческие билеты и помогает найти соседей по комнате или квартире рядом с кампусом.",
            stage="mvp",
            required_roles=["UI/UX Designer", "Frontend Developer"],
            conditions="equity",
            demo_url="https://unirent.example.com",
        )
        assert proj is not None, "Проект не создан"
        assert proj.title == "UniRent"
        assert proj.stage == "mvp"
        assert "UI/UX Designer" in proj.required_roles
        print(f"✅ Проект «{proj.title}» успешно создан (ID: {proj.id}).")

        # 3. Проверяем получение проектов фаундера
        my_projs = await get_user_projects(session, founder.id)
        assert len(my_projs) == 1
        assert my_projs[0].id == proj.id
        print("✅ Список проектов создателя проверен.")

        # 4. Кандидат смотрит ленту проектов (get_projects_feed)
        feed = await get_projects_feed(session, viewer_user_id=candidate.id, limit=10)
        assert len(feed) == 1
        assert feed[0].id == proj.id

        # Фаундер в своей ленте свой проект НЕ видит
        founder_feed = await get_projects_feed(session, viewer_user_id=founder.id, limit=10)
        assert len(founder_feed) == 0
        print("✅ Лента проектов кандидата и фильтрация своих проектов проверена.")

        # 5. Кандидат ставит Like проекту (двусторонний свайп со стороны соискателя)
        is_immediate_match = await create_swipe(
            session,
            from_id=candidate.id,
            to_id=founder.id,
            action=SwipeAction.like,
            mode=ModeEnum.projects,
            to_project_id=proj.id,
        )
        assert is_immediate_match is False, "Не должно быть мгновенного мэтча до решения фаундера"

        # После свайпа проект больше не показывается в ленте кандидата
        feed_after = await get_projects_feed(session, viewer_user_id=candidate.id, limit=10)
        assert len(feed_after) == 0
        print("✅ Свайп кандидата на проект зарегистрирован, проект исключён из повторной выдачи.")

        # 6. Фаундер проверяет список откликов (кандидатов) на проект
        candidates = await get_project_candidates(session, proj.id)
        assert len(candidates) == 1
        cand_user, swipe_record = candidates[0]
        assert cand_user.id == candidate.id
        assert swipe_record.to_project_id == proj.id
        assert swipe_record.action == SwipeAction.like
        print(f"✅ Фаундер получил отклик от кандидата {cand_user.profile.name}.")

        # 7. Фаундер одобряет кандидата (founder_swipe_candidate Like) -> должен создаться Match!
        is_match = await founder_swipe_candidate(
            session,
            founder_id=founder.id,
            candidate_id=candidate.id,
            project_id=proj.id,
            action=SwipeAction.like,
        )
        assert is_match is True, "Мэтч должен быть создан после одобрения фаундера"

        # Проверяем запись в таблице Match
        matches_stmt = select(Match).where(
            Match.mode == ModeEnum.projects,
            Match.project_id == proj.id,
        )
        m_res = await session.execute(matches_stmt)
        created_match = m_res.scalar_one_or_none()
        assert created_match is not None
        assert created_match.user1_id == founder.id
        assert created_match.user2_id == candidate.id
        assert created_match.project_id == proj.id
        print(f"✅ Взаимный Match успешно создан: ID={created_match.id}, mode={created_match.mode.value}!")

    # 8. Проверка Bot клавиатур и описания
    test_uuid = uuid.uuid4()
    kb = project_swipe_card_keyboard(test_uuid)
    buttons = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert f"pswipe:like:{test_uuid.hex}" in buttons
    assert f"pswipe:skip:{test_uuid.hex}" in buttons
    assert f"pswipe:superlike:{test_uuid.hex}" in buttons
    assert f"pswipe:details:{test_uuid.hex}" in buttons

    kb_founder = founder_candidate_keyboard(test_uuid, 123456)
    f_buttons = [b.callback_data for row in kb_founder.inline_keyboard for b in row]
    assert f"fcand:accept:{test_uuid.hex}:123456" in f_buttons
    assert f"fcand:skip:{test_uuid.hex}:123456" in f_buttons

    for b_data in buttons + f_buttons:
        assert len(b_data.encode("utf-8")) <= 64, f"Callback data exceeds 64 bytes: {b_data}"

    caption = _build_project_caption(proj)
    assert "UniRent" in caption
    assert "Сервис совместной аренды" in caption
    assert "UI/UX Designer" in caption
    print("✅ Бот-клавиатуры, лимиты callback_data (<=64 байт) и верстка карточек проверены.")

    # 9. Проверка WebApp API через TestClient
    from fastapi.testclient import TestClient
    from web.main import app
    from web.routers.webapp import create_student_token

    client = TestClient(app)
    founder_token = create_student_token(founder.id)
    candidate_token = create_student_token(candidate.id)

    # Лента проектов для кандидата
    res = client.get(
        "/api/webapp/projects/feed",
        headers={"Authorization": f"Bearer {candidate_token}"},
    )
    assert res.status_code == 200, f"feed failed: {res.text}"
    feed_data = res.json()
    assert "projects" in feed_data
    print(f"✅ WebApp API: GET /api/webapp/projects/feed вернул {len(feed_data['projects'])} проектов.")

    # Создание проекта фаундером через WebApp API
    res_create = client.post(
        "/api/webapp/projects",
        headers={"Authorization": f"Bearer {founder_token}"},
        json={
            "title": "StudyCoffee",
            "pitch": "Сеть студенческих кофепоинтов с коворкингом",
            "description": "Поиск инвестиций и открытие первых точек в корпусах университета.",
            "stage": "idea",
            "required_roles": ["Бариста", "Управляющий"],
            "conditions": "equity",
        },
    )
    assert res_create.status_code == 200, f"create failed: {res_create.text}"
    created_proj_data = res_create.json()
    assert "project_id" in created_proj_data
    new_proj_id = created_proj_data["project_id"]
    print(f"✅ WebApp API: POST /api/webapp/projects успешно создал проект (ID: {new_proj_id}).")

    # Получение списка "Мои проекты"
    res_my = client.get(
        "/api/webapp/projects/my",
        headers={"Authorization": f"Bearer {founder_token}"},
    )
    assert res_my.status_code == 200
    my_data = res_my.json()
    assert len(my_data.get("projects", [])) >= 2
    print("✅ WebApp API: GET /api/webapp/projects/my вернул проекты фаундера.")

    # Обновление проектного профиля соискателя
    res_prof = client.post(
        "/api/webapp/profile/project",
        headers={"Authorization": f"Bearer {candidate_token}"},
        json={
            "project_role": "Senior UI/UX Lead",
            "project_skills": "Figma, Design Systems, Mobile Apps",
            "project_bio": "3 года опыта, победы в хакатонах",
        },
    )
    assert res_prof.status_code == 200
    prof_data = res_prof.json()
    assert prof_data["project_role"] == "Senior UI/UX Lead"
    print("✅ WebApp API: POST /api/webapp/profile/project успешно обновил проектную анкету.")


    await engine.dispose()
    if os.path.exists(TEST_DB_PATH):
        try:
            os.remove(TEST_DB_PATH)
        except Exception:
            pass

    print("=" * 70)
    print("🎉 ВСЕ ТЕСТЫ РЕЖИМА «💡 ПРОЕКТЫ» УСПЕШНО ПРОЙДЕНЫ!")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(run_tests())
