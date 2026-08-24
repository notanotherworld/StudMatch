"""
Создание анкеты — 5 вопросов + фото (FSM).
"""
import html
from typing import Optional, List, Dict, Any, Set
from aiogram import Router, F
from aiogram.filters import StateFilter, CommandObject
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from bot.states.fsm import ProfileState, CareerProfileState
from bot.keyboards.swipe import (
    age_keyboard, year_keyboard, interests_keyboard, main_menu_keyboard, mode_keyboard,
    rudn_institutes_keyboard, RUDN_INSTITUTES, cancel_reply_keyboard,
    gender_keyboard, target_gender_keyboard,
    career_skills_keyboard, career_work_format_keyboard, CAREER_SKILLS_LIST,
)
from database.crud import get_or_create_profile, update_profile, update_career_profile
from database.models import User, InterestTag, ModeEnum
from aiogram.utils.keyboard import InlineKeyboardBuilder

router = Router()


async def start_profile_creation(message: Message, state: FSMContext) -> None:
    """Начать заполнение анкеты знакомств с первого вопроса."""
    await state.set_state(ProfileState.waiting_name)
    await message.answer(
        "📋 <b>Создание анкеты «❤️ Знакомства»</b>\n\n"
        "<b>Вопрос 1/6: Имя</b>\n"
        "Как тебя зовут?",
        parse_mode="HTML",
        reply_markup=cancel_reply_keyboard(),
    )


async def start_career_profile_creation(event, state: FSMContext, user: User, db: AsyncSession) -> None:
    """Начать заполнение профессиональной анкеты «🎯 Карьера»."""
    message = event if isinstance(event, Message) else event.message
    
    # Если базовые данные (имя/вуз/курс) еще не заполнены
    if not user.profile or not user.profile.name:
        await state.update_data(career_after=True)
        await start_profile_creation(message, state)
        return

    await state.set_state(CareerProfileState.waiting_career_skills)
    await state.update_data(selected_career_skills=[], user_id=user.id)
    
    await message.answer(
        "🎯 <b>Анкета «Карьера»: Шаг 1/4 — Навыки и стек</b>\n\n"
        "Выбери ключевые навыки из списка (можно выбрать несколько) или напиши свои.\n"
        "Когда закончишь — нажми <b>✔️ Готово</b>:",
        parse_mode="HTML",
        reply_markup=career_skills_keyboard([]),
    )


@router.callback_query(F.data == "profile:cancel")
async def cancel_profile_callback(callback: CallbackQuery, state: FSMContext, user: User, db: AsyncSession):
    """Отмена заполнения анкеты по инлайн-кнопке."""
    await state.clear()
    await callback.answer("Редактирование отменено")
    try:
        await callback.message.delete()
    except Exception:
        pass

    if user.profile and user.profile.is_complete:
        await callback.message.answer(
            "❌ <b>Редактирование анкеты отменено.</b>\nТвоя анкета сохранена без изменений.",
            parse_mode="HTML",
            reply_markup=main_menu_keyboard(),
        )
        from bot.handlers.settings import show_my_profile
        await show_my_profile(callback.message, user, db)
    else:
        await callback.message.answer(
            "⚠️ <b>Заполнение анкеты отменено.</b>\n"
            "Без заполненной анкеты функции поиска ограничены. Напиши /start в любое время, чтобы продолжить.",
            parse_mode="HTML",
            reply_markup=main_menu_keyboard(),
        )


