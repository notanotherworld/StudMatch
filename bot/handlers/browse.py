"""
Свайп-интерфейс: поочерёдный показ анкет по одной (Tinder-style).
Действия: ❤️ Лайк, 👎 Дизлайк, ⭐ Суперлайк, 💌 Письмо.
"""
import html
from typing import Optional
from aiogram import Router, F
from aiogram.filters import StateFilter
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from sqlalchemy.orm import selectinload

from bot.keyboards.swipe import (
    swipe_card_keyboard, career_swipe_card_keyboard, main_menu_keyboard, letter_received_keyboard, match_keyboard,
)
from bot.states.fsm import LetterState
from database.crud import get_next_profile, create_swipe, get_user, deduct_superlike
from database.models import User, Profile, InterestTag, SwipeAction, ModeEnum, Swipe

import logging

logger = logging.getLogger(__name__)
router = Router()


async def _build_profile_caption(
    profile: Profile, tags_map: dict[int, InterestTag], user: Optional[User] = None, mode: Optional[ModeEnum] = None
) -> str:
    """Формируем текст карточки студента в зависимости от режима."""
    user_obj = user or (profile.__dict__.get("user") if hasattr(profile, "__dict__") else None)
    card_mode = mode or getattr(user_obj, "mode", ModeEnum.dating)

    name = html.escape(profile.name or "Студент")
    major = html.escape(profile.major or "")
    year_str = f"{profile.year} курс" if profile.year else "Студент"
    raw_rating = getattr(profile, "rating_score", 0.0) or 0.0
    rating = f"⭐ {raw_rating:.0f} б." if raw_rating > 0 else ""

    from datetime import datetime, timezone
    boost_badge = ""
    if user_obj and getattr(user_obj, "boost_until", None):
        if user_obj.boost_until > datetime.now(timezone.utc):
            boost_badge = " 🌪"

    if card_mode == ModeEnum.career:
        skills_text = html.escape(profile.career_custom_skills or "Не указаны")
        goal_text = html.escape(profile.career_goal or "Ищет интересные проекты и стажировки")
        work_fmt = html.escape(profile.career_work_format or "Любой формат")

        return (
            f"<b>{name}</b>{boost_badge}, {year_str} 🎯 <b>[Карьера]</b>\n\n"
            f"📚 {major}\n"
            f"💼 Формат: <b>{work_fmt}</b>\n"
            f"⭐ Рейтинг: <b>{rating}</b>\n\n"
            f"🛠 <b>Навыки и стек:</b>\n{skills_text}\n\n"
            f"🎯 <b>Цель / Опыт:</b>\n<i>{goal_text}</i>"
        )
    else:
        tags_text = ""
        if profile.interest_ids:
            tags = [tags_map[tid] for tid in profile.interest_ids if tid in tags_map]
            tags_text = " ".join(f"#{html.escape(t.name)}" for t in tags)

        if profile.custom_interests:
            custom = html.escape(profile.custom_interests)
            tags_text += f"\n✍️ {custom}" if tags_text else f"✍️ {custom}"

        goal = html.escape(getattr(profile, "goal", "") or "")

        return (
            f"<b>{name}</b>{boost_badge}, {year_str}\n\n"
            f"📚 {major}\n\n"
            f"❤️ Знакомства  {rating}\n\n"
            f"💬 <i>{goal}</i>\n\n"
            f"{tags_text}"
        )


async def send_next_card(
    bot,
    chat_id: int,
    user: User,
    db: AsyncSession,
) -> None:
    """Получить и отправить следующую единичную анкету пользователя."""
    profile = await get_next_profile(db, viewer_id=user.id, mode=user.mode)

    if not profile:
        await bot.send_message(
            chat_id,
            "🎉 <b>Все анкеты просмотрены!</b>\n\n"
            "Ты просмотрел всех доступных студентов на данный момент. "
            "Загляни позже — новые анкеты появляются регулярно! 😉",
            parse_mode="HTML",
            reply_markup=main_menu_keyboard(),
        )
        return

    # Загружаем теги интересов
    tags_map: dict[int, InterestTag] = {}
    if profile.interest_ids:
        result = await db.execute(
            select(InterestTag).where(InterestTag.id.in_(profile.interest_ids))
        )
        for tag in result.scalars().all():
            tags_map[tag.id] = tag

    caption = await _build_profile_caption(profile, tags_map, mode=user.mode)

    if user.mode == ModeEnum.career:
        photo_id = profile.career_avatar_file_id or profile.avatar_file_id
        kb = career_swipe_card_keyboard(
            profile.user_id,
            portfolio_url=profile.career_portfolio_url,
            superlikes_count=user.superlike_balance,
        )
    else:
        photo_id = profile.avatar_file_id
        kb = swipe_card_keyboard(profile.user_id, superlikes_count=user.superlike_balance)

    if photo_id:
        try:
            await bot.send_photo(
                chat_id=chat_id,
                photo=photo_id,
                caption=caption,
                parse_mode="HTML",
                reply_markup=kb,
            )
            return
        except Exception:
            pass

    await bot.send_message(
        chat_id=chat_id,
        text=caption,
        parse_mode="HTML",
        reply_markup=kb,
    )


