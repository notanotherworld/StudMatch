"""
Клавиатуры для магазина, заданий, стриков и инвентаря.
"""
from typing import List, Optional
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database.models import ShopItem, UserInventoryItem, UserDailyQuest
from database.crud import DEFAULT_DAILY_QUESTS_CONFIG
from bot.config import settings


def shop_main_keyboard(credits_balance: int, streak_days: int) -> InlineKeyboardMarkup:
    """Главное меню магазина."""
    builder = InlineKeyboardBuilder()

    # WebApp кнопка (двухуровневый магазин)
    shop_web_url = f"{settings.webapp_url}?startapp=shop"
    builder.button(text="🛍 Открыть Web-витрину магазина", web_app=WebAppInfo(url=shop_web_url))

    # Категории
    builder.button(text="⚡️ Расходники и бусты", callback_data="shop:cat:consumable")
    builder.button(text="💎 Премиум-подписка", callback_data="shop:cat:subscription")
    builder.button(text="🎨 Рамки и статусы", callback_data="shop:cat:cosmetic")
    builder.button(text="🩺 Защита стрика", callback_data="shop:cat:insurance")

    # Дополнительные разделы
    builder.button(text="📋 Зачётка и задания", callback_data="quests:main")
    builder.button(text="🎒 Мой инвентарь", callback_data="shop:inventory")
    builder.button(text="💳 Пополнить зачёты (₽)", callback_data="shop:deposit")
    builder.button(text="🎁 Ввести промокод", callback_data="settings:enter_promo")
    builder.button(text="◀️ В главное меню", callback_data="shop:back_to_main")

    builder.adjust(1, 2, 2, 2, 1, 1, 1)
    return builder.as_markup()


def shop_category_keyboard(items: List[ShopItem], category: str) -> InlineKeyboardMarkup:
    """Список товаров в выбранной категории."""
    builder = InlineKeyboardBuilder()

    for item in items:
        price_str = f"{item.price_credits} 🎓"
        if item.price_rub:
            price_str += f" / {item.price_rub} ₽"
        btn_text = f"{item.icon} {item.title} — {price_str}"
        builder.button(text=btn_text, callback_data=f"shop:item:{item.code}")

    builder.button(text="◀️ Все разделы магазина", callback_data="shop:main")
    builder.adjust(1)
    return builder.as_markup()


def shop_item_detail_keyboard(item: ShopItem, user_credits: int) -> InlineKeyboardMarkup:
    """Карточка товара с кнопками покупки."""
    builder = InlineKeyboardBuilder()

    can_afford = user_credits >= item.price_credits
    btn_credits_text = f"🎓 Купить за {item.price_credits} 🎓" if can_afford else f"⚠️ Не хватает {item.price_credits - user_credits} 🎓"
    
    if can_afford:
        builder.button(text=btn_credits_text, callback_data=f"shop:buy:{item.code}")
    else:
        builder.button(text=btn_credits_text, callback_data="shop:deposit")

    if item.price_rub:
        builder.button(text=f"💳 Купить за {item.price_rub} ₽", callback_data=f"shop:buy_rub:{item.code}")

    builder.button(text=f"◀️ Назад в «{_category_name(item.category)}»", callback_data=f"shop:cat:{item.category}")
    builder.adjust(1)
    return builder.as_markup()


def _category_name(category: str) -> str:
    names = {
        "consumable": "Расходники",
        "subscription": "Премиум",
        "cosmetic": "Рамки",
        "insurance": "Защита стрика",
    }
    return names.get(category, "Каталог")


def shop_inventory_keyboard(
    inventory_items: List[UserInventoryItem],
    equipped_frame: Optional[str] = None,
) -> InlineKeyboardMarkup:
    """Инвентарь пользователя: рамки, шпоры, справки."""
    builder = InlineKeyboardBuilder()

    frame_items = [it for it in inventory_items if it.item_code.startswith("frame_")]
    for f in frame_items:
        is_on = (f.item_code == equipped_frame)
        status_icon = "✅ Надет" if is_on else "Надеть"
        title = _frame_title(f.item_code)
        act = "unequip" if is_on else "equip"
        builder.button(text=f"{title} ({status_icon})", callback_data=f"shop:frame:{act}:{f.item_code}")

    if equipped_frame:
        builder.button(text="❌ Снять активную рамку", callback_data="shop:frame:unequip:all")

    builder.button(text="🛍 В магазин", callback_data="shop:main")
    builder.button(text="◀️ В меню", callback_data="shop:back_to_main")
    builder.adjust(1)
    return builder.as_markup()


def _frame_title(code: str) -> str:
    names = {
        "frame_gold": "🥇 Рамка «Отличник»",
        "frame_headman": "👔 Рамка «Староста»",
        "frame_neon": "🌌 Рамка «Неон»",
    }
    return names.get(code, code)


