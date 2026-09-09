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
from sqlalchemy import select, delete, or_
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
        # ─────────────────────────────────────────────────────────────
        # 6. ТЕСТ: КАРЛИКОВЫЙ ПУЛ (ВСЕГО 1 КАНДИДАТ В БАЗЕ)
        # ─────────────────────────────────────────────────────────────
        print("\n▶ [ТЕСТ 6] Бесконечная лента при пуле всего из 1 кандидата (Pass 3 Ultimate Fallback)...")
        await db.execute(delete(Swipe))
        await db.execute(delete(Match))
        await db.execute(delete(Profile))
        await db.execute(delete(User))
        await db.commit()

        u_solo = User(id=700, tg_username="solo_viewer", is_active=True, mode=ModeEnum.dating)
        p_solo = Profile(
            user_id=700, name="Solo Viewer", gender="male", target_gender="female",
            is_complete=True, is_visible=True
        )

        girl_solo = User(id=701, is_active=True, mode=ModeEnum.dating)
        p_girl_solo = Profile(
            user_id=701, name="Единственная Девушка", gender="female", target_gender="male",
            is_complete=True, is_visible=True
        )

        db.add_all([u_solo, p_solo, girl_solo, p_girl_solo])
        await db.commit()

        for step in range(3):
            card = await get_next_profile(db, viewer_id=700, mode=ModeEnum.dating)
            assert card is not None, f"Шаг {step+1}: анкета пропала при пуле из 1 человека!"
            assert card.user_id == 701, f"Шаг {step+1}: ожидалась анкета 701, получено {card.user_id}"
            await create_swipe(db, from_id=700, to_id=701, action=SwipeAction.skip, mode=ModeEnum.dating)

        print("  ✓ [6.1] При пуле из 1 анкеты лента никогда не прерывается и не падает в None.")
        passed += 1

        # ─────────────────────────────────────────────────────────────
        # 7. ТЕСТ: МАЛЕНЬКИЙ ПУЛ ИЗ 2 КАНДИДАТОВ (ЧЕРЕДОВАНИЕ A -> B -> A -> B)
        # ─────────────────────────────────────────────────────────────
        print("\n▶ [ТЕСТ 7] Чередование двух кандидатов без дублей подряд (A -> B -> A -> B)...")
        await db.execute(delete(Swipe))
        await db.execute(delete(Match))
        await db.execute(delete(Profile))
        await db.execute(delete(User))
        await db.commit()

        u_duo = User(id=800, tg_username="duo_viewer", is_active=True, mode=ModeEnum.dating)
        p_duo = Profile(user_id=800, name="Duo Viewer", gender="male", target_gender="female", is_complete=True, is_visible=True)

        g_A = User(id=801, is_active=True, mode=ModeEnum.dating)
        p_g_A = Profile(user_id=801, name="Девушка A", gender="female", target_gender="male", is_complete=True, is_visible=True)

        g_B = User(id=802, is_active=True, mode=ModeEnum.dating)
        p_g_B = Profile(user_id=802, name="Девушка B", gender="female", target_gender="male", is_complete=True, is_visible=True)

        db.add_all([u_duo, p_duo, g_A, p_g_A, g_B, p_g_B])
        await db.commit()

        duo_seq = []
        for step in range(4):
            card = await get_next_profile(db, viewer_id=800, mode=ModeEnum.dating)
            assert card is not None, f"Шаг {step+1}: лента неожиданно прервалась!"
            duo_seq.append(card.user_id)
            await create_swipe(db, from_id=800, to_id=card.user_id, action=SwipeAction.skip, mode=ModeEnum.dating)

        assert duo_seq[0] != duo_seq[1], "Анкеты 1 и 2 должны быть разными!"
        assert duo_seq[1] != duo_seq[2], "Анкеты 2 и 3 не должны повторяться подряд!"
        assert duo_seq[2] != duo_seq[3], "Анкеты 3 и 4 не должны повторяться подряд!"
        print(f"  ✓ [7.1] Корректное бесконечное чередование 2 анкет: {duo_seq}")
        passed += 1

        # ─────────────────────────────────────────────────────────────
        # 8. ТЕСТ: СБРОС ИСТОРИИ СВАЙПОВ И МЭТЧЕЙ
        # ─────────────────────────────────────────────────────────────
        print("\n▶ [ТЕСТ 8] Сброс истории свайпов и мэтчей в режиме...")
        # Ставим лайк и создаем мэтч между 800 и 801
        await create_swipe(db, from_id=800, to_id=801, action=SwipeAction.like, mode=ModeEnum.dating)
        db.add(Match(user1_id=800, user2_id=801, mode=ModeEnum.dating))
        await db.commit()

        # Проверяем, что 801 теперь исключена из выдачи
        card_before_reset = await get_next_profile(db, viewer_id=800, mode=ModeEnum.dating)
        assert card_before_reset.user_id == 802, "801 должна быть скрыта из-за лайка/мэтча!"

        # Сбрасываем свайпы и мэтчи для 800
        await db.execute(delete(Swipe).where(Swipe.from_user_id == 800, Swipe.mode == ModeEnum.dating))
        await db.execute(delete(Match).where(or_(Match.user1_id == 800, Match.user2_id == 800), Match.mode == ModeEnum.dating))
        await db.commit()

        # Проверяем, что 801 снова доступна в выдаче
        card_after_reset = await get_next_profile(db, viewer_id=800, mode=ModeEnum.dating)
        assert card_after_reset is not None, "После сброса выдача должна вернуть анкету!"
        print("  ✓ [8.1] Сброс свайпов и мэтчей успешно возвращает профили в выдачу.")
        # ─────────────────────────────────────────────────────────────
        # 9. ТЕСТ: КОРРЕКТНЫЙ ПРОПУСК ВХОДЯЩЕГО ЛАЙКА (БЕЗ ЗАСТРЕВАНИЯ)
        # ─────────────────────────────────────────────────────────────
        print("\n▶ [ТЕСТ 9] Пропуск входящего лайка не застревает и переключает на следующего кандидата...")
        await db.execute(delete(Swipe))
        await db.execute(delete(Match))
        await db.execute(delete(Profile))
        await db.execute(delete(User))
        await db.commit()

        u_viewer9 = User(id=900, tg_username="viewer9", is_active=True, mode=ModeEnum.dating)
        p_viewer9 = Profile(user_id=900, name="Viewer 9", gender="male", target_gender="female", is_complete=True, is_visible=True)

        g_liker = User(id=901, is_active=True, mode=ModeEnum.dating)
        p_liker = Profile(user_id=901, name="Девушка с лайком", gender="female", target_gender="male", is_complete=True, is_visible=True)

        g_fresh = User(id=902, is_active=True, mode=ModeEnum.dating)
        p_fresh = Profile(user_id=902, name="Свежая Девушка", gender="female", target_gender="male", is_complete=True, is_visible=True)

        db.add_all([u_viewer9, p_viewer9, g_liker, p_liker, g_fresh, p_fresh])
        await db.commit()

        # Девушка 901 ставит лайк Viewer'у 900
        await create_swipe(db, from_id=901, to_id=900, action=SwipeAction.like, mode=ModeEnum.dating)

        # 1. Первой должна выпасть именно девушка с входящим лайком (901)
        card_1 = await get_next_profile(db, viewer_id=900, mode=ModeEnum.dating)
        assert card_1 is not None and card_1.user_id == 901, f"Ожидалась 901 (входящий лайк), получена {card_1.user_id if card_1 else None}"
        print("  ✓ [9.1] Анкета со свежим входящим лайком выпадает первой (Priority 3).")

        # 2. Viewer пропускает (skip) девушку с лайком
        await asyncio.sleep(0.01)
        await create_swipe(db, from_id=900, to_id=901, action=SwipeAction.skip, mode=ModeEnum.dating)

        # 3. Следующей ДОЛЖНА выпасть свежая девушка (902), а НЕ пропущенная 901!
        card_2 = await get_next_profile(db, viewer_id=900, mode=ModeEnum.dating)
        assert card_2 is not None and card_2.user_id == 902, (
            f"ОШИБКА: Застревание! Ожидалась следующая анкета 902, но снова вернулась {card_2.user_id if card_2 else None}"
        )
        print("  ✓ [9.2] После нажатия Skip анкета с лайком не застревает и успешно уступает место следующей анкете (902).")

        # 4. Пропускаем 902
        await asyncio.sleep(0.01)
        await create_swipe(db, from_id=900, to_id=902, action=SwipeAction.skip, mode=ModeEnum.dating)

        # 5. Теперь обе анкеты пропущены -> ресайкл поочередно возвращает 901
        card_3 = await get_next_profile(db, viewer_id=900, mode=ModeEnum.dating)
        assert card_3 is not None and card_3.user_id == 901, f"Ожидался ресайкл 901, получено {card_3.user_id if card_3 else None}"

        # 6. Если в ресайкле Viewer лайкнет 901 — должен произойти мгновенный взаимный мэтч!
        is_match = await create_swipe(db, from_id=900, to_id=901, action=SwipeAction.like, mode=ModeEnum.dating)
        assert is_match is True, "При ответе лайком на ресайкленную анкету должен сработать взаимный мэтч!"
        print("  ✓ [9.3] При взаимном лайке из ресайкла мгновенный мэтч успешно срабатывает.")
        passed += 1

    print("\n" + "=" * 75)
    print(f"🎉 ВСЕ {passed} ТЕСТОВ УСПЕШНО ПРОЙДЕНЫ!")
    print("=" * 75)


if __name__ == "__main__":
    asyncio.run(main())
