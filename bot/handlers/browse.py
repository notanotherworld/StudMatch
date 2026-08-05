"""
Свайп-интерфейс: топ-6 студентов (3+3), лайк/суперлайк/скип, мэтчи.
"""
import html
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from sqlalchemy.orm import selectinload

from bot.keyboards.swipe import (
    swipe_card_keyboard, top_navigation_keyboard,
    profile_open_keyboard, main_menu_keyboard, letter_received_keyboard,
)
from bot.states.fsm import LetterState
from database.crud import get_top_profiles, create_swipe, get_user, deduct_superlike
from database.models import User, Profile, InterestTag, SwipeAction, ModeEnum, Swipe

router = Router()

# Кол-во профилей на страницу
PAGE_SIZE = 3


async def _build_profile_caption(
    profile: Profile, tags_map: dict[int, InterestTag]
) -> str:
    """Формируем текст карточки студента (tags_map уже загружен batch-запросом)."""
    tags_text = ""
    if profile.interest_ids:
        tags = [tags_map[tid] for tid in profile.interest_ids if tid in tags_map]
        tags_text = " ".join(f"{t.emoji}{t.name}" for t in tags)

    # Кастомные интересы
    if profile.custom_interests:
        custom = html.escape(profile.custom_interests)
        tags_text += f"\n✍️ {custom}" if tags_text else f"✍️ {custom}"

    user_mode = getattr(profile.user, "mode", None)
    mode_label = "🎯 Карьера" if (user_mode and user_mode == ModeEnum.career) else "❤️ Знакомства"
    rating = f"⭐ {profile.rating_score:.0f} б." if profile.rating_score > 0 else ""

    name = html.escape(profile.name or "")
    major = html.escape(profile.major or "")
    goal = html.escape(profile.goal or "")

    return (
        f"<b>{name}</b>, {profile.year} курс\n"
        f"📚 {major}\n"
        f"{mode_label}  {rating}\n\n"
        f"💬 <i>{goal}</i>\n\n"
        f"{tags_text}"
    )


async def _send_top_page(
    message: Message,
    profiles: list,
    page: int,
    total_pages: int,
    user_id: int,
    db: AsyncSession,
    edit: bool = False,
) -> None:
    """Отправить страницу топа (3 карточки с навигацией)."""
    start = (page - 1) * PAGE_SIZE
    page_profiles = profiles[start: start + PAGE_SIZE]

    if not page_profiles:
        await message.answer("Нет студентов для отображения на этой странице.")
        return

    # Batch-загрузка тегов для всех профилей на странице (#6)
    all_tag_ids = set()
    for p in page_profiles:
        if p.interest_ids:
            all_tag_ids.update(p.interest_ids)

    tags_map: dict[int, InterestTag] = {}
    if all_tag_ids:
        result = await db.execute(
            select(InterestTag).where(InterestTag.id.in_(all_tag_ids))
        )
        for tag in result.scalars().all():
            tags_map[tag.id] = tag

    for i, profile in enumerate(page_profiles):
        caption = await _build_profile_caption(profile, tags_map)
        pos = start + i + 1  # позиция в общем топе

        full_caption = f"<b>#{pos} в топе</b>\n\n{caption}"

        if profile.avatar_file_id:
            await message.answer_photo(
                photo=profile.avatar_file_id,
                caption=full_caption,
                parse_mode="HTML",
                reply_markup=swipe_card_keyboard(profile.user_id),
            )
        else:
            await message.answer(
                full_caption,
                parse_mode="HTML",
                reply_markup=swipe_card_keyboard(profile.user_id),
            )

    # Навигация страниц
    nav_text = f"📄 Страница {page}/{total_pages}"
    await message.answer(nav_text, reply_markup=top_navigation_keyboard(page, total_pages))


@router.message(F.text == "🏆 Топ студентов")
async def show_top(message: Message, user: User, db: AsyncSession, state: FSMContext):
    if not user.email_verified:
        await message.answer("❌ Сначала пройди верификацию email. Напиши /start")
        return
    if not user.profile or not user.profile.is_complete:
        await message.answer("❌ Сначала заполни анкету. Напиши /start")
        return

    profiles = await get_top_profiles(db, viewer_id=user.id, mode=user.mode, limit=6)

    if not profiles:
        await message.answer(
            "😔 Пока нет студентов для отображения.\n"
            "Загляни позже — список обновляется!"
        )
        return

    total_pages = 2 if len(profiles) > PAGE_SIZE else 1
    await state.update_data(top_profile_ids=[p.user_id for p in profiles])

    mode_label = "🎯 Карьера" if user.mode == ModeEnum.career else "❤️ Знакомства"
    await message.answer(
        f"🏆 <b> СТУДЕНТОВ</b> · {mode_label}",
        parse_mode="HTML",
    )
    await _send_top_page(message, profiles, page=1, total_pages=total_pages, user_id=user.id, db=db)


