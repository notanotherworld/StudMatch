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

    # Награждаем реферера +3 суперлайками — только один раз (#10)
    if user.referrer_id and not user.referral_rewarded:
        await add_superlikes(db, user.referrer_id, 3)
        user.referral_rewarded = True
        await db.commit()
        try:
            await callback.bot.send_message(
                user.referrer_id,
                "🎉 <b>Твой друг зарегистрировался в СтудМэч!</b>\n\n"
                "Тебе начислено <b>+3 ⭐️ Суперлайка</b> за приглашение!",
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


@router.callback_query(F.data == "update:open")
async def update_announcement_open(callback: CallbackQuery, user: User, db: AsyncSession, state: FSMContext):
    """Обработка кнопки «🚀 Открыть СтудМэч» из рассылки об обновлении."""
    await callback.answer()
    if state:
        await state.clear()
    await _after_consent(callback.message, state, user, db)


async def _after_consent(message: Message, state: FSMContext, user: User, db: AsyncSession):
    """Логика после согласия: мгновенный переход к созданию анкеты или главное меню."""
    if not user.profile or not user.profile.is_complete:
        from bot.handlers.profile import start_profile_creation
        await start_profile_creation(message, state)
    else:
        # Обновляем кнопку меню для этого пользователя
        try:
            from aiogram.types import MenuButtonWebApp, WebAppInfo
            from bot.config import settings
            await message.bot.set_chat_menu_button(
                chat_id=message.chat.id,
                menu_button=MenuButtonWebApp(
                    text="🚀 StudMatch App",
                    web_app=WebAppInfo(url=settings.webapp_url),
                )
            )
        except Exception:
            pass

        from bot.keyboards.swipe import webapp_inline_keyboard
        await message.answer(
            f"👋 С возвращением, <b>{user.profile.name}</b>!\n\n"
            "📱 Доступно мобильное приложение StudMatch со свайпами и мэтчами!\n"
            "Нажми на кнопку ниже или в меню, чтобы открыть:",
            parse_mode="HTML",
            reply_markup=webapp_inline_keyboard(),
        )
        await message.answer(
            "📋 Или выбери действие в меню:",
            parse_mode="HTML",
            reply_markup=main_menu_keyboard(),
        )


from aiogram.filters import StateFilter

@router.message(StateFilter("*"), Command("menu"))
async def cmd_menu(message: Message, user: User, state: FSMContext = None):
    if state:
        await state.clear()
    if user.profile and user.profile.is_complete:
        try:
            from aiogram.types import MenuButtonWebApp, WebAppInfo
            from bot.config import settings
            await message.bot.set_chat_menu_button(
                chat_id=message.chat.id,
                menu_button=MenuButtonWebApp(
                    text="🚀 StudMatch App",
                    web_app=WebAppInfo(url=settings.webapp_url),
                )
            )
        except Exception:
            pass

        from bot.keyboards.swipe import webapp_inline_keyboard
        await message.answer(
            "📱 <b>StudMatch WebApp:</b>\n"
            "Нажми на кнопку, чтобы открыть приложение:",
            parse_mode="HTML",
            reply_markup=webapp_inline_keyboard(),
        )
        await message.answer(
            "📋 <b>Главное меню:</b>",
            parse_mode="HTML",
            reply_markup=main_menu_keyboard(),
        )
    else:
        await message.answer("❌ Сначала заполни анкету. Напиши /start")


@router.message(F.text.in_({"🚀 Открыть StudMatch App", "🚀 Открыть StudMatch", "📱 Открыть приложение", "/app", "/webapp"}))
@router.message(Command("app"))
@router.message(Command("webapp"))
async def cmd_open_webapp(message: Message, user: User):
    """Прямой запуск WebApp по команде или тексту кнопки."""
    from bot.keyboards.swipe import webapp_inline_keyboard
    await message.answer(
        "✨ <b>StudMatch WebApp</b>\n\n"
        "Нажми на кнопку ниже, чтобы открыть приложение со свайпами прямо в Telegram:",
        parse_mode="HTML",
        reply_markup=webapp_inline_keyboard(),
    )



@router.message(Command("health"))
@router.message(Command("status"))
async def cmd_health(message: Message, user: User, db: AsyncSession, state: FSMContext = None):
    """Диагностика и проверка всех систем бота."""
    if state:
        await state.clear()

    wait_msg = await message.answer("⏳ <i>Запуск полной диагностики системы...</i>", parse_mode="HTML")

    from bot.services.health_checker import run_full_diagnostics
    diag = await run_full_diagnostics(message.bot, db=db)

    lines = []
    for s in diag["services"]:
        icon = "✅" if s["status"] == "OK" else ("⚠️" if s["status"] == "WARN" else "❌")
        lat = f" <code>({s['latency_ms']} ms)</code>" if s["latency_ms"] is not None else ""
        lines.append(f"{icon} <b>{s['name']}</b>{lat}\n└ {s['details']}")

    overall = "✅ ВСЕ СЕРВИСЫ В ПОРЯДКЕ" if diag["overall_status"] == "OK" else ("⚠️ ЕСТЬ ЗАМЕЧАНИЯ" if diag["overall_status"] == "WARN" else "🚨 СБОЙ В РАБОТЕ")

    report_text = (
        f"🏥 <b>СТАТУС И ДИАГНОСТИКА СИСТЕМЫ</b>\n"
        f"Время: <code>{diag['timestamp']}</code>\n"
        f"Статус: <b>{overall}</b> (время проверки: {diag['total_time_ms']} ms)\n\n" +
        "\n\n".join(lines)
    )

    try:
        await wait_msg.delete()
    except Exception:
        pass

    await message.answer(report_text, parse_mode="HTML")