@router.message(
    StateFilter(
        ProfileState.waiting_name,
        ProfileState.waiting_year,
        ProfileState.waiting_major,
        ProfileState.waiting_interests,
        ProfileState.waiting_custom_interest,
        ProfileState.waiting_goal,
        ProfileState.waiting_gender,
        ProfileState.waiting_target_gender,
        ProfileState.waiting_photo,
        CareerProfileState.waiting_career_skills,
        CareerProfileState.waiting_career_custom_skills,
        CareerProfileState.waiting_career_goal,
        CareerProfileState.waiting_career_portfolio,
        CareerProfileState.waiting_career_work_format,
        CareerProfileState.waiting_career_photo,
    ),
    F.text.func(
        lambda t: bool(
            t and (
                t in {
                    "❌ Отмена", "Отмена", "/cancel", "🔍 Смотреть анкеты", "Смотреть анкеты",
                    "🏅 Зал славы", "🫂 Мои мэтчи", "Мои мэтчи", "🐾 Мой профиль",
                    "👤 Мой профиль", "Мой профиль", "⚙️ Настройки", "Настройки",
                }
                or "Пригласить" in t
                or "ref" in t.lower()
                or t.startswith("/")
            )
        )
    ),
)
async def cancel_or_route_menu_during_profile(message: Message, state: FSMContext, user: User, db: AsyncSession):
    """Перехват кнопок меню и команды Отмена во время заполнения анкеты."""
    text_val = message.text.strip()
    await state.clear()

    if text_val in {"❌ Отмена", "Отмена", "/cancel"}:
        if user.profile and user.profile.is_complete:
            await message.answer(
                "❌ <b>Редактирование анкеты отменено.</b>\nТвоя анкета сохранена без изменений.",
                parse_mode="HTML",
                reply_markup=main_menu_keyboard(),
            )
            from bot.handlers.settings import show_my_profile
            await show_my_profile(message, user, db)
        else:
            await message.answer(
                "⚠️ <b>Заполнение анкеты отменено.</b>\n"
                "Без заполненной анкеты функции поиска ограничены. Напиши /start в любое время, чтобы продолжить.",
                parse_mode="HTML",
                reply_markup=main_menu_keyboard(),
            )
        return

    # Нажата конкретная кнопка главного меню
    if text_val in {"🔍 Смотреть анкеты", "Смотреть анкеты"}:
        from bot.handlers.browse import start_swiping
        await start_swiping(message, user, db, state)
    elif "Зал славы" in text_val or text_val == "/halloffame" or text_val == "/top":
        from bot.handlers.rating import cmd_hall_of_fame
        await cmd_hall_of_fame(message, user, db, state)
    elif text_val in {"🫂 Мои мэтчи", "Мои мэтчи", "/matches"}:
        from bot.handlers.browse import show_my_matches
        await show_my_matches(message, user, db, state)
    elif text_val in {"🐾 Мой профиль", "👤 Мой профиль", "Мой профиль", "/profile"}:
        from bot.handlers.settings import show_my_profile
        await show_my_profile(message, user, db, state)
    elif text_val in {"⚙️ Настройки", "Настройки", "/settings"}:
        from bot.handlers.settings import show_settings
        await show_settings(message, user, state)
    elif "Пригласить" in text_val or "ref" in text_val.lower():
        from bot.handlers.settings import show_referral_link
        await show_referral_link(message, user, state)
    elif text_val == "/menu":
        await message.answer("📋 <b>Главное меню:</b>", parse_mode="HTML", reply_markup=main_menu_keyboard())
    elif text_val == "/start":
        from bot.handlers.start import cmd_start
        await cmd_start(message, CommandObject(prefix="/", command="start", args=None), state, user, db)


# ─── Вопрос 1: Имя ────────────────────────────────────────────
@router.message(ProfileState.waiting_name)
async def process_name(message: Message, state: FSMContext, user: User, db: AsyncSession):
    raw_name = message.text.strip()
    if len(raw_name) < 2 or len(raw_name) > 50:
        await message.answer("Имя должно быть от 2 до 50 символов. Попробуй ещё раз.")
        return

    name = html.escape(raw_name)  # Защищаем от HTML-инъекций (#18)
    await state.update_data(name=name)
    await state.set_state(ProfileState.waiting_age)
    await message.answer(
        f"👋 Отлично, <b>{name}</b>!\n\n"
        "<b>Вопрос 2/6: Возраст</b>\n"
        "Сколько тебе лет? Напиши число (16–35) или выбери кнопку ниже:",
        parse_mode="HTML",
        reply_markup=age_keyboard(),
    )


# ─── Вопрос 2: Возраст ─────────────────────────────────────────
@router.callback_query(F.data.startswith("age:"), ProfileState.waiting_age)
async def process_age_callback(callback: CallbackQuery, state: FSMContext):
    val = callback.data.split(":")[1]
    if val == "custom":
        await callback.answer()
        await callback.message.answer("Напиши свой возраст числом (например: <code>19</code>):", parse_mode="HTML")
        return
    try:
        age = int(val)
    except ValueError:
        age = 18

    await state.update_data(age=age)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer()
    await state.set_state(ProfileState.waiting_year)
    await callback.message.answer(
        f"✅ Возраст: <b>{age} лет</b> записан!\n\n"
        "<b>Вопрос 3/6: Курс</b>\n"
        "На каком ты курсе?",
        parse_mode="HTML",
        reply_markup=year_keyboard(),
    )


