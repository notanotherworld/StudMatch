"""
Создание анкеты — 5 вопросов + фото (FSM).
"""
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from bot.states.fsm import ProfileState
from bot.keyboards.swipe import (
    year_keyboard, interests_keyboard, main_menu_keyboard, mode_keyboard
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
    name = message.text.strip()
    if len(name) < 2 or len(name) > 50:
        await message.answer("Имя должно быть от 2 до 50 символов. Попробуй ещё раз.")
        return

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
        "Твоё направление или специальность?\n"
        "<i>(Например: Информационные системы, Экономика, Медицина...)</i>",
        parse_mode="HTML",
    )


# ─── Вопрос 3: Направление ────────────────────────────────────
@router.message(ProfileState.waiting_major)
async def process_major(message: Message, state: FSMContext, db: AsyncSession):
    major = message.text.strip()
    if len(major) < 2 or len(major) > 100:
        await message.answer("Направление должно быть от 2 до 100 символов.")
        return

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
async def process_interest(callback: CallbackQuery, state: FSMContext, db: AsyncSession):
    value = callback.data.split(":")[1]

    if value == "done":
        data = await state.get_data()
        selected = data.get("selected_interests", [])
        if not selected:
            await callback.answer("Выбери хотя бы один интерес!", show_alert=True)
            return

        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.answer()
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


# ─── Вопрос 5: Цель ───────────────────────────────────────────
@router.message(ProfileState.waiting_goal)
async def process_goal(message: Message, state: FSMContext):
    goal = message.text.strip()
    if len(goal) < 10 or len(goal) > 300:
        await message.answer("Цель должна быть от 10 до 300 символов.")
        return

    await state.update_data(goal=goal)
    await state.set_state(ProfileState.waiting_photo)
    await message.answer(
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
