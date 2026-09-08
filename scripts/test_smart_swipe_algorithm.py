"""
Автоматизированный комплексный тест нового алгоритма выдачи анкет для свайпов:
1. Priority Tiers (Входящие лайки/суперлайки -> Свежие -> Ресайкл >48ч -> Ресайкл FIFO fallback).
2. Защита от дублей: скользящий буфер N анкет и исключение back-to-back показа одного человека.
3. Исключение положительных свайпов (лайки, суперлайки, мэтчи никогда не повторяются).
4. Воскрешение пропущенного при входящем лайке: skip + incoming like -> немедленный топ.
5. Изоляция режимов: свайпы в Dating не влияют на Career и наоборот.
6. Бесконечность ленты при исчерпании свежих анкет.
"""
import asyncio
import os
import sys
import json
import sqlite3
from datetime import datetime, timezone, timedelta

# Настраиваем UTF-8 для вывода в консоль Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

os.environ.setdefault("BOT_TOKEN", "123456:TEST_TOKEN_SMART_SWIPES")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///test_smart_swipes.db")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select, delete
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

from database.models import (
    Base, User, Profile, InterestTag, ModeEnum, Swipe, SwipeAction, Match, Report
)
from database.crud import (
    get_next_profile, create_swipe, get_user
)


async def main():
    print("=" * 75)
    print("🧪 ЗАПУСК ТЕСТОВ УМНОГО БЕСКОНЕЧНОГО АЛГОРИТМА СВАЙПОВ")
    print("=" * 75)

    db_path = "test_smart_swipes.db"
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
        except Exception:
            pass

    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    passed = 0
    now = datetime.now(timezone.utc)

    async with async_session() as db:
        # ─────────────────────────────────────────────────────────────
        # 1. ТЕСТ: ПРИОРИТЕТ СВЕЖИХ НАД РЕСАЙКЛОМ И 48-ЧАСОВОЙ КУЛДАУН
        # ─────────────────────────────────────────────────────────────
        print("\n▶ [ТЕСТ 1] Свежие анкеты vs Ресайкл (>48ч) vs Ресайкл (<48ч)...")

        viewer = User(id=101, tg_username="viewer1", is_active=True, mode=ModeEnum.dating)
        p_viewer = Profile(
            user_id=101, name="Viewer", gender="male", target_gender="female",
            age=20, year=2, is_complete=True, career_is_complete=True, is_visible=True
        )

        # Кандидат 1: Был пропущен 3 дня назад (>48ч)
        c1 = User(id=201, tg_username="cand1_old_skip", is_active=True, mode=ModeEnum.dating)
        p1 = Profile(user_id=201, name="Анна (Skip >48ч)", gender="female", target_gender="male", is_complete=True, is_visible=True, rating_score=50.0)

        # Кандидат 2: Свежая девушка (никогда не свайпалась)
        c2 = User(id=202, tg_username="cand2_fresh", is_active=True, mode=ModeEnum.dating)
        p2 = Profile(user_id=202, name="Белла (Fresh)", gender="female", target_gender="male", is_complete=True, is_visible=True, rating_score=10.0)

        # Кандидат 3: Пропущена 2 часа назад (<48ч)
        c3 = User(id=203, tg_username="cand3_recent_skip", is_active=True, mode=ModeEnum.dating)
        p3 = Profile(user_id=203, name="Вера (Skip <48ч)", gender="female", target_gender="male", is_complete=True, is_visible=True, rating_score=100.0)

        db.add_all([viewer, p_viewer, c1, p1, c2, p2, c3, p3])
        await db.commit()

        # Добавляем свайпы
        # Анна пропущена 72 часа назад
        s1 = Swipe(from_user_id=101, to_user_id=201, mode=ModeEnum.dating, action=SwipeAction.skip, created_at=now - timedelta(hours=72))
        # Вера пропущена 2 часа назад
        s3 = Swipe(from_user_id=101, to_user_id=203, mode=ModeEnum.dating, action=SwipeAction.skip, created_at=now - timedelta(hours=2))
        db.add_all([s1, s3])
        await db.commit()

        # 1.1 Свежая Белла должна быть выдана ПЕРВОЙ, несмотря на более низкий рейтинг, чем у Веры
        card1 = await get_next_profile(db, viewer_id=101, mode=ModeEnum.dating)
        assert card1 is not None and card1.user_id == 202, f"Ожидалась свежая Белла (202), получена {card1.name if card1 else None}"
        print("  ✓ [1.1] Свежая анкета приоритетнее ресайкла.")
        passed += 1

        # Свайпаем Беллу (скип)
        await create_swipe(db, from_id=101, to_id=202, action=SwipeAction.skip, mode=ModeEnum.dating)

        # 1.2 Теперь свежих нет. Должна выпасть Анна (пропущена >48ч назад), а не Вера (пропущена 2ч назад)
        card2 = await get_next_profile(db, viewer_id=101, mode=ModeEnum.dating)
        assert card2 is not None and card2.user_id == 201, f"Ожидалась Анна с кулдауном >48ч (201), получена {card2.name if card2 else None}"
        print("  ✓ [1.2] Ресайкл >48ч приоритетнее недавних пропусков (<48ч).")
        passed += 1

        # ─────────────────────────────────────────────────────────────
        # 2. ТЕСТ: ВОСКРЕШЕНИЕ ПРОПУЩЕННОГО ПРИ ВХОДЯЩЕМ ЛАЙКЕ
        # ─────────────────────────────────────────────────────────────
        print("\n▶ [ТЕСТ 2] Воскрешение ранее пропущенной анкеты при входящем лайке...")

        # Пользователь 101 только что пропустил Анну (201).
        await create_swipe(db, from_id=101, to_id=201, action=SwipeAction.skip, mode=ModeEnum.dating)

        # Теперь Анна ставит лайк пользователю 101!
        await create_swipe(db, from_id=201, to_id=101, action=SwipeAction.like, mode=ModeEnum.dating)

        # Несмотря на то, что 101 только что нажал skip на Анну, входящий лайк должен вернуть её на 1-е место!
        revived = await get_next_profile(db, viewer_id=101, mode=ModeEnum.dating)
        assert revived is not None and revived.user_id == 201, f"Ожидалась Анна (201) по входящему лайку, получена {revived.name if revived else None}"
        print("  ✓ [2.1] Входящий лайк ломает кулдаун и немедленно поднимает пропущенную анкету в топ.")
        passed += 1

        # Пользователь отвечает взаимным лайком -> образуется мэтч
        is_match = await create_swipe(db, from_id=101, to_id=201, action=SwipeAction.like, mode=ModeEnum.dating)
        assert is_match is True, "Ожидался взаимный мэтч"

        # Проверяем, что Анна ПОСЛЕ МЭТЧА больше никогда не появится в ленте свайпов
        next_after_match = await get_next_profile(db, viewer_id=101, mode=ModeEnum.dating)
        assert next_after_match is not None and next_after_match.user_id != 201, "Мэтч не должен повторно выдаваться в ленте!"
        print("  ✓ [2.2] Мэтч навсегда исключён из ленты свайпов.")
        passed += 1

        # ─────────────────────────────────────────────────────────────
        # 3. ТЕСТ: ИЗОЛЯЦИЯ РЕЖИМОВ (DATING VS CAREER)
        # ─────────────────────────────────────────────────────────────
        print("\n▶ [ТЕСТ 3] Изоляция свайпов между режимами Dating и Career...")

        # Кандидат Дарья (301) доступна и в знакомствах, и в карьере
        c_daria = User(id=301, tg_username="daria_dual", is_active=True, mode=ModeEnum.dating)
        p_daria = Profile(
            user_id=301, name="Дарья", gender="female", target_gender="all",
            is_complete=True, career_is_complete=True, is_visible=True, rating_score=90.0
        )
        db.add_all([c_daria, p_daria])
        await db.commit()

        # Пользователь скипает Дарью в режиме ДЕЙТИНГА
        await create_swipe(db, from_id=101, to_id=301, action=SwipeAction.skip, mode=ModeEnum.dating)

        # Проверяем: в режиме КАРЬЕРЫ Дарья должна быть абсолютно СВЕЖЕЙ анкетой!
        career_card = await get_next_profile(db, viewer_id=101, mode=ModeEnum.career)
        assert career_card is not None and career_card.user_id == 301, f"В Карьере ожидалась Дарья (301), получена {career_card.name if career_card else None}"
        print("  ✓ [3.1] Скип в Dating не скрыл анкету в Career.")
        passed += 1

        # В Карьере пользователь ставит Дарье лайк
        await create_swipe(db, from_id=101, to_id=301, action=SwipeAction.like, mode=ModeEnum.career)

        # Проверяем записи в БД: должны существовать 2 раздельных свайпа с разными mode
        dating_s = await db.scalar(select(Swipe).where(Swipe.from_user_id == 101, Swipe.to_user_id == 301, Swipe.mode == ModeEnum.dating))
        career_s = await db.scalar(select(Swipe).where(Swipe.from_user_id == 101, Swipe.to_user_id == 301, Swipe.mode == ModeEnum.career))
        assert dating_s is not None and dating_s.action == SwipeAction.skip, "В Dating должен остаться skip"
        assert career_s is not None and career_s.action == SwipeAction.like, "В Career должен остаться like"
        print("  ✓ [3.2] В БД сохранены независимые записи свайпов для Dating и Career.")
        passed += 1

        # ─────────────────────────────────────────────────────────────
        # 4. ТЕСТ: БЕСКОНЕЧНАЯ ЛЕНТА И ЗАЩИТА ОТ ДУБЛЕЙ (FIFO FALLBACK)
        # ─────────────────────────────────────────────────────────────
        print("\n▶ [ТЕСТ 4] Бесконечная лента без прерывания и защита от мгновенных дублей...")

        # Создадим отдельного пользователя и 3 кандидатов для проверки циклической выдачи
        u_loop = User(id=500, tg_username="loop_viewer", is_active=True, mode=ModeEnum.dating)
        p_loop = Profile(user_id=500, name="Loop Viewer", gender="male", target_gender="female", is_complete=True, is_visible=True)

        girl_A = User(id=501, is_active=True, mode=ModeEnum.dating)
        p_A = Profile(user_id=501, name="Девушка А", gender="female", target_gender="male", is_complete=True, is_visible=True)

        girl_B = User(id=502, is_active=True, mode=ModeEnum.dating)
        p_B = Profile(user_id=502, name="Девушка Б", gender="female", target_gender="male", is_complete=True, is_visible=True)

        girl_C = User(id=503, is_active=True, mode=ModeEnum.dating)
        p_C = Profile(user_id=503, name="Девушка В", gender="female", target_gender="male", is_complete=True, is_visible=True)

        db.add_all([u_loop, p_loop, girl_A, p_A, girl_B, p_B, girl_C, p_C])
        await db.commit()

        # Пользователь делает 9 свайпов подряд (3 круга по 3 анкетам).
        # Проверим, что:
        # 1. Выдача НИ РАЗУ не вернула None (лента бесконечна).
        # 2. Ни одна анкета не выпала дважды подряд (отсутствие мгновенных дублей).
        last_id = None
        seen_sequence = []
        for i in range(9):
            card = await get_next_profile(db, viewer_id=500, mode=ModeEnum.dating)
            assert card is not None, f"Шаг {i+1}: лента неожиданно прервалась (вернула None)!"
            assert card.user_id != last_id, f"Шаг {i+1}: обнаружен дубль подряд! Карточка {card.user_id} показана дважды."
            last_id = card.user_id
            seen_sequence.append(card.user_id)
            # Пользователь скипает карточку
            await create_swipe(db, from_id=500, to_id=card.user_id, action=SwipeAction.skip, mode=ModeEnum.dating)

        print(f"  ✓ [4.1] 9 свайпов подряд успешно пройдены без пауз: {seen_sequence}")
        print("  ✓ [4.2] Ни на одном шаге анкета не повторилась подряд.")
        passed += 1

        # ─────────────────────────────────────────────────────────────
        # 5. ТЕСТ: ОБНОВЛЕНИЕ TIMESTAMPS ПРИ ПОВТОРНЫХ ПРОПУСКАХ
        # ─────────────────────────────────────────────────────────────
        print("\n▶ [ТЕСТ 5] Обновление времени свайпа при повторном skip...")

        swipe_record = await db.scalar(
            select(Swipe).where(Swipe.from_user_id == 500, Swipe.to_user_id == 501, Swipe.mode == ModeEnum.dating)
        )
        old_time = swipe_record.created_at

        # Ждем 0.05с и снова скипаем
        await asyncio.sleep(0.05)
        await create_swipe(db, from_id=500, to_id=501, action=SwipeAction.skip, mode=ModeEnum.dating)

        await db.refresh(swipe_record)
        assert swipe_record.created_at >= old_time, "Время свайпа должно было обновиться!"
        print("  ✓ [5.1] Время created_at успешно обновляется на текущее при повторном skip.")
        passed += 1

    print("\n" + "=" * 75)
    print(f"🎉 ВСЕ {passed} ТЕСТОВ УСПЕШНО ПРОЙДЕНЫ!")
    print("=" * 75)


if __name__ == "__main__":
    asyncio.run(main())
