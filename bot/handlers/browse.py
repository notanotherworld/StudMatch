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
    swipe_card_keyboard, career_swipe_card_keyboard, main_menu_keyboard,
    letter_received_keyboard, match_keyboard, incoming_like_keyboard,
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
    now = datetime.now(timezone.utc)

    is_prem = False
    if user_obj and getattr(user_obj, "premium_until", None):
        p_until = user_obj.premium_until
        if p_until.tzinfo is None:
            p_until = p_until.replace(tzinfo=timezone.utc)
        if p_until > now:
            is_prem = True

    boost_badge = ""
    if user_obj and getattr(user_obj, "boost_until", None):
        b_until = user_obj.boost_until
        if b_until.tzinfo is None:
            b_until = b_until.replace(tzinfo=timezone.utc)
        if b_until > now:
            boost_badge = " 🌪 [В топе]"

    header_badges = []
    if is_prem:
        header_badges.append("💎✨ <b>PREMIUM ПРОФИЛЬ</b> ✨💎")

    if user_obj and getattr(user_obj, "email_verified", False):
        univ_str = ""
        if hasattr(user_obj, "university") and user_obj.university and getattr(user_obj.university, "short_name", None):
            univ_str = f": {user_obj.university.short_name}"
        header_badges.append(f"🎓 <b>ВЕРИФИЦИРОВАН{univ_str}</b>")

    badges_header = ("\n".join(header_badges) + "\n\n") if header_badges else ""
    title_name = f"💎 <b>{name}</b>" if is_prem else f"<b>{name}</b>"

    age_str = ""
    if getattr(profile, "age", None):
        a_val = profile.age
        if 11 <= (a_val % 100) <= 19:
            suf = "лет"
        elif a_val % 10 == 1:
            suf = "год"
        elif a_val % 10 in (2, 3, 4):
            suf = "года"
        else:
            suf = "лет"
        age_str = f", {a_val} {suf}"

    if card_mode == ModeEnum.career:
        skills_text = html.escape(profile.career_custom_skills or "Не указаны")
        goal_text = html.escape(profile.career_goal or "Ищет интересные проекты и стажировки")
        work_fmt = html.escape(profile.career_work_format or "Любой формат")

        return (
            f"{badges_header}"
            f"{title_name}{age_str}, {year_str} 🎯 <b>[Карьера]</b>{boost_badge}\n\n"
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
            f"{badges_header}"
            f"{title_name}{age_str}, {year_str} ❤️ <b>[Знакомства]</b>{boost_badge}\n\n"
            f"📚 {major}\n\n"
            f"❤️ Знакомства  {rating}\n\n"
            f"💬 <i>{goal}</i>\n\n"
            f"{tags_text}"
        )


import os
from aiogram.types import FSInputFile, URLInputFile

def _get_photo_input(photo_id: Optional[str]):
    """Возвращает InputFile (FSInputFile, URLInputFile или file_id) для Telegram."""
    if not photo_id or not str(photo_id).strip() or str(photo_id).strip().lower() in ("none", "null"):
        return None
    photo_str = str(photo_id).strip()
    if photo_str.startswith("http://") or photo_str.startswith("https://"):
        return URLInputFile(photo_str)
    if (
        photo_str.startswith("/static/")
        or photo_str.startswith("static/")
        or photo_str.startswith("web/")
        or photo_str.startswith("/uploads/")
        or photo_str.startswith("uploads/")
    ):
        clean_path = photo_str.lstrip("/")
        if not clean_path.startswith("web/"):
            clean_path = os.path.join("web", clean_path)
        if os.path.exists(clean_path):
            return FSInputFile(clean_path)
        return None
    return photo_str


