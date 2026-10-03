"""
Тестирование схемы и логики свайпов проектов (Fix uq_swipe_pair_mode):
1. Проверка возможности свайпа нескольких разных проектов одного и того же автора одним пользователем.
2. Проверка обновления (re-swipe) существующего свайпа по проекту без ошибки уникальности.
3. Проверка независимости свайпов в режиме Dating/Career (to_project_id IS NULL).
4. Проверка основателя проекта (founder_swipe_candidate) на нескольких проектах для одного кандидата.
"""
import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone

# Настраиваем UTF-8 для вывода в консоль Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

os.environ.setdefault("BOT_TOKEN", "123456:TEST_TOKEN_SWIPE_CONSTRAINT")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import select, and_

from database.models import Base, User, Profile, Project, Swipe, SwipeAction, ModeEnum
from database.crud import create_swipe, founder_swipe_candidate


async def setup_test_data(session: AsyncSession):
    founder = User(id=5240488942, tg_username="founder_projs")
    candidate = User(id=8015547531, tg_username="candidate_student")
    session.add_all([founder, candidate])
    await session.commit()

    p1 = Project(
        id=uuid.uuid4(),
        user_id=founder.id,
        title="Startup Alpha",
        pitch="AI Assistant for Students",
        description="Detailed description for project 1",
        stage="mvp",
    )
    p2 = Project(
        id=uuid.uuid4(),
        user_id=founder.id,
        title="Startup Beta",
        pitch="Campus Food Sharing",
        description="Detailed description for project 2",
        stage="idea",
    )
    session.add_all([p1, p2])
    await session.commit()
    return candidate, founder, p1, p2


async def check_multiple_projects_same_author_swipe(session, candidate, founder, p1, p2):
    """
    Тест исправления ошибки 'duplicate key value violates unique constraint uq_swipe_pair_mode':
    Пользователь должен иметь возможность откликнуться/свайпнуть Project 1 и Project 2 одного автора.
    """
    # 1. Кандидат свайпает Проект 1 автора 5240488942
    res1 = await create_swipe(
        session,
        from_id=candidate.id,
        to_id=founder.id,
        action=SwipeAction.like,
        mode=ModeEnum.projects,
        to_project_id=p1.id,
        comment="Хочу в бэкенд",
    )
    assert res1 is False

    # 2. Кандидат свайпает Проект 2 ТОГО ЖЕ автора 5240488942
    # Раньше падало с IntegrityError: duplicate key value violates unique constraint "uq_swipe_pair_mode"
    # (Key (from_user_id, to_user_id, mode)=(8015547531, 5240488942, projects) already exists)
    res2 = await create_swipe(
        session,
        from_id=candidate.id,
        to_id=founder.id,
        action=SwipeAction.skip,
        mode=ModeEnum.projects,
        to_project_id=p2.id,
    )
    assert res2 is False

    # Проверяем, что в БД сохранились ОБА свайпа
    swipes_p1 = (await session.execute(
        select(Swipe).where(and_(Swipe.from_user_id == candidate.id, Swipe.to_project_id == p1.id))
    )).scalars().all()
    assert len(swipes_p1) == 1
    assert swipes_p1[0].action == SwipeAction.like
    assert swipes_p1[0].comment == "Хочу в бэкенд"

    swipes_p2 = (await session.execute(
        select(Swipe).where(and_(Swipe.from_user_id == candidate.id, Swipe.to_project_id == p2.id))
    )).scalars().all()
    assert len(swipes_p2) == 1
    assert swipes_p2[0].action == SwipeAction.skip

    print("  ✅ [1] Свайп нескольких разных проектов одного автора успешно сохранён без конфликта ключей!")


async def check_reswipe_project_updates_existing(session, candidate, founder, p1):
    """
    Повторный свайп одного и того же проекта (например, повторное нажатие или смена на суперлайк)
    должен обновлять существующую запись, а не создавать дубликат и не выбрасывать IntegrityError.
    """
    # Сначала скип
    await create_swipe(
        session,
        from_id=candidate.id,
        to_id=founder.id,
        action=SwipeAction.skip,
        mode=ModeEnum.projects,
        to_project_id=p1.id,
    )

    # Затем лайк
    await create_swipe(
        session,
        from_id=candidate.id,
        to_id=founder.id,
        action=SwipeAction.like,
        mode=ModeEnum.projects,
        to_project_id=p1.id,
        comment="Передумал, проект супер",
    )

    swipes = (await session.execute(
        select(Swipe).where(and_(Swipe.from_user_id == candidate.id, Swipe.to_project_id == p1.id))
    )).scalars().all()
    assert len(swipes) == 1
    assert swipes[0].action == SwipeAction.like
    assert swipes[0].comment == "Передумал, проект супер"

    print("  ✅ [2] Повторный свайп по проекту корректно обновил запись!")