@router.message(ProfileState.waiting_age)
async def process_age_message(message: Message, state: FSMContext):
    text_val = message.text.strip()
    if not text_val.isdigit() or not (15 <= int(text_val) <= 60):
        await message.answer("Пожалуйста, введи корректный возраст числом от 16 до 35 (или выбери кнопку выше).")
        return
    age = int(text_val)
    await state.update_data(age=age)
    await state.set_state(ProfileState.waiting_year)
    await message.answer(
        f"✅ Возраст: <b>{age} лет</b> записан!\n\n"
        "<b>Вопрос 3/6: Курс</b>\n"
        "На каком ты курсе?",
        parse_mode="HTML",
        reply_markup=year_keyboard(),
    )


# ─── Вопрос 3: Курс ───────────────────────────────────────────
@router.callback_query(F.data.startswith("year:"), ProfileState.waiting_year)
async def process_year(callback: CallbackQuery, state: FSMContext):
    year = int(callback.data.split(":")[1])
    await state.update_data(year=year)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer()
    await state.set_state(ProfileState.waiting_major)
    await callback.message.answer(
        f"✅ <b>{year} курс</b> записан!\n\n"
        "<b>Вопрос 4/6: Факультет</b>\n"
        "Выбери свой институт / факультет РУДН ниже или введи вручную:",
        parse_mode="HTML",
        reply_markup=rudn_institutes_keyboard(),
    )


# ─── Вопрос 4: Направление (кнопка или текст) ──────────────────
@router.callback_query(F.data.startswith("major_idx:"), ProfileState.waiting_major)
async def process_major_callback(callback: CallbackQuery, state: FSMContext, db: AsyncSession):
    idx = int(callback.data.split(":")[1])
    major = RUDN_INSTITUTES[idx] if 0 <= idx < len(RUDN_INSTITUTES) else "РУДН"
    await state.update_data(major=major, selected_interests=[])
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer()

    result = await db.execute(select(InterestTag).order_by(InterestTag.id))
    tags = list(result.scalars().all())

    await state.set_state(ProfileState.waiting_interests)
    await callback.message.answer(
        f"✅ Институт: <b>{html.escape(major)}</b>\n\n"
        "<b>Вопрос 5/6: Интересы</b>\n"
        "Выбери свои интересы (можно несколько).\n"
        "Нажми <b>«✔️ Готово»</b> когда выберешь всё.",
        parse_mode="HTML",
        reply_markup=interests_keyboard(tags, selected=[]),
    )


@router.message(ProfileState.waiting_major)
async def process_major(message: Message, state: FSMContext, db: AsyncSession):
    raw_major = message.text.strip()
    if len(raw_major) < 2 or len(raw_major) > 100:
        await message.answer("Направление должно быть от 2 до 100 символов.")
        return

    major = html.escape(raw_major)  # Защищаем от HTML-инъекций (#18)
    await state.update_data(major=major, selected_interests=[])

    # Загружаем теги
    result = await db.execute(select(InterestTag).order_by(InterestTag.id))
    tags = list(result.scalars().all())

    await state.set_state(ProfileState.waiting_interests)
    await message.answer(
        "<b>Вопрос 4/5</b>\n"
        "Выбери свои интересы (можно несколько).\n"
        "Нажми <b>«✔️ Готово»</b> когда выберешь всё.",
        parse_mode="HTML",
        reply_markup=interests_keyboard(tags, selected=[]),
    )


# ─── Вопрос 4: Интересы (множественный выбор) ─────────────────
@router.callback_query(F.data.startswith("interest:"), ProfileState.waiting_interests)
async def process_interest(callback: CallbackQuery, state: FSMContext, user: User, db: AsyncSession):
    value = callback.data.split(":")[1]

    if value == "custom":
        await callback.answer()
        await state.set_state(ProfileState.waiting_custom_interest)
        await callback.message.answer(
            "✍️ <b>Напиши свой интерес или хобби текстом:</b>\n"
            "<i>(Например: 3D Геймдев, Астрофизика, Спортивное ориентирование)</i>",
            parse_mode="HTML",
        )
        return

    if value == "done":
        data = await state.get_data()
        selected = data.get("selected_interests", [])
        custom_interests = data.get("custom_interests")
        if not selected and not custom_interests:
            await callback.answer("Выбери хотя бы один интерес!", show_alert=True)
            return

        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.answer()

        if data.get("editing_from_settings"):
            await update_profile(db, user.id, interest_ids=selected, custom_interests=custom_interests)
            await state.clear()
            await callback.message.answer(
                "✅ <b>Список интересов обновлён!</b>",
                parse_mode="HTML",
                reply_markup=main_menu_keyboard(),
            )
            return

        await state.set_state(ProfileState.waiting_goal)
        await callback.message.answer(
            "<b>Вопрос 5/5</b>\n"
            "Расскажи о своей цели на платформе.\n"
            "<i>(Например: ищу партнёра для стартапа, хочу познакомиться с новыми людьми...)</i>",
            parse_mode="HTML",
        )
        return

    tag_id = int(value)
    data = await state.get_data()
    selected = data.get("selected_interests", [])

    if tag_id in selected:
        selected.remove(tag_id)
    else:
        if len(selected) >= 10:
            await callback.answer("Максимум 10 интересов!", show_alert=True)
            return
        selected.append(tag_id)

    await state.update_data(selected_interests=selected)

    await callback.answer()
    # Обновляем клавиатуру
    result = await db.execute(select(InterestTag).order_by(InterestTag.id))
    tags = list(result.scalars().all())
    try:
        await callback.message.edit_reply_markup(reply_markup=interests_keyboard(tags, selected))
    except Exception:
        pass


