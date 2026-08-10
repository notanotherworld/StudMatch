"""
Загрузка достижений студентом: тип → название → документ → MinIO.
"""
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from bot.states.fsm import AchievementState
from bot.keyboards.swipe import achievement_type_keyboard
from bot.utils.minio_client import upload_document
from database.models import User, Achievement, AchievementType
from database.crud import ACHIEVEMENT_SCORES

import html
from database.crud import set_user_mode
from database.models import User, Achievement, AchievementType, Profile

router = Router()


@router.message(F.text.in_({"🏆 Зал славы", "Зал славы", "🏆 Топ студентов", "/halloffame"}))
@router.callback_query(F.data.startswith("top:page"))
async def show_hall_of_fame(event, user: User, db: AsyncSession):
    """Показать Зал славы (расширен до 12 человек)."""
    result = await db.execute(
        select(Profile)
        .options(selectinload(Profile.user))
        .where(Profile.is_complete == True, Profile.is_visible == True)
        .order_by(Profile.rating_score.desc())
        .limit(12)  # Расширено до 12 человек (#2)
    )
    profiles = list(result.scalars().all())

    lines = []
    for idx, p in enumerate(profiles, start=1):
        name = html.escape(p.name or "Студент")
        score = f"{p.rating_score:.0f}"
        medal = "🥇" if idx == 1 else ("🥈" if idx == 2 else ("🥉" if idx == 3 else f"{idx}."))
        lines.append(f"{medal} <b>{name}</b> ({p.year} курс) — ⭐ <b>{score}</b> б.")

    text_header = "🏆 <b>Зал славы СтудМэч (Топ-12)</b>\n\n"
    text_body = "\n".join(lines) if lines else "<i>Зал славы пока пуст. Будь первым!</i>"
    text_footer = (
        "\n\n💼 <i>Компании видят топ-50. Чем выше ты в этом списке, тем чаще они пишут тебе первыми. Все получится 🤲🏻</i>"
    )
    text = text_header + text_body + text_footer

    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Добавить достижение", callback_data="achievement:add")
    builder.button(text="🔍 Смотреть анкеты", callback_data="top:swipe_next")
    builder.adjust(1)

    if isinstance(event, CallbackQuery):
        await event.answer()
        await event.message.answer(text, parse_mode="HTML", reply_markup=builder.as_markup())
    else:
        await event.answer(text, parse_mode="HTML", reply_markup=builder.as_markup())

# Единый словарь лейблов для всех типов достижений (#8, #17)
ACHIEVEMENT_LABELS = {
    # Новые типы (текущие)
    "case_participant": "💼 Участие в хакатоне / кейс-чемпионате",
    "place_3": "🥉 Призовое 3-е место",
    "place_2": "🥈 Призовое 2-е место",
    "place_1": "🥇 Победа / 1-е место",
    "volunteer": "🤝 Участие в волонтёрском проекте",
    "internship": "👔 Прохождение стажировки",
    "forum_attender": "🏛 Посещение форума / конференции",
    "forum_speaker": "🎤 Выступление на форуме / конференции",
    # Дополнительные / устаревшие типы
    "gpa": "📊 GPA / Успеваемость",
    "competition": "🥇 Соревнования",
    "case": "💼 Кейс-чемпионат",
    "olympiad": "🏆 Победа в олимпиаде",
    "diploma": "🎓 Диплом с отличием",
    "publication": "📝 Публикация",
    "participation": "🎯 Участие",
}


@router.callback_query(F.data == "settings:achievements")
async def show_achievements(callback: CallbackQuery, user: User, db: AsyncSession):
    """Показать текущие достижения и кнопку добавить."""
    result = await db.execute(
        select(Achievement).where(Achievement.user_id == user.id).order_by(Achievement.created_at.desc())
    )
    achievements = result.scalars().all()

    if achievements:
        lines = []
        for a in achievements:
            status_icon = {"pending": "⏳", "approved": "✅", "rejected": "❌"}.get(a.verified.value, "?")
            label = ACHIEVEMENT_LABELS.get(a.type.value, a.type.value)
            lines.append(f"{status_icon} {label}: {a.title}")
        text = "🏆 <b>Мои достижения:</b>\n\n" + "\n".join(lines)
    else:
        text = "🏆 <b>Достижений пока нет.</b>\n\nДобавь первое!"

    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Добавить достижение", callback_data="achievement:add")
    builder.adjust(1)

    await callback.answer()
    await callback.message.answer(text, parse_mode="HTML", reply_markup=builder.as_markup())


