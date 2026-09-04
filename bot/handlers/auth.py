"""
Email-верификация: ввод корп. email → отправка кода → подтверждение.
Защиты: rate limiting (60s cooldown), защита от перебора брутфорсом (макс. 5 попыток).
"""
import redis.asyncio as aioredis
from aiogram import Router, F
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings
from bot.states.fsm import AuthState
from bot.utils.email import send_verification_code
from database.crud import (
    find_university_by_email, create_email_token,
    verify_email_token, get_or_create_profile,
)
from database.models import User
from database.models import User as UserModel

router = Router()

_redis: aioredis.Redis | None = None


def _get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis


@router.message(AuthState.waiting_email)
async def process_email(message: Message, state: FSMContext, user: User, db: AsyncSession):
    if not message.text:
        await message.answer("⚠️ Пожалуйста, отправь свой email текстом (например: <code>ivanov@rudn.ru</code>).", parse_mode="HTML")
        return
    email = message.text.strip().lower()

    # Базовая проверка формата
    if "@" not in email or "." not in email.split("@")[-1]:
        await message.answer(
            "❌ Неверный формат email. Попробуй ещё раз.\n"
            "Пример: <code>ivanov@rudn.ru</code>",
            parse_mode="HTML",
        )
        return

    # Защита от спама отправкой (60 сек кулдаун)
    r = _get_redis()
    cooldown_key = f"email_cooldown:{user.id}"
    if await r.exists(cooldown_key):
        ttl = await r.ttl(cooldown_key)
        await message.answer(
            f"⏳ Код уже был отправлен на почту.\n"
            f"Повторная отправка возможна через {ttl} сек.",
        )
        return

    # Ищем вуз по домену
    university = await find_university_by_email(db, email)
    if not university:
        await message.answer(
            "❌ Этот email-домен не зарегистрирован в СтудМэч.\n\n"
            "Сейчас поддерживается:\n• РУДН (@rudn.ru, @pfur.ru)\n\n"
            "Если твой вуз не в списке — скоро мы его добавим 🙏"
        )
        return

    # Сохраняем email и вуз в БД
    await db.execute(
        update(UserModel)
        .where(UserModel.id == user.id)
        .values(email=email, university_id=university.id)
    )
    await db.commit()

    # Создаём и отправляем код
    code = await create_email_token(db, user.id)

    try:
        await send_verification_code(email, code)
    except Exception:
        await message.answer(
            "⚠️ Не удалось отправить письмо. Проверь email и попробуй снова."
        )
        return

    # Устанавливаем кулдаун 60 секунд на отправку и сбрасываем попытки брутфорса
    await r.set(cooldown_key, "1", ex=60)
    await r.delete(f"email_attempts:{user.id}")

    await state.set_state(AuthState.waiting_code)
    await state.update_data(email=email, university_name=university.name)

    await message.answer(
        f"📨 Код отправлен на <code>{email}</code>\n\n"
        f"Введи 6-значный код из письма. Код действителен <b>15 минут</b>.",
        parse_mode="HTML",
    )


@router.message(AuthState.waiting_code)
async def process_code(message: Message, state: FSMContext, user: User, db: AsyncSession):
    if not message.text:
        await message.answer("⚠️ Пожалуйста, введи 6-значный код из письма.")
        return
    code = message.text.strip()

    if not code.isdigit() or len(code) != 6:
        await message.answer("❌ Код должен состоять из 6 цифр. Попробуй ещё раз.")
        return

    # Защита от брутфорса кода (макс. 5 попыток)
    r = _get_redis()
    attempts_key = f"email_attempts:{user.id}"
    attempts = int(await r.get(attempts_key) or 0)

    if attempts >= 5:
        await message.answer(
            "❌ Вы превысили лимит попыток ввода (максимум 5).\n"
            "Код заблокирован. Напишите /start чтобы запросить новый код."
        )
        return

    is_valid = await verify_email_token(db, user.id, code)

    if not is_valid:
        attempts += 1
        await r.set(attempts_key, attempts, ex=900)
        remaining = 5 - attempts
        if remaining > 0:
            await message.answer(
                f"❌ Неверный или истёкший код.\n"
                f"Осталось попыток: <b>{remaining}</b>",
                parse_mode="HTML",
            )
        else:
            await message.answer(
                "❌ Лимит попыток исчерпан. Напишите /start чтобы заново получить код."
            )
        return

    # При успешной верификации удаляем счетчик попыток
    await r.delete(attempts_key)
    await r.delete(f"email_cooldown:{user.id}")

    data = await state.get_data()
    university_name = data.get("university_name", "университете")

    # Награждаем пользователя за верификацию: +100 баллов рейтинга и +3 суперлайка
    from database.crud import add_superlikes, get_profile
    await add_superlikes(db, user.id, 3)

    prof = await get_profile(db, user.id)
    if prof:
        prof.rating_score = (prof.rating_score or 0.0) + 100.0
        await db.commit()

    await state.clear()

    if prof and prof.is_complete:
        from bot.keyboards.swipe import main_menu_keyboard
        await message.answer(
            f"🎉 <b>Студенческий статус успешно подтверждён!</b>\n\n"
            f"🏛 ВУЗ: <b>{university_name}</b>\n"
            f"В твоей анкете появился бейдж <b>[ 🎓 Верифицирован ]</b>\n\n"
            f"🎁 <b>Твоя награда:</b>\n"
            f"• <b>+100 баллов</b> к рейтингу в Зале славы ⭐\n"
            f"• <b>+3 ⭐️ Суперлайка</b> на баланс\n\n"
            f"Твоя анкета теперь получает приоритет при поиске и показывается выше! 🚀",
            parse_mode="HTML",
            reply_markup=main_menu_keyboard(),
        )
    else:
        await message.answer(
            f"✅ <b>Верификация пройдена!</b>\n\n"
            f"Ты подтверждён как студент <b>{university_name}</b>.\n"
            f"Тебе начислено <b>+3 ⭐️ Суперлайка</b> и <b>+100 баллов</b> рейтинга!\n\n"
            f"Теперь давай заполним твой профиль 📋",
            parse_mode="HTML",
        )
        from bot.handlers.profile import start_profile_creation
        await start_profile_creation(message, state)