@router.message(ProfileState.waiting_custom_interest)
async def process_custom_interest(message: Message, state: FSMContext, user: User, db: AsyncSession):
    if not message.text:
        await message.answer("Пожалуйста, напиши свой интерес текстом.")
        return

    raw_custom = message.text.strip()[:100]
    custom_text = html.escape(raw_custom)  # Защищаем от HTML-инъекций (#18)
    data = await state.get_data()
    selected = data.get("selected_interests", [])

    await update_profile(db, user.id, custom_interests=custom_text)
    await state.update_data(custom_interests=custom_text)

    await message.answer(f"✅ Добавлен свой интерес: <b>{custom_text}</b>", parse_mode="HTML")

    if data.get("editing_from_settings"):
        await update_profile(db, user.id, interest_ids=selected, custom_interests=custom_text)
        await state.clear()
        await message.answer("✅ <b>Интересы обновлены!</b>", parse_mode="HTML", reply_markup=main_menu_keyboard())
    else:
        await state.set_state(ProfileState.waiting_interests)
        result = await db.execute(select(InterestTag).order_by(InterestTag.id))
        tags = list(result.scalars().all())
        await message.answer(
            "Выбери ещё готовые теги или нажми <b>✔️ Готово</b>:",
            parse_mode="HTML",
            reply_markup=interests_keyboard(tags, selected),
        )


# ─── Вопрос 5: Цель ───────────────────────────────────────────
@router.message(ProfileState.waiting_goal)
async def process_goal(message: Message, state: FSMContext):
    raw_goal = message.text.strip()
    if len(raw_goal) < 10 or len(raw_goal) > 300:
        await message.answer("Цель должна быть от 10 до 300 символов.")
        return

    goal = html.escape(raw_goal)
    await state.update_data(goal=goal)
    await state.set_state(ProfileState.waiting_gender)
    from bot.keyboards.swipe import gender_keyboard
    await message.answer(
        "👫 <b>Укажи твой пол:</b>",
        parse_mode="HTML",
        reply_markup=gender_keyboard(),
    )


@router.callback_query(F.data.startswith("gender:"), ProfileState.waiting_gender)
async def process_gender(callback: CallbackQuery, state: FSMContext):
    g_val = callback.data.split(":")[1]
    await state.update_data(gender=g_val)
    await state.set_state(ProfileState.waiting_target_gender)
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)
    from bot.keyboards.swipe import target_gender_keyboard
    await callback.message.answer(
        "❤️ <b>Кого ты ищешь для знакомств?</b>",
        parse_mode="HTML",
        reply_markup=target_gender_keyboard(),
    )