@router.message(StateFilter("*"), F.text.in_({"🔍 Смотреть анкеты", "Смотреть анкеты", "🏆 Свайп анкет", "🔥 Смотреть анкеты", "🔥 Свайп анкет"}))
async def start_swiping(message: Message, user: User, db: AsyncSession, state: FSMContext = None):
    if state:
        await state.clear()
    if not user.email_verified:
        await message.answer("❌ Сначала пройди верификацию email. Напиши /start")
        return

    if user.mode == ModeEnum.career:
        if not user.profile or not user.profile.career_is_complete:
            from aiogram.utils.keyboard import InlineKeyboardBuilder
            b = InlineKeyboardBuilder()
            b.button(text="🚀 Заполнить анкету Карьеры", callback_data="settings:edit_career_profile")
            b.adjust(1)
            await message.answer(
                "❌ <b>Твоя профессиональная анкета «🎯 Карьера» ещё не заполнена!</b>\n\n"
                "Заполни свои навыки, стек и цели, чтобы начать карьерный нетворкинг и быть заметным для работодателей.",
                parse_mode="HTML",
                reply_markup=b.as_markup(),
            )
            return
    else:
        if not user.profile or not user.profile.is_complete:
            await message.answer("❌ Сначала заполни анкету знакомств. Напиши /start")
            return

    await send_next_card(message.bot, message.chat.id, user, db)


@router.callback_query(F.data == "top:swipe_next")
async def callback_swipe_next(callback: CallbackQuery, user: User, db: AsyncSession):
    await callback.answer()
    try:
        await callback.message.delete()
    except Exception:
        pass
    await send_next_card(callback.bot, callback.message.chat.id, user, db)


@router.callback_query(F.data.startswith("profile:open:"))
async def open_user_profile(callback: CallbackQuery, user: User, db: AsyncSession, state: FSMContext = None):
    """Открыть анкету выбранного студента из Зала славы или мэтча."""
    if state:
        await state.clear()
    try:
        target_id = int(callback.data.split(":")[2])
        target = await get_user(db, target_id)
        if not target or not target.profile:
            await callback.answer("Анкета пользователя не найдена.", show_alert=True)
            return

        await callback.answer()

        tags_map = {}
        if target.profile.interest_ids:
            result = await db.execute(
                select(InterestTag).where(InterestTag.id.in_(target.profile.interest_ids))
            )
            for tag in result.scalars().all():
                tags_map[tag.id] = tag

        caption = await _build_profile_caption(target.profile, tags_map, user=target)
        reply_kb = swipe_card_keyboard(target.id, superlikes_count=user.superlike_balance)

        if target.profile.avatar_file_id:
            try:
                await callback.bot.send_photo(
                    chat_id=callback.message.chat.id,
                    photo=target.profile.avatar_file_id,
                    caption=caption,
                    parse_mode="HTML",
                    reply_markup=reply_kb,
                )
                return
            except Exception as pe:
                logger.warning(f"send_photo failed: {pe}, trying fallback send_message")

        try:
            await callback.bot.send_message(
                chat_id=callback.message.chat.id,
                text=caption,
                parse_mode="HTML",
                reply_markup=reply_kb,
            )
        except Exception:
            clean_text = caption.replace("<b>", "").replace("</b>", "").replace("<i>", "").replace("</i>", "")
            await callback.bot.send_message(
                chat_id=callback.message.chat.id,
                text=clean_text,
                reply_markup=reply_kb,
            )
    except Exception as e:
        logger.error(f"Error opening profile: {e}", exc_info=True)
        await callback.answer("Не удалось открыть анкету.", show_alert=True)


