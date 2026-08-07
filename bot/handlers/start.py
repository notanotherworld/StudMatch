"""
Хэндлер /start:
1. Показ соглашения о персональных данных
2. После согласия — переход к email-верификации
"""
from aiogram import Router, F
from aiogram.filters import CommandStart, CommandObject, Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession

from bot.states.fsm import ConsentState, AuthState
from bot.keyboards.swipe import consent_keyboard, main_menu_keyboard
from database.crud import set_user_consent, get_user, add_superlikes
from database.models import User

router = Router()

WELCOME_TEXT = """Привет! Это StudMatch 🪢

Здесь ты найдёшь:

🔥 Соратников для кейс-чемпионатов и хакатонов
🤝 Друзей по интересам
❤️ Любовь (да, здесь такое тоже случается)

Набирай баллы, поднимайся в топ и становись видимым для лучших компаний. Или просто покажи миру свою уникальность!

Всё начинается с одной анкеты.
Сначала подтверди, что ты студент, это займёт 1 минуту.

Готов?🧨"""

CONSENT_TEXT = """📋 <b>Соглашение об обработке персональных данных</b>

Для верификации статуса студента и работы сервиса мы обрабатываем:
— Имя, курс, направление и анкетные данные
— Корпоративный email университета
— Документы для верификации рейтингов

🔒 Данные надёжно защищены (в соответствии с ФЗ-152) и не передаются третьим лицам.

Нажимая <b>«Принимаю»</b>, ты соглашаешься с обработкой персональных данных."""


from aiogram.filters import CommandObject, CommandStart

@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject, state: FSMContext, user: User, db: AsyncSession):
    await state.clear()

    # Обработка реферальной ссылки (start=ref_123456)
    if command.args and command.args.startswith("ref_") and not user.referrer_id:
        try:
            ref_id = int(command.args.split("ref_")[1])
            if ref_id != user.id:
                # Проверяем существование реферера в БД (#9)
                referrer = await get_user(db, ref_id)
                if referrer:
                    user.referrer_id = ref_id
                    await db.commit()
        except Exception:
            pass

    # Сообщение #1 — Приветственное вступление
    await message.answer(WELCOME_TEXT)

    # Уже дал согласие?
    if user.consent_given:
        await _after_consent(message, state, user, db)
        return

    # Сообщение #2 — Соглашение с кнопкой "Принимаю"
    await state.set_state(ConsentState.waiting_consent)
    await message.answer(CONSENT_TEXT, parse_mode="HTML", reply_markup=consent_keyboard())


@router.callback_query(F.data == "consent:accept", ConsentState.waiting_consent)
async def consent_accepted(callback: CallbackQuery, state: FSMContext, user: User, db: AsyncSession):
    await set_user_consent(db, user.id)
    user.consent_given = True

    # Награждаем реферера +1 суперлайком — только один раз (#10)
    if user.referrer_id and not user.referral_rewarded:
        await add_superlikes(db, user.referrer_id, 1)
        user.referral_rewarded = True
        await db.commit()
        try:
            await callback.bot.send_message(
                user.referrer_id,
                "🎉 <b>Твой друг зарегистрировался в СтудМэч!</b>\n\n"
                "Тебе начислен <b>+1 ⭐️ Суперлайк</b> за приглашение!",
                parse_mode="HTML",
            )
        except Exception:
            pass

    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer("✅ Соглашение принято!")
    await _after_consent(callback.message, state, user, db)


@router.callback_query(F.data == "consent:decline", ConsentState.waiting_consent)
async def consent_declined(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer()
    await callback.message.answer(
        "😔 Без принятия соглашения использование СтудМэч невозможно.\n"
        "Напиши /start чтобы попробовать снова."
    )
    await state.clear()


async def _after_consent(message: Message, state: FSMContext, user: User, db: AsyncSession):
    """Логика после согласия: email верификация или главное меню."""
    if not user.email_verified:
        await state.set_state(AuthState.waiting_email)
        await message.answer(
            "📧 <b>Верификация студента</b>\n\n"
            "Введи свой корпоративный email университета.\n"
            "Например: <code>ivanov@rudn.ru</code>",
            parse_mode="HTML",
        )
    elif not user.profile or not user.profile.is_complete:
        from bot.handlers.profile import start_profile_creation
        await start_profile_creation(message, state)
    else:
        await message.answer(
            f"👋 С возвращением, <b>{user.profile.name}</b>!\n"
            "Выбери раздел:",
            parse_mode="HTML",
            reply_markup=main_menu_keyboard(),
        )


@router.message(Command("menu"))
async def cmd_menu(message: Message, user: User):
    if user.profile and user.profile.is_complete:
        await message.answer(
            "📋 <b>Главное меню:</b>",
            parse_mode="HTML",
            reply_markup=main_menu_keyboard(),
        )
    else:
        await message.answer("❌ Сначала заполни анкету. Напиши /start")