@router.callback_query(F.data.startswith("target_gender:"), ProfileState.waiting_target_gender)
async def process_target_gender(callback: CallbackQuery, state: FSMContext, user: User, db: AsyncSession):
    tg_val = callback.data.split(":")[1]
    await state.update_data(target_gender=tg_val)
    data = await state.get_data()
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)

    # Если пол и предпочтения редактируются отдельно из настроек (кнопка «👫 Пол и предпочтения»)
    if data.get("editing_gender_from_settings"):
        gender_val = data.get("gender")
        await update_profile(db, user.id, gender=gender_val, target_gender=tg_val)
        await state.clear()

        g_name = "👨 Парень" if gender_val == "male" else ("👩 Девушка" if gender_val == "female" else "Не указан")
        tg_name = "👩 Девушек" if tg_val == "female" else ("👨 Парней" if tg_val == "male" else "✨ Всех")

        await callback.message.answer(
            f"✅ <b>Пол и предпочтения успешно сохранены!</b>\n\n"
            f"• Твой пол: <b>{g_name}</b>\n"
            f"• Кого ищешь: <b>{tg_name}</b>",
            parse_mode="HTML",
            reply_markup=main_menu_keyboard(),
        )
        from bot.handlers.settings import show_my_profile
        await show_my_profile(callback.message, user, db, view_mode="dating")
        return

    # Переходим к шагу медиа (загрузка фото/видео или сохранение текущих)
    await state.set_state(ProfileState.waiting_photo)
    await state.update_data(photos=[], video_file_id=None)
    from bot.keyboards.swipe import media_upload_keyboard

    can_keep = bool(user.profile and user.profile.avatar_file_id)
    keep_hint = "\n<i>Или нажми <b>«📸 Оставить текущие фото/видео»</b>, если не хочешь их менять.</i>" if can_keep else ""

    await callback.message.answer(
        "📸 <b>Медиа для анкеты Знакомств:</b>\n\n"
        "• Можно отправить <b>сразу альбомом</b> или по одному: <b>до 3 фото</b> и <b>1 видео</b> (до 10 МБ 🎥)\n"
        "• Первое фото станет твоей главной аватаркой.\n\n"
        f"<i>Выбери в галерее и отправь сразу 3 фото + видео, затем нажми <b>✔️ Завершить загрузку</b></i>{keep_hint}",
        parse_mode="HTML",
        reply_markup=media_upload_keyboard(0, False, can_keep_existing=can_keep),
    )


# ─── Фото и Видео ─────────────────────────────────────────────
async def _save_media_and_complete(
    photos: list[str],
    video_file_id: Optional[str],
    message: Message,
    state: FSMContext,
    user: User,
    db: AsyncSession,
):
    data = await state.get_data()
    prof = user.profile

    if data.get("editing_media_from_settings"):
        main_avatar = photos[0] if photos else (prof.avatar_file_id if prof else None)
        await update_profile(
            db,
            user.id,
            avatar_file_id=main_avatar,
            photos=photos,
            video_file_id=video_file_id,
        )
        await state.clear()
        await message.answer(
            "✅ <b>Фото и видео в твоей анкете успешно обновлены!</b>",
            parse_mode="HTML",
            reply_markup=main_menu_keyboard(),
        )
        from bot.handlers.settings import show_my_profile
        await show_my_profile(message, user, db)
        return

    name = data.get("name") or (prof.name if prof else "Студент")
    age = data.get("age") or (prof.age if prof else None)
    year = data.get("year") or (prof.year if prof else 1)
    major = data.get("major") or (prof.major if prof else "РУДН")
    goal = data.get("goal") or (getattr(prof, "goal", "") if prof else "")
    interest_ids = data.get("selected_interests") if "selected_interests" in data else (prof.interest_ids if prof else [])
    custom_interests = data.get("custom_interests") if "custom_interests" in data else (prof.custom_interests if prof else None)
    gender = data.get("gender") or (prof.gender if prof else None)
    target_gender = data.get("target_gender") or (prof.target_gender if prof else None)
    main_avatar = photos[0] if photos else (prof.avatar_file_id if prof else None)

    was_complete = bool(prof and prof.is_complete)

    await get_or_create_profile(db, user.id)
    await update_profile(
        db,
        user.id,
        name=name,
        age=age,
        year=year,
        major=major,
        interest_ids=interest_ids or [],
        custom_interests=custom_interests,
        goal=goal,
        gender=gender,
        target_gender=target_gender,
        avatar_file_id=main_avatar,
        photos=photos,
        video_file_id=video_file_id,
        is_complete=True,
        is_visible=True,
    )

    await state.clear()

    if was_complete:
        await message.answer(
            "🎉 <b>Твоя анкета «❤️ Знакомства» успешно обновлена!</b>",
            parse_mode="HTML",
            reply_markup=main_menu_keyboard(),
        )
        from bot.handlers.settings import show_my_profile
        await show_my_profile(message, user, db, view_mode="dating")
        return

    verify_tip = ""
    if not user.email_verified:
        verify_tip = (
            "\n\n💡 <i>Совет: подтверди свой студенческий статус в Настройках, "
            "чтобы получить бейдж <b>[ 🎓 Верифицирован ]</b>, <b>+100 баллов</b> к рейтингу и <b>+3 ⭐️ Суперлайка</b>!</i>"
        )

    await message.answer(
        f"🎉 <b>Профиль сохранён!</b>{verify_tip}\n\n"
        "Теперь выбери режим, в котором хочешь искать людей:",
        parse_mode="HTML",
        reply_markup=mode_keyboard(),
    )