CREDIT_PACKAGES = [
    {
        "code": "starter_pack_99",
        "credits": 300,
        "bonus": 0,
        "price": 99,
        "title": "🚀 Стартовый набор первокурсника",
        "icon": "🚀",
        "is_starter": True,
        "one_time": True,
        "badge": "ВЫГОДА 500%",
        "short_desc": "300 🎓 + Буст 24ч + 3 Шпоры + 1 Справка",
        "perks": [
            "300 Зачётов 🎓 (в 3 раза больше стандарта!)",
            "Буст анкеты ⚡️ в топ на 24 часа",
            "3 «Шпоры» 🔄 (откат свайпа в ленте)",
            "1 «Справка» 🩺 (защита стрика)",
        ],
    },
    {
        "code": "credits_100",
        "credits": 100,
        "bonus": 0,
        "price": 99,
        "title": "«Шпаргалка» (100 🎓)",
        "icon": "🎒",
        "is_starter": False,
        "one_time": False,
        "badge": None,
        "short_desc": "100 Зачётов на баланс",
        "perks": ["100 Зачётов 🎓"],
    },
    {
        "code": "credits_300",
        "credits": 300,
        "bonus": 30,
        "price": 249,
        "title": "«Студенческий» (330 🎓)",
        "icon": "📚",
        "is_starter": False,
        "one_time": False,
        "badge": "+10% Бонус",
        "short_desc": "330 🎓 (300 + 30 бонус)",
        "perks": ["300 Зачётов 🎓", "Бонус +30 🎓"],
    },
    {
        "code": "credits_700",
        "credits": 700,
        "bonus": 100,
        "price": 499,
        "title": "«Сессия закрыта» (800 🎓)",
        "icon": "⚡️",
        "is_starter": False,
        "one_time": False,
        "badge": "🔥 ХИТ",
        "short_desc": "800 🎓 (700 + 100 бонус)",
        "perks": ["700 Зачётов 🎓", "Бонус +100 🎓"],
    },
    {
        "code": "credits_1500",
        "credits": 1500,
        "bonus": 300,
        "price": 899,
        "title": "«Красный диплом» (1800 🎓)",
        "icon": "👑",
        "is_starter": False,
        "one_time": False,
        "badge": "Выгода 20%",
        "short_desc": "1800 🎓 (1500 + 300 бонус)",
        "perks": ["1500 Зачётов 🎓", "Бонус +300 🎓"],
    },
    {
        "code": "credits_3000",
        "credits": 3000,
        "bonus": 800,
        "price": 1499,
        "title": "«Грант ректора» (3800 🎓)",
        "icon": "🏛",
        "is_starter": False,
        "one_time": False,
        "badge": "Выгода 25%",
        "short_desc": "3800 🎓 (3000 + 800 бонус)",
        "perks": ["3000 Зачётов 🎓", "Бонус +800 🎓"],
    },
]


def deposit_credits_keyboard(has_bought_starter_pack: bool = False) -> InlineKeyboardMarkup:
    """Пакеты пополнения баланса за рубли через ЮКассу."""
    builder = InlineKeyboardBuilder()

    for p in CREDIT_PACKAGES:
        if p["code"] == "starter_pack_99":
            if has_bought_starter_pack:
                # Уже куплен - показываем как недоступный или пропускаем
                builder.button(
                    text="✅ 🚀 Стартовый набор (Куплен 1/1)",
                    callback_data="shop:starter_already_bought",
                )
            else:
                builder.button(
                    text=f"🔥 🚀 Стартовый набор (300🎓+Буст) — {p['price']} ₽",
                    callback_data=f"shop:deposit_pack:{p['code']}",
                )
        else:
            btn_text = f"🎓 {p['title']} — {p['price']} ₽"
            builder.button(text=btn_text, callback_data=f"shop:deposit_pack:{p['code']}")

    builder.button(text="◀️ В магазин", callback_data="shop:main")
    builder.adjust(1)
    return builder.as_markup()


def quests_main_keyboard(
    can_claim_streak: bool,
    today_reward: int,
    quests: List[UserDailyQuest],
) -> InlineKeyboardMarkup:
    """Экран зачётки, стрика и дейликов."""
    builder = InlineKeyboardBuilder()

    # Кнопка стрика
    if can_claim_streak:
        builder.button(text=f"🔥 Забрать стипендию (+{today_reward} 🎓)", callback_data="quests:claim_streak")
    else:
        builder.button(text="✅ Стипендия за сегодня получена", callback_data="quests:streak_done")

    # Кнопки готовых дейликов
    for q in quests:
        if q.current_progress >= q.target_progress and not q.is_claimed:
            builder.button(
                text=f"🎁 Забрать +{q.reward_credits} 🎓 ({q.quest_key})",
                callback_data=f"quests:claim_daily:{q.quest_key}",
            )

    builder.button(text="🎒 Достижения первокурсника", callback_data="quests:onboarding")
    builder.button(text="🏪 В Магазин", callback_data="shop:main")
    builder.button(text="◀️ Главное меню", callback_data="shop:back_to_main")

    builder.adjust(1)
    return builder.as_markup()
