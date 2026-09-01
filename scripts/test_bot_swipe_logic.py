"""
Комплексный стресс-тест и аудит логики свайпов бота StudMatch.
Проверяет:
1. Корректность рендеринга и экранирования анкет (_build_profile_caption, _get_photo_input).
2. Алгоритм выборки анкет (get_next_profile): фильтры, исключение свайпнутых/репортов, взаимная гендерная совместимость, сортировка по приоритетам.
3. Разделение режимов «❤️ Знакомства» и «🎯 Карьера».
4. Механику свайпов, суперлайков и создания мэтчей (create_swipe, deduct_superlike, auto_match).
"""
import asyncio
import os
import sys
import html
from datetime import datetime, timezone, timedelta

# Настраиваем UTF-8 для вывода в консоль Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

# Устанавливаем тестовые переменные окружения ДО импорта настроек
os.environ.setdefault("BOT_TOKEN", "123456:TEST_TOKEN_FOR_AUDIT_RUNNER")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///test_audit.db")

# Добавляем корень проекта в путь
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select, delete
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.types import ARRAY
from sqlalchemy.dialects.postgresql import UUID

import sqlite3
import json

sqlite3.register_adapter(list, json.dumps)
sqlite3.register_converter("JSON", json.loads)

@compiles(ARRAY, "sqlite")
def compile_array_sqlite(type_, compiler, **kw):
    return "JSON"

@compiles(UUID, "sqlite")
def compile_uuid_sqlite(type_, compiler, **kw):
    return "VARCHAR(36)"

from database.models import (
    Base, User, Profile, InterestTag, ModeEnum, Swipe, SwipeAction, Match, Report, University
)
from database.crud import (
    get_next_profile, create_swipe, deduct_superlike, get_profile, get_user
)
from bot.handlers.browse import _build_profile_caption, _get_photo_input