@router.callback_query(F.data == "media:keep_existing", ProfileState.waiting_photo)
async def process_media_keep_existing_callback(callback: CallbackQuery, state: FSMContext, user: User, db: AsyncSession):
    """Использовать уже сохраненные медиа (фото/видео) без повторной загрузки."""
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)
    prof = user.profile
    existing_photos = (prof.photos if prof and prof.photos else ([prof.avatar_file_id] if prof and prof.avatar_file_id else []))
    existing_video = prof.video_file_id if prof else None
    await _save_media_and_complete(existing_photos, existing_video, callback.message, state, user, db)


@router.callback_query(F.data == "media:done", ProfileState.waiting_photo)
async def process_media_done_callback(callback: CallbackQuery, state: FSMContext, user: User, db: AsyncSession):
    data = await state.get_data()
    photos = list(data.get("photos", []))
    video_id = data.get("video_file_id")

    if not photos and not (user.profile and user.profile.avatar_file_id):
        await callback.answer("Пожалуйста, загрузи хотя бы 1 фото для анкеты!", show_alert=True)
        return

    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)
    await _save_media_and_complete(photos, video_id, callback.message, state, user, db)


@router.callback_query(F.data == "media:cancel", ProfileState.waiting_photo)
async def process_media_cancel_callback(callback: CallbackQuery, state: FSMContext, user: User, db: AsyncSession):
    await callback.answer()
    await state.clear()
    await callback.message.answer(
        "❌ <b>Загрузка медиа отменена.</b>",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(),
    )
    from bot.handlers.settings import show_my_profile
    await show_my_profile(callback.message, user, db)


@router.message(ProfileState.waiting_photo, F.photo | F.video | F.video_note | F.document)
async def process_media_upload(
    message: Message,
    state: FSMContext,
    user: User,
    db: AsyncSession,
    album: Optional[List[Message]] = None,
):
    data = await state.get_data()
    photos = list(data.get("photos", []))
    video_id = data.get("video_file_id")
    max_video_bytes = 10 * 1024 * 1024  # 10 MB

    messages_to_process = album if album else [message]
    new_photos = []
    new_video = None
    skipped_large_video = False
    excess_photos_count = 0

    for msg in messages_to_process:
        # Фотография
        if msg.photo:
            new_photos.append(msg.photo[-1].file_id)
        # Документ-картинка
        elif msg.document and msg.document.mime_type and msg.document.mime_type.startswith("image/"):
            new_photos.append(msg.document.file_id)
        # Видео или видеозаметка (кружочек)
        elif msg.video or msg.video_note:
            v_obj = msg.video or msg.video_note
            if v_obj.file_size and v_obj.file_size > max_video_bytes:
                skipped_large_video = True
            else:
                new_video = v_obj.file_id

    # Добавляем новые фото с учетом лимита 3
    if new_photos:
        available_slots = 3 - len(photos)
        if available_slots > 0:
            to_add = new_photos[:available_slots]
            photos.extend(to_add)
            if len(new_photos) > available_slots:
                excess_photos_count = len(new_photos) - available_slots
        else:
            excess_photos_count = len(new_photos)

    if new_video:
        video_id = new_video

    await state.update_data(photos=photos, video_file_id=video_id)

    from bot.keyboards.swipe import media_upload_keyboard

    # Формируем статус
    video_status = "📹 1 видео добавлено" if video_id else "нет видео"
    notes = []
    if excess_photos_count > 0:
        notes.append(f"ℹ️ <i>Сохранены первые {len(photos)} фото (лимит — 3 фото).</i>")
    if skipped_large_video:
        notes.append("⚠️ <i>Видео превышает лимит 10 МБ и не было добавлено.</i>")

    notes_text = ("\n" + "\n".join(notes)) if notes else ""

    await message.answer(
        f"✅ <b>Медиа получено!</b>\n\n"
        f"• Фото: <b>{len(photos)}/3</b>\n"
        f"• Видео: <b>{video_status}</b>{notes_text}\n\n"
        f"<i>Нажми <b>✔️ Завершить загрузку</b> или отправь ещё фото/видео:</i>",
        parse_mode="HTML",
        reply_markup=media_upload_keyboard(len(photos), bool(video_id)),
    )


@router.message(ProfileState.waiting_photo)
async def process_photo_wrong(message: Message):
    await message.answer("Пожалуйста, отправь фото как изображение или видео (до 10 МБ).")


