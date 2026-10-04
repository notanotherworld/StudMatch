"""
Обработчик ежедневных стриков («Стипендия»), заданий и онбординг-ачивок.
"""
from datetime import datetime, timezone
import logging
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from bot.keyboards.shop import quests_main_keyboard
from bot.keyboards.swipe import main_menu_keyboard
from bot.services.economy_service import (
    format_credits,
    reward_email_verification,
    reward_profile_completion,
    reward_gallery_upload,
    has_received_reward,
)
from database.crud import (
    get_user,
    claim_daily_streak,
    get_or_create_daily_quests,
    claim_daily_quest,
    STREAK_REWARDS_MAP,
    DEFAULT_DAILY_QUESTS_CONFIG,
)
from database.models import User, Profile

logger = logging.getLogger(__name__)
router = Router()


def _render_streak_bar(streak_days: int) -> str:
    """Визуальная шкала 7-дневного цикла стрика."""
    cycle_day = ((streak_days - 1) % 7) + 1 if streak_days > 0 else 0
    icons = []
    for day in range(1, 8):
        reward = STREAK_REWARDS_MAP.get(day, 10)
        if day < cycle_day:
            icons.append(f"<b>[✅ Д{day}: +{reward}]</b>")
        elif day == cycle_day:
            icons.append(f"<b>[🔥 Д{day}: +{reward}]</b>")
        else:
            if day == 7:
                icons.append(f"[⭐ Д7: +{reward}+⭐️]")
            else:
                icons.append(f"[Д{day}: +{reward}]")
    return " ➔ ".join(icons[:4]) + "\n" + " ➔ ".join(icons[4:])


def _progress_bar(current: int, target: int, length: int = 6) -> str:
    """Генератор простого прогресс-бара [■■■□□□]."""
    if target <= 0:
        return "[■" * length + "]"
    fill = min(length, int((current / target) * length))
    empty = length - fill
    return f"[{'■' * fill}{'□' * empty}]"


@router.message(Command("quests"))
@router.message(Command("streak"))
@router.message(Command("daily"))
async def cmd_quests_main(message: Message, user: User, db: AsyncSession):
    """Экран зачётки, стрика и дейликов."""
    text, keyboard = await _render_quests_main(user, db)
    await message.answer(text, parse_mode="HTML", reply_markup=keyboard)


@router.callback_query(F.data == "quests:main")
async def cb_quests_main(callback: CallbackQuery, user: User, db: AsyncSession):
    text, keyboard = await _render_quests_main(user, db)
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
    await callback.answer()


async def _render_quests_main(user: User, db: AsyncSession):
    u = await get_user(db, user.id) or user
    bal = u.credits_balance or 0
    streak = u.streak_days or 0

    now = datetime.now(timezone.utc)
    today = now.date()

    can_claim_streak = True
    if u.last_streak_date and u.last_streak_date.date() == today:
        can_claim_streak = False

    # Расчет награды за сегодня
    next_streak = streak + 1 if can_claim_streak else streak
    cycle_day = ((next_streak - 1) % 7) + 1 if next_streak > 0 else 1
    today_reward = STREAK_REWARDS_MAP.get(cycle_day, 10)

    # Получаем дейлики
    quests = await get_or_create_daily_quests(db, u.id)
    quest_cfg_map = {c["key"]: c for c in DEFAULT_DAILY_QUESTS_CONFIG}

    streak_visual = _render_streak_bar(streak)
    is_prem = bool(u.is_premium)
    prem_banner = (
        "👑 <b>Премиум-бонус активен: x3 Зачётов за все задания!</b>\n\n"
        if is_prem
        else "💡 <i>С Премиум-подпиской награды за все задания умножаются на 3 (x3 🎓)!</i>\n\n"
    )

    text = (
        f"📋 <b>Студенческая Зачётка и Задания</b>\n\n"
        f"Баланс: <b>{format_credits(bal)}</b>\n"
        f"🔥 Текущая серия (стрик): <b>{streak} дн.</b>\n"
        f"🩺 Справок от врача в запасе: <b>{u.streak_freeze_count or 0} шт.</b>\n\n"
        f"{prem_banner}"
        f"<b>Серия посещений («Стипендия»):</b>\n"
        f"{streak_visual}\n\n"
        f"<b>Ежедневные задания на сегодня:</b>\n"
    )

    for q in quests:
        cfg = quest_cfg_map.get(q.quest_key, {})
        title = cfg.get("title", q.quest_key)
        bar = _progress_bar(q.current_progress, q.target_progress)
        status_icon = "✅" if q.is_claimed else ("🎁 Готово!" if q.current_progress >= q.target_progress else "")
        prem_badge = " [👑 x3]" if is_prem else ""
        text += f"— {title}: {bar} {q.current_progress}/{q.target_progress} (+{q.reward_credits} 🎓{prem_badge}) {status_icon}\n"

    keyboard = quests_main_keyboard(can_claim_streak, today_reward, quests)
    return text, keyboard