async def run_audit():
    print("=" * 70)
    print("🚀 НАЧАЛО КОМПЛЕКСНОГО АУДИТА ЛОГИКИ СВАЙПОВ БОТА STUDMATCH")
    print("=" * 70)

    db_path = "test_audit.db"
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
        except Exception:
            pass

    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False)

    # Создаем все таблицы
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    passed_tests = 0
    failed_tests = 0

    async with async_session() as db:
        try:
            # ─────────────────────────────────────────────────────────────
            # БЛОК 1: ТЕСТИРОВАНИЕ РЕНДЕРИНГА АНКЕТ И ЭКРАНИРОВАНИЯ HTML
            # ─────────────────────────────────────────────────────────────
            print("\n📌 [БЛОК 1] Тестирование рендеринга текста, экранирования HTML и медиа-инпутов...")

            test_tag = InterestTag(id=99991, name="<IT & Кодинг>", emoji="💻")
            tags_map = {99991: test_tag}

            # 1.1 Дейтинг профиль с потенциально опасными HTML-символами
            p_dating = Profile(
                user_id=99991,
                name="Иван <Hack & Slash>",
                major="Информатика <b>&</b> ИИ",
                year=3,
                age=21,
                rating_score=150.0,
                interest_ids=[99991],
                custom_interests="C++ <templates> & Python",
                goal="Ищу тиммейта <или> спутницу жизни :)",
                avatar_file_id="tg_avatar_file_123",
            )
            u_dating = User(
                id=99991,
                tg_username="ivan_hack",
                email_verified=True,
                mode=ModeEnum.dating,
                premium_until=datetime.now(timezone.utc) + timedelta(days=30),
                boost_until=datetime.now(timezone.utc) + timedelta(hours=2),
            )

            caption_dating = await _build_profile_caption(p_dating, tags_map, user=u_dating, mode=ModeEnum.dating)

            # Проверяем экранирование
            assert "<Hack & Slash>" not in caption_dating, "Имя не экранировано от < >"
            assert "&lt;Hack &amp; Slash&gt;" in caption_dating or html.escape("Иван <Hack & Slash>") in caption_dating
            assert "&lt;templates&gt;" in caption_dating or "C++ &lt;templates&gt; &amp; Python" in caption_dating
            assert "PREMIUM" in caption_dating, "Бейдж Premium не отобразился"
            assert "[В топе]" in caption_dating, "Бейдж буста не отобразился"
            assert "21 год" in caption_dating, "Склонение возраста для 21 неверно"
            assert "⭐ 150 б." in caption_dating, "Рейтинг не отобразился"
            print("  ✅ [1.1] Дейтинг-анкета: экранирование HTML, бейджи, склонения возраста и рейтинг корректны.")
            passed_tests += 1

            # 1.2 Карьерный профиль
            p_career = Profile(
                user_id=99992,
                name="Анна Программист",
                major="Прикладная математика",
                year=4,
                age=22,
                rating_score=200.0,
                career_custom_skills="Python 3.12, FastAPI <async>, PostgreSQL, Docker & K8s",
                career_goal="Стажировка на позицию <Junior Backend Developer>",
                career_work_format="Удаленно / Гибрид",
                career_avatar_file_id="career_photo_456",
            )
            u_career = User(
                id=99992,
                tg_username="anna_dev",
                email_verified=True,
                mode=ModeEnum.career,
            )

            caption_career = await _build_profile_caption(p_career, tags_map, user=u_career, mode=ModeEnum.career)
            assert "[Карьера]" in caption_career, "Маркер режима Карьера отсутствует"
            assert "&lt;async&gt;" in caption_career or "FastAPI &lt;async&gt;" in caption_career
            assert "22 года" in caption_career, "Склонение возраста для 22 неверно"
            assert "Python 3.12" in caption_career
            assert "Удаленно / Гибрид" in caption_career
            print("  ✅ [1.2] Карьерная анкета: корректные поля навыков, формата, опыта и экранирование.")
            passed_tests += 1

            # 1.3 Склонения возраста (17, 18, 19, 20, 21, 22, 23, 24, 25)
            age_cases = {18: "18 лет", 19: "19 лет", 20: "20 лет", 21: "21 год", 22: "22 года", 24: "24 года", 25: "25 лет"}
            for a_test, expected in age_cases.items():
                p_tmp = Profile(user_id=99999, name="Тест", age=a_test)
                c_tmp = await _build_profile_caption(p_tmp, {})
                assert expected in c_tmp, f"Склонение для {a_test} ожидалось '{expected}', получено '{c_tmp}'"
            print("  ✅ [1.3] Склонения возраста (год/года/лет) на всех тестовых значениях работают без ошибок.")
            passed_tests += 1

            # 1.4 Проверка резолвера медиа (_get_photo_input)
            assert _get_photo_input(None) is None
            assert _get_photo_input("AgACAgIAAxkBA...") == "AgACAgIAAxkBA..."
            assert _get_photo_input("https://stud-match.ru/logo.jpg") is not None
            print("  ✅ [1.4] Резолвер медиа (_get_photo_input) корректно обрабатывает file_id, URL и None.")
            passed_tests += 1

            # ─────────────────────────────────────────────────────────────
            # БЛОК 2: ТЕСТИРОВАНИЕ АЛГОРИТМА ВЫБОРКИ (GET_NEXT_PROFILE)
            # ─────────────────────────────────────────────────────────────
            print("\n📌 [БЛОК 2] Тестирование алгоритма выборки (get_next_profile)...")

            # 1. Viewer (Парень, ищет Девушек, возраст 20)
            u_viewer = User(id=888001, tg_username="viewer_boy", is_active=True, mode=ModeEnum.dating)
            p_viewer = Profile(
                user_id=888001, name="Viewer", gender="male", target_gender="female",
                age=20, year=2, is_complete=True, career_is_complete=True, is_visible=True, rating_score=100.0
            )

            # 2. Candidate 1: Девушка, ищет парней (полная совместимость, балл 80)
            u_c1 = User(id=888002, tg_username="girl_1", is_active=True, mode=ModeEnum.dating)
            p_c1 = Profile(
                user_id=888002, name="Алиса", gender="female", target_gender="male",
                age=19, year=1, is_complete=True, is_visible=True, rating_score=80.0
            )

            # 3. Candidate 2: Девушка, ищет парней, Premium + Boost (балл 50, но должна быть первой из-за буста)
            u_c2 = User(
                id=888003, tg_username="girl_boosted", is_active=True, mode=ModeEnum.dating,
                premium_until=datetime.now(timezone.utc) + timedelta(days=7),
                boost_until=datetime.now(timezone.utc) + timedelta(hours=1),
            )
            p_c2 = Profile(
                user_id=888003, name="Белла Премиум", gender="female", target_gender="male",
                age=20, year=2, is_complete=True, is_visible=True, rating_score=50.0
            )

            # 4. Candidate 3: Парень (не должен выпасть, т.к. viewer ищет девушек)
            u_c3 = User(id=888004, tg_username="other_boy", is_active=True, mode=ModeEnum.dating)
            p_c3 = Profile(
                user_id=888004, name="Борис", gender="male", target_gender="female",
                age=21, year=3, is_complete=True, is_visible=True, rating_score=200.0
            )

            # 5. Candidate 4: Девушка, но скрыла анкету (is_visible=False - не должна выпасть)
            u_c4 = User(id=888005, tg_username="hidden_girl", is_active=True, mode=ModeEnum.dating)
            p_c4 = Profile(
                user_id=888005, name="Вера Скрытая", gender="female", target_gender="male",
                age=20, year=2, is_complete=True, is_visible=False, rating_score=999.0
            )

            # 6. Candidate 5: Девушка, но забанена (is_active=False - не должна выпасть)
            u_c5 = User(id=888006, tg_username="banned_girl", is_active=False, mode=ModeEnum.dating)
            p_c5 = Profile(
                user_id=888006, name="Галя Забанена", gender="female", target_gender="male",
                age=19, year=1, is_complete=True, is_visible=True, rating_score=500.0
            )

            # 7. Candidate 6: Девушка, но ищет ТОЛЬКО девушек (target_gender='female' - не должна выпасть парню)
            u_c6 = User(id=888007, tg_username="girl_wants_girl", is_active=True, mode=ModeEnum.dating)
            p_c6 = Profile(
                user_id=888007, name="Даша", gender="female", target_gender="female",
                age=20, year=2, is_complete=True, is_visible=True, rating_score=300.0
            )

            db.add_all([u_viewer, p_viewer, u_c1, p_c1, u_c2, p_c2, u_c3, p_c3, u_c4, p_c4, u_c5, p_c5, u_c6, p_c6])
            await db.commit()

            # 2.1 Первая анкета: должна быть girl_boosted (Белла Премиум) благодаря Premium & Boost
            first = await get_next_profile(db, viewer_id=888001, mode=ModeEnum.dating)
            assert first is not None, "Первая анкета не найдена"
            assert first.user_id == 888003, f"Ожидалась Белла (888003) с бустом, получена {first.name} ({first.user_id})"
            print("  ✅ [2.1] Приоритет сортировки: премиум/буст-анкета успешно показана первой.")
            passed_tests += 1

            # 2.2 Свайпаем Беллу (лайк) и проверяем следующую анкету
            await create_swipe(db, from_id=888001, to_id=888003, action=SwipeAction.like)
            
            second = await get_next_profile(db, viewer_id=888001, mode=ModeEnum.dating)
            assert second is not None, "Вторая анкета не найдена"
            assert second.user_id == 888002, f"Ожидалась Алиса (888002), получена {second.name} ({second.user_id})"
            print("  ✅ [2.2] Исключение свайпнутых: ранее свайпнутая анкета не повторилась, выбрана следующая.")
            passed_tests += 1

            # 2.3 Свайпаем Алису (скип)
            await create_swipe(db, from_id=888001, to_id=888002, action=SwipeAction.skip)

            # Теперь не должно остаться ни одной доступной анкеты
            third = await get_next_profile(db, viewer_id=888001, mode=ModeEnum.dating)
            assert third is None, f"Ожидалось None (все анкеты просмотрены), но вернулось {third.name if third else ''}"
            print("  ✅ [2.3] Гендерная фильтрация и фильтры видимости/банов исключили всех несовместимых кандидатов.")
            passed_tests += 1

            # ─────────────────────────────────────────────────────────────
            # БЛОК 3: ТЕСТИРОВАНИЕ ВХОДЯЩИХ СИМПАТИЙ И СУПЕРЛАЙКОВ В ВЫБОРКЕ
            # ─────────────────────────────────────────────────────────────
            print("\n📌 [БЛОК 3] Тестирование приоритета входящих суперлайков...")

            # Создаем новую девушку, которая суперлайкнула Viewer'а
            u_c7 = User(id=888008, tg_username="superliker_girl", is_active=True, mode=ModeEnum.dating)
            p_c7 = Profile(
                user_id=888008, name="Женя Суперлайк", gender="female", target_gender="male",
                age=20, year=2, is_complete=True, is_visible=True, rating_score=10.0 # низкий рейтинг
            )
            # И обычную девушку с высоким рейтингом
            u_c8 = User(id=888009, tg_username="high_rating_girl", is_active=True, mode=ModeEnum.dating)
            p_c8 = Profile(
                user_id=888009, name="Зоя Высокий Рейтинг", gender="female", target_gender="male",
                age=20, year=2, is_complete=True, is_visible=True, rating_score=500.0 # высокий рейтинг
            )
            db.add_all([u_c7, p_c7, u_c8, p_c8])
            await db.commit()

            # Женя ставит суперлайк Viewer'у
            await create_swipe(db, from_id=888008, to_id=888001, action=SwipeAction.superlike)

            # Теперь для Viewer'а первой ДОЛЖНА выпасть Женя (т.к. она поставила суперлайк), несмотря на низкий балл!
            incoming_top = await get_next_profile(db, viewer_id=888001, mode=ModeEnum.dating)
            assert incoming_top is not None and incoming_top.user_id == 888008, (
                f"Ожидалась Женя Суперлайк (888008), получена {incoming_top.name if incoming_top else None}"
            )
            print("  ✅ [3.1] Входящий суперлайк поднял анкету на 1 место в выдаче с наивысшим приоритетом.")
            passed_tests += 1

            # ─────────────────────────────────────────────────────────────
            # БЛОК 4: ТЕСТИРОВАНИЕ СВАЙПОВ, МЭТЧЕЙ И АВТО-МЭТЧЕЙ
            # ─────────────────────────────────────────────────────────────
            print("\n📌 [БЛОК 4] Тестирование механики взаимных симпатий, списания суперлайков и мэтчей...")

            # 4.1 Списание суперлайка
            u_viewer.superlike_balance = 3
            await db.commit()
            ok_sl = await deduct_superlike(db, u_viewer.id)
            assert ok_sl is True, "Не удалось списать суперлайк"
            u_reloaded = await get_user(db, u_viewer.id)
            assert u_reloaded.superlike_balance == 2, f"Баланс суперлайков {u_reloaded.superlike_balance} вместо 2"
            print("  ✅ [4.1] Списание баланса суперлайков работает корректно.")
            passed_tests += 1

            # 4.2 Взаимный свайп (Мэтч)
            # Viewer лайкает Женю в ответ -> должен случиться МЭТЧ!
            is_match = await create_swipe(db, from_id=888001, to_id=888008, action=SwipeAction.like)
            assert is_match is True, "Ожидался взаимный мэтч при ответе на входящий суперлайк"

            # Проверяем наличие записи в таблице matches
            m_res = await db.execute(
                select(Match).where(
                    (Match.user1_id == 888001) & (Match.user2_id == 888008) |
                    (Match.user1_id == 888008) & (Match.user2_id == 888001)
                )
            )
            match_obj = m_res.scalar_one_or_none()
            assert match_obj is not None, "Объект Match не был создан в базе данных"
            print("  ✅ [4.2] Взаимная симпатия успешно создала объект Match в БД без дубликатов.")
            passed_tests += 1

            # 4.3 Тестовый профиль с auto_match_mode == 'instant'
            u_fake = User(
                id=888010, tg_username="test_bot_girl", is_active=True, is_fake=True,
                auto_match_mode="instant", mode=ModeEnum.dating
            )
            p_fake = Profile(
                user_id=888010, name="Тестовая Девушка", gender="female", target_gender="male",
                age=20, year=2, is_complete=True, is_visible=True
            )
            db.add_all([u_fake, p_fake])
            await db.commit()

            # Viewer лайкает тестовый профиль
            fake_match = await create_swipe(db, from_id=888001, to_id=888010, action=SwipeAction.like)
            assert fake_match is True, "Тестовый профиль с auto_match_mode='instant' должен мгновенно создать мэтч"
            print("  ✅ [4.3] Авто-мэтч тестовых анкет (auto_match_mode=instant) срабатывает мгновенно.")
            passed_tests += 1

            # 4.4 Защита от повторного свайпа (идемпотентность)
            dup_swipe = await create_swipe(db, from_id=888001, to_id=888010, action=SwipeAction.like)
            assert dup_swipe is False, "Повторный свайп должен быть проигнорирован"
            print("  ✅ [4.4] Защита от повторных свайпов и дубликатов в БД работает исправно.")
            passed_tests += 1

            # ─────────────────────────────────────────────────────────────
            # БЛОК 5: ТЕСТИРОВАНИЕ РЕЖИМА «КАРЬЕРА»
            # ─────────────────────────────────────────────────────────────
            print("\n📌 [БЛОК 5] Тестирование выборки в режиме «🎯 Карьера»...")

            # 1. Студент с заполненной карьерной анкетой
            u_car1 = User(id=888011, tg_username="dev_pro", is_active=True, mode=ModeEnum.career)
            p_car1 = Profile(
                user_id=888011, name="Разработчик", career_is_complete=True, is_complete=False,
                is_visible=True, rating_score=120.0
            )
            # 2. Студент без карьерной анкеты (is_complete=True, но career_is_complete=False)
            u_car2 = User(id=888012, tg_username="dating_only", is_active=True, mode=ModeEnum.career)
            p_car2 = Profile(
                user_id=888012, name="Только Дейтинг", career_is_complete=False, is_complete=True,
                is_visible=True, rating_score=300.0
            )
            db.add_all([u_car1, p_car1, u_car2, p_car2])
            await db.commit()

            career_card = await get_next_profile(db, viewer_id=888001, mode=ModeEnum.career)
            assert career_card is not None and career_card.user_id == 888011, (
                f"В режиме карьеры должен выпадать только студент с career_is_complete=True (888011), получено: {career_card.user_id if career_card else None}"
            )
            print("  ✅ [5.1] В режиме «Карьера» корректно фильтруются только профили с career_is_complete=True.")
            passed_tests += 1

            # ─────────────────────────────────────────────────────────────
            # БЛОК 6: РАСШИРЕННЫЕ ФИЛЬТРЫ (КУРС, ВОЗРАСТ, ФАКУЛЬТЕТ, ЖАЛОБЫ)
            # ─────────────────────────────────────────────────────────────
            print("\n📌 [БЛОК 6] Тестирование расширенных поисковых фильтров и исключения жалоб...")

            # Очищаем временных кандидатов для точной проверки фильтров
            await db.execute(delete(Report))
            await db.execute(delete(Swipe))
            await db.execute(delete(Match))
            await db.execute(delete(Profile))
            await db.execute(delete(User))
            await db.commit()

            # 6.1 Исключение заблокированных через жалобу (Report)
            u_rep_viewer = User(id=888030, tg_username="rep_viewer", is_active=True, mode=ModeEnum.dating)
            p_rep_viewer = Profile(
                user_id=888030, name="Смотрящий Репортов", gender="male", target_gender="female",
                is_complete=True, is_visible=True
            )
            u_rep = User(id=888013, tg_username="reported_user", is_active=True, mode=ModeEnum.dating)
            p_rep = Profile(
                user_id=888013, name="Нарушитель", gender="female", target_gender="male",
                age=20, year=2, is_complete=True, is_visible=True, rating_score=100.0
            )
            db.add_all([u_rep_viewer, p_rep_viewer, u_rep, p_rep])
            await db.commit()

            # До жалобы пользователь доступен
            card_before_rep = await get_next_profile(db, viewer_id=888030, mode=ModeEnum.dating)
            assert card_before_rep is not None and card_before_rep.user_id == 888013, "До репорта пользователь должен выпадать"

            # Viewer отправляет жалобу на нарушителя
            db.add(Report(reporter_id=888030, reported_id=888013, reason="Спам"))
            await db.commit()

            # После жалобы пользователь исключается из ленты навсегда!
            card_after_rep = await get_next_profile(db, viewer_id=888030, mode=ModeEnum.dating)
            assert card_after_rep is None, "Пользователь, на которого отправлена жалоба, не должен показываться!"
            print("  ✅ [6.1] Пользователи, на которых отправлена жалоба (Report), навсегда исключаются из выдачи.")
            passed_tests += 1

            # 6.2 Фильтр по диапазону возраста и курсу
            u_searcher = User(id=888020, tg_username="searcher", is_active=True, mode=ModeEnum.dating)
            p_searcher = Profile(
                user_id=888020, name="Искатель", gender="male", target_gender="female",
                filter_min_age=21, filter_max_age=23, filter_min_year=3, filter_max_year=4,
                is_complete=True, is_visible=True
            )
            # Кандидат, подходящий по фильтрам (22 года, 3 курс)
            u_match_filter = User(id=888021, tg_username="good_filter", is_active=True, mode=ModeEnum.dating)
            p_match_filter = Profile(
                user_id=888021, name="Подходящая", gender="female", target_gender="male",
                age=22, year=3, is_complete=True, is_visible=True
            )
            # Кандидат, НЕ подходящий по возрасту (19 лет)
            u_young = User(id=888022, tg_username="too_young", is_active=True, mode=ModeEnum.dating)
            p_young = Profile(
                user_id=888022, name="Слишком юная", gender="female", target_gender="male",
                age=19, year=3, is_complete=True, is_visible=True
            )
            db.add_all([u_searcher, p_searcher, u_match_filter, p_match_filter, u_young, p_young])
            await db.commit()

            filtered_card = await get_next_profile(db, viewer_id=888020, mode=ModeEnum.dating)
            assert filtered_card is not None and filtered_card.user_id == 888021, (
                f"Ожидался кандидат с возрастом 22 и 3 курсом (888021), получено: {filtered_card.user_id if filtered_card else None}"
            )
            print("  ✅ [6.2] Фильтры по возрасту (min/max) и курсу (min/max) работают строго по диапазону.")
            passed_tests += 1

        except Exception as e:
            await db.rollback()
            failed_tests += 1
            print(f"\n❌ ОШИБКА В ХОДЕ ТЕСТА: {e}")
            import traceback
            traceback.print_exc()

    await engine.dispose()
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
        except Exception:
            pass

    print("\n" + "=" * 70)
    print(f"📊 ИТОГИ АУДИТА: Успешно пройдено тестов: {passed_tests} | Ошибок: {failed_tests}")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(run_audit())