@router.message(StateFilter("*"), F.text.in_({"🫂 Мои мэтчи", "💘 Мои мэтчи", "Мои мэтчи", "/matches"}))
async def show_my_matches(message: Message, user: User, db: AsyncSession, state: FSMContext = None):
    if state:
        await state.clear()
    from database.crud import get_user_matches
    matches = await get_user_matches(db, user.id)

    if not matches:
        await message.answer(
            "🫂 <b>У тебя пока нет мэтчей</b>\n\n"
            "Продолжай смотреть анкеты в разделе <b>«🔍 Смотреть анкеты»</b> — взаимная симпатия появится совсем скоро! 🔥",
            parse_mode="HTML",
            reply_markup=main_menu_keyboard(),
        )
        return

    lines = []
    builder = InlineKeyboardBuilder()

    for idx, (m, partner) in enumerate(matches, start=1):
        p_name = html.escape(partner.profile.name if (partner.profile and partner.profile.name) else "Студент")
        p_username = f"@{partner.tg_username}" if partner.tg_username else "(нет username)"
        p_year = f"{partner.profile.year} курс" if (partner.profile and partner.profile.year) else ""
        date_str = m.created_at.strftime("%d.%m") if m.created_at else ""

        lines.append(f"{idx}. <b>{p_name}</b> ({p_year}) — <b>{p_username}</b> <i>({date_str})</i>")

        if partner.tg_username:
            clean_username = partner.tg_username.lstrip("@")
            builder.button(text=f"💬 Написать {p_name}", url=f"https://t.me/{clean_username}")

    builder.button(text="🔍 Искать новые анкеты", callback_data="top:swipe_next")
    builder.adjust(1)

    text = (
        f"🫂 <b>Твои мэтчи ({len(matches)}):</b>\n\n" +
        "\n".join(lines) +
        "\n\nНажми кнопку ниже, чтобы сразу написать человеку в Telegram!"
    )

    await message.answer(text, parse_mode="HTML", reply_markup=builder.as_markup())


HOW_TO_TOP_TEXT = """<b>КАК ПОПАСТЬ В ТОП 🏆</b>

1) 💼 Участие в кейс-чемпионате / хакатоне — <b>+25 баллов</b>
2) 🥉 Призовое место (3-е место) — <b>+50 баллов</b>
3) 🥈 Призовое место (2-е место) — <b>+75 баллов</b>
4) 🥇 Победа (1-е место) — <b>+100 баллов</b>
5) 🤝 Участие в волонтёрском проекте — <b>+20 баллов</b>
6) 👔 Прохождение стажировки — <b>+60 баллов</b>
7) 🏛 Посещение проф. форума / конференции — <b>+15 баллов</b>
8) 🎤 Выступление на форуме / конференции — <b>+40 баллов</b>

📌 <i>Подтвердить достижения можно в профиле: ⚙️ Настройки → 🏆 Мои достижения</i>"""