@router.callback_query(F.data == "quests:claim_streak")
async def cb_claim_streak(callback: CallbackQuery, user: User, db: AsyncSession):
    """Клейм ежедневной стипендии."""
    success, msg, new_streak, reward = await claim_daily_streak(db, user.id)
    if not success:
        await callback.answer(msg, show_alert=True)
        return

    u = await get_user(db, user.id) or user
    text, keyboard = await _render_quests_main(u, db)
    await callback.message.edit_text(
        f"{msg}\n\n" + text,
        parse_mode="HTML",
        reply_markup=keyboard,
    )
    await callback.answer("Стипендия получена! 🎉")


@router.callback_query(F.data == "quests:streak_done")
async def cb_streak_done(callback: CallbackQuery):
    await callback.answer("Ты уже забрал(а) стипендию за сегодня! Ждём тебя завтра ⏳", show_alert=True)


@router.callback_query(F.data.startswith("quests:claim_daily:"))
async def cb_claim_daily(callback: CallbackQuery, user: User, db: AsyncSession):
    """Клейм награды за выполненный дейлик."""
    quest_key = callback.data.split(":")[2]
    success, msg, reward = await claim_daily_quest(db, user.id, quest_key)

    if not success:
        await callback.answer(msg, show_alert=True)
        return

    u = await get_user(db, user.id) or user
    text, keyboard = await _render_quests_main(u, db)
    await callback.message.edit_text(
        f"{msg}\n\n" + text,
        parse_mode="HTML",
        reply_markup=keyboard,
    )
    await callback.answer("Награда начислена! 🎓")