# ─────────────────────────────────────────────────────────────
# FSM: Анкета «🎯 Карьера»
# ─────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("cskill:"), CareerProfileState.waiting_career_skills)
async def process_career_skill_callback(callback: CallbackQuery, state: FSMContext):
    action = callback.data.split(":")[1]
    data = await state.get_data()
    selected: list = list(data.get("selected_career_skills", []))

    if action == "custom":
        await state.set_state(CareerProfileState.waiting_career_custom_skills)
        await callback.answer()
        await callback.message.answer(
            "✍️ <b>Напиши свои навыки или технологии через запятую:</b>\n"
            "<i>(Например: FastApi, Docker, PostgreSQL, Flutter, Английский C1)</i>",
            parse_mode="HTML",
            reply_markup=cancel_reply_keyboard(),
        )
        return

    if action == "done":
        await callback.answer()
        await state.set_state(CareerProfileState.waiting_career_goal)
        await callback.message.answer(
            "🎯 <b>Анкета «Карьера»: Шаг 2/4 — Карьерная цель и опыт</b>\n\n"
            "Расскажи о своих целях и что ищешь:\n"
            "<i>(Например: Ищу стажировку Python-разработчиком, готовлюсь к хакатонам, ищу команду в стартап или ментора)</i>",
            parse_mode="HTML",
            reply_markup=cancel_reply_keyboard(),
        )
        return

    # Выбор конкретного скилла
    try:
        idx = int(action)
        skill_name = CAREER_SKILLS_LIST[idx]
        if skill_name in selected:
            selected.remove(skill_name)
        else:
            selected.append(skill_name)
        await state.update_data(selected_career_skills=selected)
        await callback.message.edit_reply_markup(
            reply_markup=career_skills_keyboard(selected)
        )
        await callback.answer()
    except Exception:
        await callback.answer()


@router.message(CareerProfileState.waiting_career_custom_skills)
async def process_career_custom_skills(message: Message, state: FSMContext):
    custom_skills = html.escape(message.text.strip())
    data = await state.get_data()
    prev_custom = data.get("custom_skills", "")
    full_custom = f"{prev_custom}, {custom_skills}".strip(", ") if prev_custom else custom_skills
    await state.update_data(custom_skills=full_custom)

    await message.answer(f"✅ Добавлены навыки: <b>{html.escape(custom_skills)}</b>", parse_mode="HTML")
    
    await state.set_state(CareerProfileState.waiting_career_skills)
    selected = list(data.get("selected_career_skills", []))
    await message.answer(
        "Выбери ещё навыки из списка или нажми <b>✔️ Готово</b>:",
        parse_mode="HTML",
        reply_markup=career_skills_keyboard(selected),
    )


@router.message(CareerProfileState.waiting_career_goal)
async def process_career_goal(message: Message, state: FSMContext):
    raw_goal = message.text.strip()
    if len(raw_goal) < 5 or len(raw_goal) > 400:
        await message.answer("Цель должна быть от 5 до 400 символов.")
        return

    goal = html.escape(raw_goal)
    await state.update_data(career_goal=goal)
    await state.set_state(CareerProfileState.waiting_career_portfolio)

    builder = InlineKeyboardBuilder()
    builder.button(text="Пропустить ⏭", callback_data="portfolio:skip")
    builder.button(text="❌ Отмена", callback_data="profile:cancel")
    builder.adjust(1)

    await message.answer(
        "🔗 <b>Анкета «Карьера»: Шаг 3/4 — Портфолио / Резюме / GitHub</b>\n\n"
        "Отправь ссылку на свой GitHub, Behance, Notion, резюме на HeadHunter или LinkedIn:\n"
        "<i>(Если ссылки нет, нажми «Пропустить»)</i>",
        parse_mode="HTML",
        reply_markup=builder.as_markup(),
    )


@router.callback_query(F.data == "portfolio:skip", CareerProfileState.waiting_career_portfolio)
async def process_portfolio_skip(callback: CallbackQuery, state: FSMContext):
    await state.update_data(career_portfolio_url=None)
    await state.set_state(CareerProfileState.waiting_career_work_format)
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        "💼 <b>Анкета «Карьера»: Шаг 4/4 — Формат работы</b>\n\n"
        "Какой формат работы тебе наиболее интересен?",
        parse_mode="HTML",
        reply_markup=career_work_format_keyboard(),
    )