@router.callback_query(F.data == "achievement:add")
async def start_achievement(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(AchievementState.choosing_type)
    await callback.message.answer(
        "📋 <b>Добавление достижения</b>\n\n"
        "Выбери тип достижения:",
        parse_mode="HTML",
        reply_markup=achievement_type_keyboard(),
    )


@router.callback_query(F.data.startswith("ach_type:"), AchievementState.choosing_type)
async def process_type(callback: CallbackQuery, state: FSMContext):
    ach_type = callback.data.split(":")[1]
    await state.update_data(ach_type=ach_type)
    await state.set_state(AchievementState.waiting_title)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer()
    await callback.message.answer(
        f"✅ Тип: <b>{ACHIEVEMENT_LABELS.get(ach_type, ach_type)}</b>\n\n"
        "Введи название достижения:\n"
        "<i>(Например: Победа в олимпиаде по программированию ИТМО 2024)</i>",
        parse_mode="HTML",
    )


@router.message(AchievementState.waiting_title)
async def process_title(message: Message, state: FSMContext):
    title = message.text.strip()
    if len(title) < 5 or len(title) > 300:
        await message.answer("Название должно быть от 5 до 300 символов.")
        return

    await state.update_data(title=title)
    await state.set_state(AchievementState.waiting_document)
    await message.answer(
        "📎 <b>Загрузи подтверждающий документ</b>\n\n"
        "Отправь файл (PDF, JPG, PNG) — диплом, сертификат, справку.\n"
        "<i>Документы проверяются модератором в течение 1–3 дней.</i>",
        parse_mode="HTML",
    )


MAX_FILE_SIZE = 15 * 1024 * 1024  # 15 МБ
ALLOWED_EXTENSIONS = {"pdf", "jpg", "jpeg", "png"}


@router.message(AchievementState.waiting_document, F.document | F.photo)
async def process_document(message: Message, state: FSMContext, user: User, db: AsyncSession):
    # Получаем файл
    if message.document:
        file_obj = message.document
        filename = file_obj.file_name or "document.pdf"
    else:
        file_obj = message.photo[-1]
        filename = "photo.jpg"

    # 1. Защита от DoS / OOM: проверка размера файла (макс 15 МБ)
    if file_obj.file_size and file_obj.file_size > MAX_FILE_SIZE:
        await message.answer("❌ Файл слишком большой. Максимальный размер документа — 15 МБ.")
        return

    # 2. Защита от Unrestricted File Upload: проверка расширения
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        await message.answer(
            "❌ Недопустимый формат файла.\n"
            "Разрешены только документы <b>PDF</b> и изображения <b>JPG, PNG</b>.",
            parse_mode="HTML",
        )
        return

    # Скачиваем файл
    file = await message.bot.get_file(file_obj.file_id)
    file_bytes_io = await message.bot.download_file(file.file_path)
    file_bytes = file_bytes_io.read()

    # Загружаем в MinIO
    try:
        doc_url = await upload_document(file_bytes, filename, user.id)
    except Exception:
        await message.answer("⚠️ Ошибка загрузки файла. Попробуй ещё раз.")
        return

    data = await state.get_data()
    ach_type = AchievementType(data["ach_type"])
    score = ACHIEVEMENT_SCORES.get(data["ach_type"], 5.0)

    achievement = Achievement(
        user_id=user.id,
        type=ach_type,
        title=data["title"],
        document_url=doc_url,
        score=score,
    )
    db.add(achievement)
    await db.commit()

    await state.clear()

    await message.answer(
        "✅ <b>Достижение отправлено на проверку!</b>\n\n"
        f"📋 <b>{ACHIEVEMENT_LABELS.get(data['ach_type'], '')}</b>\n"
        f"🏷 {data['title']}\n\n"
        "⏳ Модератор проверит документ в течение 1–3 дней.\n"
        "После подтверждения очки будут начислены в рейтинг автоматически.",
        parse_mode="HTML",
    )