@router.callback_query(F.data == "quests:onboarding")
async def cb_quests_onboarding(callback: CallbackQuery, user: User, db: AsyncSession):
    """Экран разовых заданий новичка («Зачётка первокурсника»)."""
    u = await get_user(db, user.id) or user
    prof_res = await db.execute(select(Profile).where(Profile.user_id == user.id))
    profile = prof_res.scalar_one_or_none()

    # Проверяем статусы
    has_email = bool(u.email_verified)
    email_claimed = await has_received_reward(db, user.id, "onboarding_email_verified") or await has_received_reward(db, user.id, "perm_quest_onboarding_email")

    is_complete = bool(profile and profile.is_complete)
    profile_claimed = await has_received_reward(db, user.id, "onboarding_profile_complete") or await has_received_reward(db, user.id, "perm_quest_onboarding_profile")

    photos_count = len(profile.photos) if profile and profile.photos else 0
    gallery_claimed = await has_received_reward(db, user.id, "onboarding_gallery_3_photos") or await has_received_reward(db, user.id, "perm_quest_onboarding_gallery")

    is_prem = bool(u.is_premium)
    mult = 3 if is_prem else 1
    email_rew = 40 * mult
    profile_rew = 20 * mult
    gallery_rew = 12 * mult
    prem_notice = " <i>(👑 x3 Премиум)</i>" if is_prem else ""

    builder = InlineKeyboardBuilder()

    text = (
        f"🎒 <b>Зачётка первокурсника (Разовые награды)</b>\n\n"
        f"Выполняй ключевые шаги в StudMatch и получай стартовые «Зачёты» для покупок в магазине:\n\n"
    )

    # 1. Почта
    if email_claimed:
        text += f"✅ <b>Верификация почты вуза</b> (+{email_rew} 🎓{prem_notice}) — Получено\n"
    elif has_email:
        text += f"🎁 <b>Верификация почты вуза</b> (+{email_rew} 🎓{prem_notice}) — Готово к получению!\n"
        builder.button(text=f"🎁 Забрать +{email_rew} 🎓 (Почта)", callback_data="quests:claim_ob:email")
    else:
        text += f"⏳ <b>Верификация почты вуза</b> (+{email_rew} 🎓{prem_notice}) — Подтверди корпоративный email\n"

    # 2. Анкета
    if profile_claimed:
        text += f"✅ <b>Заполнение анкеты на 100%</b> (+{profile_rew} 🎓{prem_notice}) — Получено\n"
    elif is_complete:
        text += f"🎁 <b>Заполнение анкеты на 100%</b> (+{profile_rew} 🎓{prem_notice}) — Готово к получению!\n"
        builder.button(text=f"🎁 Забрать +{profile_rew} 🎓 (Анкета)", callback_data="quests:claim_ob:profile")
    else:
        text += f"⏳ <b>Заполнение анкеты на 100%</b> (+{profile_rew} 🎓{prem_notice}) — Заполни все 5 вопросов анкеты\n"

    # 3. Галерея
    if gallery_claimed:
        text += f"✅ <b>Портфолио из 3+ фото</b> (+{gallery_rew} 🎓{prem_notice}) — Получено\n"
    elif photos_count >= 3:
        text += f"🎁 <b>Портфолио из 3+ фото</b> (+{gallery_rew} 🎓{prem_notice}) — Готово к получению!\n"
        builder.button(text=f"🎁 Забрать +{gallery_rew} 🎓 (Фото)", callback_data="quests:claim_ob:photos")
    else:
        text += f"⏳ <b>Портфолио из 3+ фото</b> (+{gallery_rew} 🎓{prem_notice}) — Загружено: {photos_count}/3 фото\n"

    text += (
        "\n🤝 <b>Приглашение друзей:</b>\n"
        "Отправь реферальную ссылку однокурсникам и получай <b>+50 🎓</b> за каждого студента, а друг получит <b>+30 🎓</b>!"
    )

    builder.button(text="◀️ В Зачётку и дейлики", callback_data="quests:main")
    builder.button(text="🏪 В Магазин", callback_data="shop:main")
    builder.adjust(1)

    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data.startswith("quests:claim_ob:"))
async def cb_claim_onboarding_reward(callback: CallbackQuery, user: User, db: AsyncSession):
    """Выдача награды за онбординг."""
    reward_type = callback.data.split(":")[2]
    u = await get_user(db, user.id) or user
    is_prem = bool(u.is_premium)
    mult = 3 if is_prem else 1

    if reward_type == "email":
        if not u.email_verified:
            await callback.answer("Сначала подтверди университетский email.", show_alert=True)
            return
        success, new_bal = await reward_email_verification(db, user.id)
        if success:
            await callback.answer(f"🎉 +{40 * mult} Зачётов начислено!", show_alert=True)
        else:
            await callback.answer("Награда уже была получена ранее.")

    elif reward_type == "profile":
        prof_res = await db.execute(select(Profile).where(Profile.user_id == user.id))
        profile = prof_res.scalar_one_or_none()
        if not profile or not profile.is_complete:
            await callback.answer("Анкета ещё не заполнена полностью.", show_alert=True)
            return
        success, new_bal = await reward_profile_completion(db, user.id)
        if success:
            await callback.answer(f"🎉 +{20 * mult} Зачётов начислено!", show_alert=True)
        else:
            await callback.answer("Награда уже была получена ранее.")

    elif reward_type == "photos":
        prof_res = await db.execute(select(Profile).where(Profile.user_id == user.id))
        profile = prof_res.scalar_one_or_none()
        count = len(profile.photos) if profile and profile.photos else 0
        if count < 3:
            await callback.answer(f"Загружено фото: {count}/3. Нужно минимум 3.", show_alert=True)
            return
        success, new_bal = await reward_gallery_upload(db, user.id)
        if success:
            await callback.answer(f"🎉 +{12 * mult} Зачётов начислено!", show_alert=True)
        else:
            await callback.answer("Награда уже была получена ранее.")

    # Перерисовываем экран онбординга
    await cb_quests_onboarding(callback, user, db)