@router.callback_query(F.data == "top:how_to")
async def show_how_to_top(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer(HOW_TO_TOP_TEXT, parse_mode="HTML")


# ─── Свайп-действия (лайк, дизлайк, суперлайк) ───────────────────────────
@router.callback_query(F.data.startswith("swipe:"))
async def handle_swipe(callback: CallbackQuery, user: User, db: AsyncSession, state: FSMContext):
    parts = callback.data.split(":")
    action_str = parts[1]

    # Если кликнули на отправку письма, переходим в состояние FSM
    if action_str == "message":
        await prompt_letter(callback, state, user, db)
        return

    target_id = int(parts[2])

    if action_str == "superlike":
        if user.superlike_balance <= 0:
            await callback.answer(
                "У тебя нет суперлайков! Купи их в настройках ⭐",
                show_alert=True
            )
            return
        ok = await deduct_superlike(db, user.id)
        if not ok:
            await callback.answer("Нет суперлайков!", show_alert=True)
            return
        action = SwipeAction.superlike
    elif action_str == "like":
        action = SwipeAction.like
    else:
        action = SwipeAction.skip

    is_match = await create_swipe(db, from_id=user.id, to_id=target_id, action=action)

    if action == SwipeAction.superlike:
        target = await get_user(db, target_id)
        if target:
            try:
                await callback.bot.send_message(
                    target_id,
                    "⭐ <b>Суперлайк!</b>\n\n"
                    "Кто-то очень заинтересован тобой в СтудМэч!",
                    parse_mode="HTML",
                )
            except Exception:
                pass

    if is_match:
        target = await get_user(db, target_id)
        target_name = target.profile.name if target and target.profile else "Студент"
        target_username = f"@{target.tg_username}" if target and target.tg_username else "(нет username)"

        my_name = user.profile.name if user.profile else "Студент"
        my_username = f"@{user.tg_username}" if user.tg_username else "(нет username)"

        # Уведомляем инициатора
        await callback.message.answer(
            f"🎉 <b>МЭТЧ!</b>\n\n"
            f"<b>{html.escape(target_name)}</b> тоже хочет познакомиться с тобой!\n"
            f"Telegram: <b>{target_username}</b>",
            parse_mode="HTML",
            reply_markup=match_keyboard(target_username),
        )

        # Уведомляем вторую сторону
        try:
            await callback.bot.send_message(
                target_id,
                f"🎉 <b>МЭТЧ!</b>\n\n"
                f"<b>{html.escape(my_name)}</b> тоже хочет познакомиться с тобой!\n"
                f"Telegram: <b>{my_username}</b>",
                parse_mode="HTML",
                reply_markup=match_keyboard(my_username),
            )
        except Exception:
            pass

        await callback.answer("🎉 Мэтч!")
    else:
        icons = {"like": "❤️ Лайк", "superlike": "⭐ Суперлайк", "skip": "⏭ Скип"}
        await callback.answer(icons.get(action_str, "✅"))

    # Удаляем или очищаем текущую карточку
    try:
        await callback.message.delete()
    except Exception:
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass

    # Автоматически отправляем СЛЕДУЮЩУЮ анкету!
    await send_next_card(callback.bot, callback.message.chat.id, user, db)


# ─── Отправка письма с анкеты ───────────────────────────
async def prompt_letter(callback: CallbackQuery, state: FSMContext, user: User, db: AsyncSession):
    target_id = int(callback.data.split(":")[-1])
    target = await get_user(db, target_id)
    if not target or not target.profile:
        await callback.answer("Пользователь не найден.", show_alert=True)
        return

    await state.update_data(letter_target_id=target_id)
    await state.set_state(LetterState.waiting_text)
    await callback.answer()

    builder = InlineKeyboardBuilder()
    builder.button(text="✕ Отмена", callback_data="letter:cancel")

    target_name = html.escape(target.profile.name or "пользователю")
    await callback.message.answer(
        f"💌 <b>Написать письмо для {target_name}</b>\n\n"
        f"Введи текст сообщения\n"
        f"<i>(до 500 символов)</i>\n\n"
        f"<i>Пример: Привет! Тоже участвую в хакатонах, давай объединимся 🚀</i>",
        parse_mode="HTML",
        reply_markup=builder.as_markup(),
    )


@router.callback_query(F.data == "letter:cancel", LetterState.waiting_text)
async def cancel_letter(callback: CallbackQuery, state: FSMContext, user: User, db: AsyncSession):
    await state.clear()
    await callback.answer("Отменено")
    try:
        await callback.message.delete()
    except Exception:
        pass

    # При отмене также отправляем следующую анкету
    await send_next_card(callback.bot, callback.message.chat.id, user, db)


@router.message(LetterState.waiting_text)
async def send_letter(message: Message, state: FSMContext, user: User, db: AsyncSession):
    data = await state.get_data()
    target_id = data.get("letter_target_id")
    await state.clear()

    if not target_id:
        await message.answer("Ошибка отправки письма.")
        return

    text = message.text.strip()[:500]
    target = await get_user(db, target_id)
    if not target:
        await message.answer("Пользователь не найден.")
        return

    my_name = user.profile.name if user.profile else "Студент"
    my_year = user.profile.year if user.profile else 1
    my_major = user.profile.major if user.profile else "Вуз"
    my_username = f"@{user.tg_username}" if user.tg_username else "(нет username)"
    target_name = target.profile.name if target.profile else "Студент"
    target_username = f"@{target.tg_username}" if target.tg_username else "(нет username)"

    # Проверяем, есть ли уже свайп
    existing_swipe = await db.execute(
        select(Swipe).where(
            and_(Swipe.from_user_id == user.id, Swipe.to_user_id == target_id)
        )
    )
    has_existing_swipe = existing_swipe.scalar_one_or_none() is not None

    is_match = False
    if not has_existing_swipe:
        is_match = await create_swipe(
            db, from_id=user.id, to_id=target_id, action=SwipeAction.like, comment=text
        )

    if is_match:
        await message.answer(
            f"🎉 <b>Мэтч!</b>\n\n"
            f"<b>{html.escape(target_name)}</b> тоже заинтересован(а) в тебе!\n"
            f"Его/её Telegram: <b>{target_username}</b>",
            parse_mode="HTML",
        )
        try:
            await message.bot.send_message(
                target_id,
                f"🎉 <b>Мэтч!</b>\n\n"
                f"<b>{html.escape(my_name)}</b> тоже заинтересован(а) в тебе!\n"
                f"Его/её Telegram: <b>{my_username}</b>",
                parse_mode="HTML",
            )
        except Exception:
            pass
    else:
        try:
            await message.bot.send_message(
                target_id,
                f"💌 <b>Тебе пришло письмо в СтудМэч!</b>\n\n"
                f"От: <b>{html.escape(my_name)}</b>, {my_year} курс ({html.escape(my_major)})\n\n"
                f"Сообщение: <i>«{html.escape(text)}»</i>",
                parse_mode="HTML",
                reply_markup=letter_received_keyboard(user.id),
            )
        except Exception:
            pass

        await message.answer(
            f"✅ <b>Письмо отправлено для {html.escape(target_name)}!</b>",
            parse_mode="HTML",
        )

    # Автоматически отправляем следующую анкету после отправки письма!
    await send_next_card(message.bot, message.chat.id, user, db)