def _safe_media_caption(caption: str, max_len: int = 1024) -> str:
    """Безопасная обрезка подписи медиа для соблюдения лимита Telegram API (1024 символа)."""
    if len(caption) <= max_len:
        return caption
    # Обрезаем так, чтобы не сломать незакрытый тег, если возможно
    trimmed = caption[: max_len - 10]
    return trimmed + "...\n<i>(анкета сокращена)</i>"


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

    # Проверяем, есть ли входящий лайк или суперлайк от этого студента к пользователю
    incoming_swipe = await db.scalar(
        select(Swipe.action).where(
            Swipe.from_user_id == profile.user_id,
            Swipe.to_user_id == user.id,
            Swipe.action.in_([SwipeAction.superlike, SwipeAction.like]),
        )
    )
    badge = ""
    if incoming_swipe == SwipeAction.superlike:
        badge = "⭐ <b>ТЕБЯ СУПЕРЛАЙКНУЛИ!</b> ⭐\n<i>Пользователь очень хочет познакомиться с тобой:</i>\n\n"
    elif incoming_swipe == SwipeAction.like:
        badge = "❤️ <b>ПОЛЬЗОВАТЕЛЬ ЛАЙКНУЛ ТЕБЯ!</b>\n\n"

    base_caption = await _build_profile_caption(profile, tags_map, mode=user.mode)
    caption = f"{badge}{base_caption}"

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

    from aiogram.types import InputMediaPhoto, InputMediaVideo

    # Формируем список медиа (до 3 фото и 1 видео)
    photos = list(profile.photos) if profile.photos else ([profile.avatar_file_id] if profile.avatar_file_id else [])
    if user.mode == ModeEnum.career and profile.career_avatar_file_id:
        if profile.career_avatar_file_id not in photos:
            photos = [profile.career_avatar_file_id] + photos

    # Ограничиваем до 3 фото
    photos = photos[:3]
    video_id = profile.video_file_id

    # Если медиа больше одного — отправляем медиагруппу (альбом)
    total_media_count = len(photos) + (1 if video_id else 0)

    media_caption = _safe_media_caption(caption)

    if total_media_count > 1:
        media_group = []
        is_first = True
        for p_id in photos:
            p_input = _get_photo_input(p_id)
            if p_input:
                if is_first:
                    media_group.append(InputMediaPhoto(media=p_input, caption=media_caption, parse_mode="HTML"))
                    is_first = False
                else:
                    media_group.append(InputMediaPhoto(media=p_input))

        if video_id:
            v_input = _get_photo_input(video_id)
            if v_input:
                if is_first:
                    media_group.append(InputMediaVideo(media=v_input, caption=media_caption, parse_mode="HTML"))
                    is_first = False
                else:
                    media_group.append(InputMediaVideo(media=v_input))

        if media_group:
            try:
                await bot.send_media_group(chat_id=chat_id, media=media_group)
                await bot.send_message(
                    chat_id=chat_id,
                    text="👇 <b>Твой выбор:</b>",
                    parse_mode="HTML",
                    reply_markup=kb,
                )
                return
            except Exception as me:
                logger.warning(f"send_media_group failed: {me}, fallback to single photo")

    # Если одно фото или fallback
    if photos:
        p_input = _get_photo_input(photos[0])
        if p_input:
            try:
                await bot.send_photo(
                    chat_id=chat_id,
                    photo=p_input,
                    caption=media_caption,
                    parse_mode="HTML",
                    reply_markup=kb,
                )
                return
            except Exception as pe:
                logger.warning(f"send_photo failed with input {p_input}: {pe}")

    if video_id:
        v_input = _get_photo_input(video_id)
        if v_input:
            try:
                await bot.send_video(
                    chat_id=chat_id,
                    video=v_input,
                    caption=media_caption,
                    parse_mode="HTML",
                    reply_markup=kb,
                )
                return
            except Exception as ve:
                logger.warning(f"send_video failed: {ve}")

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
        media_caption = _safe_media_caption(caption)

        photo_input = _get_photo_input(target.profile.avatar_file_id)
        if photo_input:
            try:
                await callback.bot.send_photo(
                    chat_id=callback.message.chat.id,
                    photo=photo_input,
                    caption=media_caption,
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

        ver_badge = " 🎓" if getattr(partner, "email_verified", False) else ""
        prem_badge = " 💎" if getattr(partner, "is_premium", False) else ""

        lines.append(f"{idx}. <b>{p_name}</b>{ver_badge}{prem_badge} ({p_year}) — <b>{p_username}</b> <i>({date_str})</i>")

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


@router.callback_query(F.data == "profile:incoming_likes")
@router.message(StateFilter("*"), F.text.in_({"💌 Кто меня лайкнул", "Кто меня лайкнул", "/likes"}))
async def show_incoming_likes_entry(event: Message | CallbackQuery, user: User, db: AsyncSession, state: FSMContext = None):
    """Просмотр входящих симпатий для Премиум-пользователей / Пейволл для обычных."""
    if state:
        await state.clear()

    from database.crud import get_incoming_likes, get_incoming_likes_count

    pending_count = await get_incoming_likes_count(db, user.id)
    is_prem = user.is_premium

    if not is_prem:
        # Paywall для пользователей без подписки
        text = (
            f"💌 <b>Кто меня лайкнул?</b>\n\n"
            f"У тебя <b>{pending_count}</b> непросмотренных симпатий! 🔥\n\n"
            f"👑 <b>Преимущества Премиум-профиля:</b>\n"
            f"• 💌 <b>Просмотр всех, кто тебя лайкнул</b> — сразу отвечай взаимностью без ожидания!\n"
            f"• 🚀 <b>Приоритет №1 в ленте свайпов</b> — твоя анкета показывается первой\n"
            f"• 💎 <b>Статусный бейдж [Премиум]</b> в профиле и Зале славы\n"
            f"• ⭐️ <b>+10 Суперлайков</b> на баланс\n"
            f"• 🌪 <b>Постоянный буст анкеты</b>\n\n"
            f"Оформи Премиум прямо сейчас:"
        )
        builder = InlineKeyboardBuilder()
        builder.button(text="💎 Оформить Премиум", callback_data="buy:premium_1m")
        builder.button(text="🔙 Назад к анкетам", callback_data="top:swipe_next")
        builder.adjust(1)

        if isinstance(event, CallbackQuery):
            await event.answer()
            await event.message.answer(text, parse_mode="HTML", reply_markup=builder.as_markup())
        else:
            await event.answer(text, parse_mode="HTML", reply_markup=builder.as_markup())
        return

    likes = await get_incoming_likes(db, user.id, limit=1)
    if not likes:
        empty_text = (
            "💌 <b>Входящие симпатии</b>\n\n"
            "У тебя пока нет новых непросмотренных лайков.\n"
            "Твоя анкета показывается в топе с приоритетом 💎 — скоро здесь появятся новые взаимные симпатии!"
        )
        builder = InlineKeyboardBuilder()
        builder.button(text="🔍 Смотреть анкеты", callback_data="top:swipe_next")
        if isinstance(event, CallbackQuery):
            await event.answer()
            await event.message.answer(empty_text, parse_mode="HTML", reply_markup=builder.as_markup())
        else:
            await event.answer(empty_text, parse_mode="HTML", reply_markup=builder.as_markup())
        return

    like = likes[0]
    candidate = like.from_user
    cand_profile = candidate.profile
    if not cand_profile:
        if isinstance(event, CallbackQuery):
            await event.answer("Анкета больше не найдена.", show_alert=True)
        return

    tags_map = {}
    if cand_profile.interest_ids:
        try:
            res = await db.execute(select(InterestTag).where(InterestTag.id.in_(cand_profile.interest_ids)))
            for t in res.scalars().all():
                tags_map[t.id] = t
        except Exception:
            pass

    card_text = await _build_profile_caption(cand_profile, tags_map, user=candidate, mode=candidate.mode)
    action_label = "⭐ <b>СУПЕРЛАЙКНУЛ(А) ТЕБЯ!</b>" if like.action == SwipeAction.superlike else "❤️ <b>ПОСТАВИЛ(А) ТЕБЕ ЛАЙК!</b>"
    comment_block = f"\n\n💌 <i>«{html.escape(like.comment)}»</i>" if like.comment else ""

    header = f"💌 <b>Входящая симпатия (всего {pending_count}):</b>\n{action_label}{comment_block}\n\n"
    full_text = header + card_text
    media_full_text = _safe_media_caption(full_text)

    portfolio_url = cand_profile.career_portfolio_url if candidate.mode == ModeEnum.career else None
    kb = incoming_like_keyboard(from_user_id=candidate.id, portfolio_url=portfolio_url)

    target_chat_id = event.message.chat.id if isinstance(event, CallbackQuery) else event.chat.id
    if isinstance(event, CallbackQuery):
        await event.answer()

    photos = list(cand_profile.photos) if cand_profile.photos else ([cand_profile.avatar_file_id] if cand_profile.avatar_file_id else [])
    if candidate.mode == ModeEnum.career and cand_profile.career_avatar_file_id and cand_profile.career_avatar_file_id not in photos:
        photos = [cand_profile.career_avatar_file_id] + photos
    photos = photos[:3]

    photo_input = _get_photo_input(photos[0]) if photos else None
    if photo_input:
        try:
            await event.bot.send_photo(chat_id=target_chat_id, photo=photo_input, caption=media_full_text, parse_mode="HTML", reply_markup=kb)
            return
        except Exception as e:
            logger.warning(f"Failed to send incoming like photo: {e}")

    await event.bot.send_message(chat_id=target_chat_id, text=full_text, parse_mode="HTML", reply_markup=kb)


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


async def send_like_notification(
    bot,
    target_user_id: int,
    from_user: User,
    action: SwipeAction,
    letter_text: Optional[str] = None,
    db: Optional[AsyncSession] = None,
) -> None:
    """
    Отправляет пользователю target_user_id интерактивную карточку
    пользователя from_user с кнопками «❤️ Ответить взаимностью» и «⏭ Пропустить».
    """
    if not from_user or not from_user.profile:
        return

    profile = from_user.profile
    mode = from_user.mode or ModeEnum.dating

    # Загружаем теги интересов
    tags_map: dict[int, InterestTag] = {}
    if profile.interest_ids and db:
        try:
            result = await db.execute(
                select(InterestTag).where(InterestTag.id.in_(profile.interest_ids))
            )
            for tag in result.scalars().all():
                tags_map[tag.id] = tag
        except Exception:
            pass

    body_caption = await _build_profile_caption(profile, tags_map, user=from_user, mode=mode)

    if action == SwipeAction.superlike:
        header = (
            "⭐ <b>ТЕБЯ СУПЕРЛАЙКНУЛИ!</b> ⭐\n"
            "<i>Пользователь очень хочет познакомиться с тобой:</i>\n\n"
        )
    else:
        header = (
            "❤️ <b>КОМУ-ТО ПОНРАВИЛАСЬ ТВОЯ АНКЕТА!</b>\n"
            "<i>Пользователь проявил к тебе интерес:</i>\n\n"
        )

    letter_block = ""
    if letter_text:
        letter_block = f"\n\n💌 <b>Личное письмо:</b>\n<i>«{html.escape(letter_text)}»</i>"

    footer = "\n\n👇 <i>Нажми «❤️ Ответить взаимностью», чтобы получить контакты и начать общение!</i>"
    full_caption = f"{header}{body_caption}{letter_block}{footer}"
    media_full_caption = _safe_media_caption(full_caption)

    portfolio_url = profile.career_portfolio_url if mode == ModeEnum.career else None
    kb = incoming_like_keyboard(from_user_id=from_user.id, portfolio_url=portfolio_url)

    from aiogram.types import InputMediaPhoto, InputMediaVideo

    photos = list(profile.photos) if profile.photos else ([profile.avatar_file_id] if profile.avatar_file_id else [])
    if mode == ModeEnum.career and profile.career_avatar_file_id:
        if profile.career_avatar_file_id not in photos:
            photos = [profile.career_avatar_file_id] + photos
    photos = photos[:3]
    video_id = profile.video_file_id

    total_media_count = len(photos) + (1 if video_id else 0)

    if total_media_count > 1:
        media_group = []
        is_first = True
        for p_id in photos:
            p_input = _get_photo_input(p_id)
            if p_input:
                if is_first:
                    media_group.append(InputMediaPhoto(media=p_input, caption=media_full_caption, parse_mode="HTML"))
                    is_first = False
                else:
                    media_group.append(InputMediaPhoto(media=p_input))
        if video_id:
            v_input = _get_photo_input(video_id)
            if v_input:
                if is_first:
                    media_group.append(InputMediaVideo(media=v_input, caption=media_full_caption, parse_mode="HTML"))
                    is_first = False
                else:
                    media_group.append(InputMediaVideo(media=v_input))

        if media_group:
            try:
                await bot.send_media_group(chat_id=target_user_id, media=media_group)
                await bot.send_message(
                    chat_id=target_user_id,
                    text="👇 <b>Твой ответ:</b>",
                    parse_mode="HTML",
                    reply_markup=kb,
                )
                return
            except Exception as e:
                logger.warning(f"send_like_notification media group failed: {e}")

    if photos:
        p_input = _get_photo_input(photos[0])
        if p_input:
            try:
                await bot.send_photo(
                    chat_id=target_user_id,
                    photo=p_input,
                    caption=media_full_caption,
                    parse_mode="HTML",
                    reply_markup=kb,
                )
                return
            except Exception as e:
                logger.warning(f"send_like_notification photo failed: {e}")

    try:
        await bot.send_message(
            chat_id=target_user_id,
            text=full_caption,
            parse_mode="HTML",
            reply_markup=kb,
        )
    except Exception as e:
        logger.warning(f"send_like_notification text fallback failed: {e}")


@router.callback_query(F.data.startswith("incoming:like:"))
async def process_incoming_like(callback: CallbackQuery, user: User, db: AsyncSession):
    """Обработка взаимного лайка по карточке входящего уведомления."""
    target_id = int(callback.data.split(":")[2])
    target = await get_user(db, target_id)

    if not target or not target.profile:
        await callback.answer("Анкета больше не найдена.", show_alert=True)
        return

    is_match = await create_swipe(db, from_id=user.id, to_id=target_id, action=SwipeAction.like)

    target_name = target.profile.name if target and target.profile else "Студент"
    target_username = f"@{target.tg_username}" if target and target.tg_username else "(нет username)"
    my_name = user.profile.name if user.profile else "Студент"
    my_username = f"@{user.tg_username}" if user.tg_username else "(нет username)"

    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    # Уведомляем текущего пользователя
    await callback.message.answer(
        f"🎉 <b>МЭТЧ!</b>\n\n"
        f"Вы с <b>{html.escape(target_name)}</b> понравились друг другу!\n"
        f"Telegram: <b>{target_username}</b>",
        parse_mode="HTML",
        reply_markup=match_keyboard(target_username),
    )

    # Уведомляем инициатора первого лайка
    try:
        await callback.bot.send_message(
            target_id,
            f"🎉 <b>МЭТЧ!</b>\n\n"
            f"<b>{html.escape(my_name)}</b> ответил(а) взаимностью на твой лайк!\n"
            f"Telegram: <b>{my_username}</b>",
            parse_mode="HTML",
            reply_markup=match_keyboard(my_username),
        )
    except Exception:
        pass

    await callback.answer("🎉 Мэтч!")


@router.callback_query(F.data.startswith("incoming:skip:"))
async def process_incoming_skip(callback: CallbackQuery, user: User, db: AsyncSession):
    """Пропуск входящего лайка."""
    target_id = int(callback.data.split(":")[2])
    await create_swipe(db, from_id=user.id, to_id=target_id, action=SwipeAction.skip)

    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    await callback.answer("Пропущено")
    await callback.message.answer(
        "⏭ <i>Анкета пропущена. Ты всегда можешь продолжить поиск в меню «🔍 Смотреть анкеты».</i>",
        parse_mode="HTML",
    )


# ─── Обработка свайпов (Callback) ─────────────────────────────
@router.callback_query(F.data.startswith("swipe:"))
async def swipe_callback(callback: CallbackQuery, state: FSMContext, user: User, db: AsyncSession):
    parts = callback.data.split(":")
    action_str = parts[1]

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
        # Если лайк или суперлайк (не скип) — отправляем красивое уведомление с анкетой
        if action in (SwipeAction.like, SwipeAction.superlike):
            try:
                await send_like_notification(
                    bot=callback.bot,
                    target_user_id=target_id,
                    from_user=user,
                    action=action,
                    db=db,
                )
            except Exception as e:
                logger.warning(f"Failed to send like notification: {e}")

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

    target_name = target.profile.name if target.profile else "Студент"
    target_username = f"@{target.tg_username}" if target.tg_username else "(нет username)"
    my_name = user.profile.name if user.profile else "Студент"
    my_username = f"@{user.tg_username}" if user.tg_username else "(нет username)"

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
            reply_markup=match_keyboard(target_username),
        )
        try:
            await message.bot.send_message(
                target_id,
                f"🎉 <b>Мэтч!</b>\n\n"
                f"<b>{html.escape(my_name)}</b> тоже заинтересован(а) в тебе!\n"
                f"Его/её Telegram: <b>{my_username}</b>",
                parse_mode="HTML",
                reply_markup=match_keyboard(my_username),
            )
        except Exception:
            pass
    else:
        # Отправляем карточку с прикреплённым письмом и кнопками
        try:
            await send_like_notification(
                bot=message.bot,
                target_user_id=target_id,
                from_user=user,
                action=SwipeAction.like,
                letter_text=text,
                db=db,
            )
        except Exception as e:
            logger.warning(f"Failed to send letter notification: {e}")

        await message.answer(
            f"✅ <b>Письмо отправлено для {html.escape(target_name)}!</b>",
            parse_mode="HTML",
        )

    # Автоматически отправляем следующую анкету после отправки письма!
    await send_next_card(message.bot, message.chat.id, user, db)