async def check_dating_swipe_uniqueness_intact(session, candidate, founder):
    """
    Проверка, что для Dating/Career уникальность пар пользователей (from_user, to_user, mode)
    по-прежнему гарантируется и защищена частичным индексом uq_swipe_pair_mode_user.
    """
    # Свайп в dating
    await create_swipe(
        session,
        from_id=candidate.id,
        to_id=founder.id,
        action=SwipeAction.skip,
        mode=ModeEnum.dating,
    )

    # Повторный свайп в dating обновляет действие
    await create_swipe(
        session,
        from_id=candidate.id,
        to_id=founder.id,
        action=SwipeAction.like,
        mode=ModeEnum.dating,
    )

    dating_swipes = (await session.execute(
        select(Swipe).where(and_(
            Swipe.from_user_id == candidate.id,
            Swipe.to_user_id == founder.id,
            Swipe.mode == ModeEnum.dating,
        ))
    )).scalars().all()
    assert len(dating_swipes) == 1
    assert dating_swipes[0].action == SwipeAction.like

    print("  ✅ [3] Свайпы в режиме Dating сохраняют уникальность без дублирования!")


async def check_founder_swipe_candidate_multiple_projects(session, candidate, founder, p1, p2):
    """
    Фаундер может рассмотреть кандидата на Проект 1 и на Проект 2 независимо.
    """
    # Кандидат откликнулся на оба
    await create_swipe(session, candidate.id, founder.id, SwipeAction.like, ModeEnum.projects, to_project_id=p1.id)
    await create_swipe(session, candidate.id, founder.id, SwipeAction.like, ModeEnum.projects, to_project_id=p2.id)

    # Фаундер принимает кандидата в Проект 1 -> создает мэтч по P1
    is_match1 = await founder_swipe_candidate(
        session,
        founder_id=founder.id,
        candidate_id=candidate.id,
        project_id=p1.id,
        action=SwipeAction.like,
    )
    assert is_match1 is True

    # Фаундер отклоняет кандидата в Проект 2 -> не создает мэтч по P2
    is_match2 = await founder_swipe_candidate(
        session,
        founder_id=founder.id,
        candidate_id=candidate.id,
        project_id=p2.id,
        action=SwipeAction.skip,
    )
    assert is_match2 is False

    # Проверяем записи свайпов фаундера
    founder_swipes = (await session.execute(
        select(Swipe).where(Swipe.from_user_id == founder.id)
    )).scalars().all()
    assert len(founder_swipes) == 2

    print("  ✅ [4] Свайпы фаундера по разным проектам для одного кандидата независимы и корректны!")


async def run_all():
    print("=" * 70)
    print("🛡️ ТЕСТИРОВАНИЕ СХЕМЫ И ЧАСТИЧНЫХ ИНДЕКСОВ СВАЙПОВ (Fix uq_swipe_pair_mode)")
    print("=" * 70)

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with session_maker() as session:
        candidate, founder, p1, p2 = await setup_test_data(session)

        await check_multiple_projects_same_author_swipe(session, candidate, founder, p1, p2)
        await check_reswipe_project_updates_existing(session, candidate, founder, p1)
        await check_dating_swipe_uniqueness_intact(session, candidate, founder)
        await check_founder_swipe_candidate_multiple_projects(session, candidate, founder, p1, p2)

    await engine.dispose()
    print("=" * 70)
    print("🎉 ВСЕ ТЕСТЫ СВАЙПОВ ПРОЕКТОВ УСПЕШНО ПРОЙДЕНЫ (4 из 4)!")
    print("=" * 70)


def test_main():
    """Для запуска через pytest."""
    asyncio.run(run_all())


if __name__ == "__main__":
    asyncio.run(run_all())
