"""FSM состояния для всех шагов бота."""
from aiogram.fsm.state import State, StatesGroup


class ConsentState(StatesGroup):
    waiting_consent = State()


class AuthState(StatesGroup):
    waiting_email = State()
    waiting_code = State()


class ProfileState(StatesGroup):
    waiting_name = State()        # Вопрос 1
    waiting_year = State()        # Вопрос 2
    waiting_major = State()       # Вопрос 3
    waiting_interests = State()   # Вопрос 4
    waiting_custom_interest = State() # Кастомный интерес
    waiting_goal = State()        # Вопрос 5
    waiting_gender = State()         # Пол
    waiting_target_gender = State()  # Предпочтение по полу
    waiting_photo = State()          # Фото


class ModeState(StatesGroup):
    choosing_mode = State()


class AchievementState(StatesGroup):
    choosing_type = State()
    waiting_title = State()
    waiting_document = State()


class AdminMessageState(StatesGroup):
    """Для отправки сообщения пользователю из Telegram (модератор)."""
    waiting_user_id = State()
    waiting_text = State()


class ReportState(StatesGroup):
    """Жалоба на пользователя."""
    choosing_reason = State()


class LetterState(StatesGroup):
    """Отправка сообщения/письма вместе со свайпом (как в Дайвинчике)."""
    waiting_text = State()


class PromoState(StatesGroup):
    """Ввод промокода."""
    waiting_promo_code = State()

