"""FSM состояния для всех шагов бота."""
from aiogram.fsm.state import State, StatesGroup


class ConsentState(StatesGroup):
    waiting_consent = State()


class AuthState(StatesGroup):
    waiting_email = State()
    waiting_code = State()


class ProfileState(StatesGroup):
    waiting_name = State()        # Вопрос 1: Имя
    waiting_age = State()         # Вопрос 2: Возраст
    waiting_year = State()        # Вопрос 3: Курс
    waiting_major = State()       # Вопрос 4: Факультет
    waiting_interests = State()   # Вопрос 5: Интересы
    waiting_custom_interest = State() # Кастомный интерес
    waiting_goal = State()        # Вопрос 6: О себе / цель
    waiting_gender = State()         # Пол
    waiting_target_gender = State()  # Предпочтение по полу
    waiting_photo = State()          # Фото


class CareerProfileState(StatesGroup):
    waiting_career_skills = State()
    waiting_career_custom_skills = State()
    waiting_career_goal = State()
    waiting_career_portfolio = State()
    waiting_career_work_format = State()
    waiting_career_photo = State()


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


class FilterState(StatesGroup):
    """Настройка фильтров поиска."""
    waiting_custom_age_range = State()
    waiting_custom_major = State()


class PromoState(StatesGroup):
    """Ввод промокода."""
    waiting_promo_code = State()

