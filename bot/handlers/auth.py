"""
Email-верификация: ввод корп. email → отправка кода → подтверждение.
"""
from aiogram import Router, F
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession

from bot.states.fsm import AuthState
from bot.utils.email import send_verification_code
from database.crud import (
    find_university_by_email, create_email_token,
    verify_email_token, get_or_create_profile,
)
from database.models import User
from sqlalchemy import update
from database.session import AsyncSessionLocal
from database.models import User as UserModel

router = Router()


@router.message(AuthState.waiting_email)
async def process_email(message: Message, state: FSMContext, user: User, db: AsyncSession):
    email = message.text.strip().lower()

    # Базовая проверка формата
    if "@" not in email or "." not in email.split("@")[-1]:
        await message.answer(
            "❌ Неверный формат email. Попробуй ещё раз.\n"
            "Пример: <code>ivanov@rudn.ru</code>",
            parse_mode="HTML",
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
    async with AsyncSessionLocal() as s:
        await s.execute(
            update(UserModel)
            .where(UserModel.id == user.id)
            .values(email=email, university_id=university.id)
        )
        await s.commit()

    # Создаём и отправляем код
    code = await create_email_token(db, user.id)

    try:
        await send_verification_code(email, code)
    except Exception as e:
        await message.answer(
            "⚠️ Не удалось отправить письмо. Проверь email и попробуй снова."
        )
        return

    await state.set_state(AuthState.waiting_code)
    await state.update_data(email=email, university_name=university.name)

    await message.answer(
        f"📨 Код отправлен на <code>{email}</code>\n\n"
        f"Введи 6-значный код из письма. Код действителен <b>15 минут</b>.",
        parse_mode="HTML",
    )


@router.message(AuthState.waiting_code)
async def process_code(message: Message, state: FSMContext, user: User, db: AsyncSession):
    code = message.text.strip()

    if not code.isdigit() or len(code) != 6:
        await message.answer("❌ Код должен состоять из 6 цифр. Попробуй ещё раз.")
        return

    is_valid = await verify_email_token(db, user.id, code)

    if not is_valid:
        await message.answer(
            "❌ Неверный или истёкший код.\n"
            "Напиши /start чтобы получить новый."
        )
        return

    data = await state.get_data()
    university_name = data.get("university_name", "твоём университете")

    await state.clear()

    await message.answer(
        f"✅ <b>Верификация пройдена!</b>\n\n"
        f"Ты подтверждён как студент <b>{university_name}</b>.\n\n"
        f"Теперь давай заполним твой профиль 📋",
        parse_mode="HTML",
    )

    # Запускаем создание анкеты
    from bot.handlers.profile import start_profile_creation
    await start_profile_creation(message, state)