@router.callback_query(F.data.startswith("top:page:"))
async def navigate_top(callback: CallbackQuery, state: FSMContext, user: User, db: AsyncSession):
    page = int(callback.data.split(":")[-1])
    await callback.answer()

    data = await state.get_data()
    profile_ids = data.get("top_profile_ids", [])

    if not profile_ids:
        await callback.message.answer("Список устарел. Обнови топ ▶️ Топ студентов")
        return

    # Batch-загрузка всех профилей одним запросом (#5)
    result = await db.execute(
        select(Profile)
        .options(selectinload(Profile.user))
        .where(Profile.user_id.in_(profile_ids))
    )
    profile_map = {p.user_id: p for p in result.scalars().all()}
    # Восстанавливаем исходный порядок
    profiles = [profile_map[uid] for uid in profile_ids if uid in profile_map]

    total_pages = 2 if len(profiles) > PAGE_SIZE else 1
    await _send_top_page(callback.message, profiles, page=page, total_pages=total_pages, user_id=user.id, db=db)


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


# ─── Свайп-действия ───────────────────────────────────────────
@router.callback_query(F.data.startswith("swipe:"))
async def handle_swipe(callback: CallbackQuery, user: User, db: AsyncSession):
    parts = callback.data.split(":")
    action_str = parts[1]
    target_id_str = parts[2]
    target_id = int(target_id_str)

    if action_str == "superlike":
        # Проверяем баланс суперлайков
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
        # Уведомляем цель о суперлайке
        target = await get_user(db, target_id)
        if target:
            try:
                await callback.bot.send_message(
                    target_id,
                    "⭐ <b>Суперлайк!</b>\n\n"
                    "Кто-то очень заинтересован тобой! "
                    "Посмотри, кто в топе — твоя анкета покажется им первой!",
                    parse_mode="HTML",
                )
            except Exception:
                pass  # Пользователь мог заблокировать бота

    if is_match:
        # Получаем данные обоих
        target = await get_user(db, target_id)
        target_name = target.profile.name if target and target.profile else "Студент"
        target_username = f"@{target.tg_username}" if target and target.tg_username else "(нет username)"

        my_name = user.profile.name if user.profile else "Студент"
        my_username = f"@{user.tg_username}" if user.tg_username else "(нет username)"

        # Уведомляем инициатора
        await callback.message.answer(
            f"🎉 <b>Мэтч!</b>\n\n"
            f"<b>{html.escape(target_name)}</b> тоже заинтересован(а) в тебе!\n"
            f"Его/её Telegram: <b>{target_username}</b>",
            parse_mode="HTML",
        )

        # Уведомляем вторую сторону
        try:
            await callback.bot.send_message(
                target_id,
                f"🎉 <b>Мэтч!</b>\n\n"
                f"<b>{html.escape(my_name)}</b> тоже заинтересован(а) в тебе!\n"
                f"Его/её Telegram: <b>{my_username}</b>",
                parse_mode="HTML",
            )
        except Exception:
            pass

        await callback.answer("🎉 Мэтч!")
    else:
        icons = {"like": "❤️", "superlike": "⭐", "skip": "⏭"}
        await callback.answer(icons.get(action_str, "✅"))

    # Убираем кнопки свайпа с карточки
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass


# ─── Отправка письма с анкеты (как в Дайвинчике) ───────────────────────────
@router.callback_query(F.data.startswith("swipe:message:"))
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
        f"Введи текст сообщения (до 500 символов):\n"
        f"<i>Пример: Привет! Тоже участвую в хакатонах, давай объединимся 🚀</i>",
        parse_mode="HTML",
        reply_markup=builder.as_markup(),
    )


@router.callback_query(F.data == "letter:cancel", LetterState.waiting_text)
async def cancel_letter(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer("Отменено")
    try:
        await callback.message.delete()
    except Exception:
        await callback.message.answer("Отправка письма отменена.")


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

    # Проверяем, есть ли уже свайп от этого пользователя (#11)
    existing_swipe = await db.execute(
        select(Swipe).where(
            and_(Swipe.from_user_id == user.id, Swipe.to_user_id == target_id)
        )
    )
    has_existing_swipe = existing_swipe.scalar_one_or_none() is not None

    is_match = False
    if not has_existing_swipe:
        # Создаём свайп-лайк с комментарием только если ещё не свайпали
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
        # Отправляем письмо получателю в Telegram (всегда, даже если свайп уже был)
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
            reply_markup=main_menu_keyboard(),
        )
