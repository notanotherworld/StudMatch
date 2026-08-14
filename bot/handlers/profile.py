"""
Создание анкеты — 5 вопросов + фото (FSM).
"""
import html
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from bot.states.fsm import ProfileState
from bot.keyboards.swipe import (
    year_keyboard, interests_keyboard, main_menu_keyboard, mode_keyboard,
    rudn_institutes_keyboard, RUDN_INSTITUTES,
)
from database.crud import get_or_create_profile, update_profile
from database.models import User, InterestTag

router = Router()


async def start_profile_creation(message: Message, state: FSMContext) -> None:
    """Начать заполнение анкеты с первого вопроса."""
    await state.set_state(ProfileState.waiting_name)
    await message.answer(
        "📋 <b>Создание анкеты</b>\n\n"
        "<b>Вопрос 1/5</b>\n"
        "Как тебя зовут?",
        parse_mode="HTML",
    )


# ─── Вопрос 1: Имя ────────────────────────────────────────────
@router.message(ProfileState.waiting_name)
async def process_name(message: Message, state: FSMContext, user: User, db: AsyncSession):
    raw_name = message.text.strip()
    if len(raw_name) < 2 or len(raw_name) > 50:
        await message.answer("Имя должно быть от 2 до 50 символов. Попробуй ещё раз.")
        return

    name = html.escape(raw_name)  # Защищаем от HTML-инъекций (#18)
    await state.update_data(name=name)
    await state.set_state(ProfileState.waiting_year)
    await message.answer(
        f"👋 Отлично, <b>{name}</b>!\n\n"
        "<b>Вопрос 2/5</b>\n"
        "На каком ты курсе?",
        parse_mode="HTML",
        reply_markup=year_keyboard(),
    )


# ─── Вопрос 2: Курс ───────────────────────────────────────────
@router.callback_query(F.data.startswith("year:"), ProfileState.waiting_year)
async def process_year(callback: CallbackQuery, state: FSMContext):
    year = int(callback.data.split(":")[1])
    await state.update_data(year=year)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer()
    await state.set_state(ProfileState.waiting_major)
    await callback.message.answer(
        f"✅ <b>{year} курс</b> записан!\n\n"
        "<b>Вопрос 3/5</b>\n"
        "Выбери свой институт / факультет РУДН ниже или введи вручную:",
        parse_mode="HTML",
        reply_markup=rudn_institutes_keyboard(),
    )


# ─── Вопрос 3: Направление (кнопка или текст) ──────────────────
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
        "<b>Вопрос 4/5</b>\n"
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

    # Обновляем клавиатуру
    result = await db.execute(select(InterestTag).order_by(InterestTag.id))
    tags = list(result.scalars().all())
    await callback.message.edit_reply_markup(reply_markup=interests_keyboard(tags, selected))
    await callback.answer()


@router.message(ProfileState.waiting_custom_interest)
async def process_custom_interest(message: Message, state: FSMContext, user: User, db: AsyncSession):
    raw_custom = message.text.strip()[:100]
    custom_text = html.escape(raw_custom)  # Защищаем от HTML-инъекций (#18)
    data = await state.get_data()
    selected = data.get("selected_interests", [])

    await update_profile(db, user.id, custom_interests=custom_text)
    await state.update_data(custom_interests=custom_text)

    await message.answer(f"✅ Добавлен свой интерес: <b>{custom_text}</b>", parse_mode="HTML")

    if data.get("editing_from_settings"):
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
async def process_target_gender(callback: CallbackQuery, state: FSMContext):
    tg_val = callback.data.split(":")[1]
    await state.update_data(target_gender=tg_val)
    await state.set_state(ProfileState.waiting_photo)
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        "📸 <b>Почти готово!</b>\n\n"
        "Загрузи фото профиля — оно будет видно другим студентам.\n"
        "<i>Отправь фото как изображение (не как файл)</i>",
        parse_mode="HTML",
    )


# ─── Фото ─────────────────────────────────────────────────────
@router.message(ProfileState.waiting_photo, F.photo)
async def process_photo(message: Message, state: FSMContext, user: User, db: AsyncSession):
    # Берём фото максимального качества
    photo = message.photo[-1]
    file_id = photo.file_id

    data = await state.get_data()

    # Создаём / обновляем профиль
    await get_or_create_profile(db, user.id)
    await update_profile(
        db,
        user.id,
        name=data["name"],
        year=data["year"],
        major=data["major"],
        interest_ids=data.get("selected_interests", []),
        goal=data["goal"],
        gender=data.get("gender"),
        target_gender=data.get("target_gender"),
        avatar_file_id=file_id,
        is_complete=True,
        is_visible=True,
    )

    await state.clear()

    await message.answer(
        "🎉 <b>Профиль создан!</b>\n\n"
        "Теперь выбери режим, в котором хочешь работать:",
        parse_mode="HTML",
        reply_markup=mode_keyboard(),
    )


@router.message(ProfileState.waiting_photo)
async def process_photo_wrong(message: Message):
    await message.answer("Пожалуйста, отправь фото как изображение (не файл).")