@router.message(CareerProfileState.waiting_career_portfolio)
async def process_portfolio_url(message: Message, state: FSMContext):
    url_text = message.text.strip()
    if not (url_text.startswith("http://") or url_text.startswith("https://") or "t.me/" in url_text or "github.com" in url_text or "hh.ru" in url_text):
        url_text = f"https://{url_text}"

    await state.update_data(career_portfolio_url=url_text)
    await state.set_state(CareerProfileState.waiting_career_work_format)

    await message.answer(
        "💼 <b>Анкета «Карьера»: Шаг 4/4 — Формат работы</b>\n\n"
        "Какой формат работы тебе наиболее интересен?",
        parse_mode="HTML",
        reply_markup=career_work_format_keyboard(),
    )


@router.callback_query(F.data.startswith("wformat:"), CareerProfileState.waiting_career_work_format)
async def process_career_work_format(callback: CallbackQuery, state: FSMContext, user: User):
    fmt_val = callback.data.split(":")[1]
    format_map = {
        "remote": "🌐 Удалённо",
        "office": "🏢 Офис",
        "hybrid": "⚖️ Гибрид",
        "part_time": "⏱ Гибкий график / Part-time",
        "skip": None,
    }
    work_format = format_map.get(fmt_val)
    await state.update_data(career_work_format=work_format)
    await state.set_state(CareerProfileState.waiting_career_photo)
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)

    builder = InlineKeyboardBuilder()
    if user.profile and user.profile.avatar_file_id:
        builder.button(text="📸 Использовать фото из Знакомств", callback_data="career_photo:use_dating")
    builder.button(text="❌ Отмена", callback_data="profile:cancel")
    builder.adjust(1)

    await callback.message.answer(
        "📸 <b>Деловое фото для Карьеры</b>\n\n"
        "Загрузи портретное/деловое фото для профессиональной анкеты.\n"
        "<i>Оно будет отображаться работодателям (HR) и студентам в карьерном поиске.</i>",
        parse_mode="HTML",
        reply_markup=builder.as_markup(),
    )


async def _save_career_profile_and_complete(
    file_id: Optional[str], message: Message, state: FSMContext, user: User, db: AsyncSession
):
    data = await state.get_data()
    selected_skills = data.get("selected_career_skills", [])
    custom_skills = data.get("custom_skills", "")
    
    # Объединяем навыки
    skills_text_parts = list(selected_skills)
    if custom_skills:
        skills_text_parts.append(custom_skills)
    skills_combined = ", ".join(skills_text_parts) if skills_text_parts else None

    career_goal = data.get("career_goal")
    career_portfolio_url = data.get("career_portfolio_url")
    career_work_format = data.get("career_work_format")

    photo_id = file_id or (user.profile.avatar_file_id if user.profile else None)

    await update_career_profile(
        db,
        user.id,
        career_goal=career_goal,
        career_custom_skills=skills_combined,
        career_portfolio_url=career_portfolio_url,
        career_work_format=career_work_format,
        career_avatar_file_id=photo_id,
        career_is_complete=True,
    )

    await state.clear()

    await message.answer(
        "🎉 <b>Профессиональная анкета «🎯 Карьера» успешно сохранена!</b>\n\n"
        "Теперь работодатели (HR) и студенты могут видеть твои навыки и проекты при поиске.\n"
        "Ты можешь переключаться между Знакомствами и Карьерой в любой момент в настройках!",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(),
    )
    from bot.handlers.settings import show_my_profile
    await show_my_profile(message, user, db, view_mode="career")


@router.callback_query(F.data == "career_photo:use_dating", CareerProfileState.waiting_career_photo)
async def process_career_photo_use_dating(callback: CallbackQuery, state: FSMContext, user: User, db: AsyncSession):
    await callback.answer()
    dating_photo = user.profile.avatar_file_id if user.profile else None
    await _save_career_profile_and_complete(dating_photo, callback.message, state, user, db)


@router.message(CareerProfileState.waiting_career_photo, F.photo)
async def process_career_photo(message: Message, state: FSMContext, user: User, db: AsyncSession):
    photo = message.photo[-1]
    await _save_career_profile_and_complete(photo.file_id, message, state, user, db)


@router.message(CareerProfileState.waiting_career_photo, F.document)
async def process_career_photo_document(message: Message, state: FSMContext, user: User, db: AsyncSession):
    if message.document and message.document.mime_type and message.document.mime_type.startswith("image/"):
        await _save_career_profile_and_complete(message.document.file_id, message, state, user, db)
    else:
        await message.answer("Пожалуйста, отправь фото как изображение (JPG/PNG).")
