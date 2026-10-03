"""
Тесты для внутренней экономики StudMatch («Зачёты» 🎓, Стрики, Дейлики, Магазин, Инвентарь, Шпоры).
"""
import os
import sys
import json
import uuid
import sqlite3
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, AsyncMock, MagicMock

# Настраиваем UTF-8 для вывода в консоль Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

os.environ.setdefault("BOT_TOKEN", "123456:TEST_TOKEN_FOR_ECONOMY_RUNNER")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///test_economy.db")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy.ext.compiler import compiles
from sqlalchemy.types import ARRAY
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy import select

sqlite3.register_adapter(list, json.dumps)
sqlite3.register_converter("JSON", json.loads)

@compiles(ARRAY, "sqlite")
def compile_array_sqlite(type_, compiler, **kw):
    return "JSON"

@compiles(UUID, "sqlite")
def compile_uuid_sqlite(type_, compiler, **kw):
    return "VARCHAR(36)"

from database.session import engine, AsyncSessionLocal
from database.models import (
    Base, User, Profile, ShopItem, EconomyTransaction,
    UserDailyQuest, UserPermanentQuest, UserInventoryItem, Swipe, SwipeAction, ModeEnum,
)
from database.crud import (
    get_or_create_user,
    add_user_credits,
    spend_user_credits,
    get_user_credits_balance,
    claim_daily_streak,
    get_or_create_daily_quests,
    track_daily_quest_event,
    claim_daily_quest,
    get_or_create_permanent_quests,
    claim_permanent_quest,
    get_shop_catalog,
    buy_shop_item_with_credits,
    get_user_inventory,
    equip_profile_frame,
    rewind_last_swipe,
    create_swipe,
)
from bot.services.economy_service import (
    format_credits,
    get_frame_title,
    reward_email_verification,
    reward_profile_completion,
    reward_referral,
)


@pytest.fixture(scope="session", autouse=True)
def setup_test_db():
    if os.path.exists("test_economy.db"):
        try:
            os.remove("test_economy.db")
        except Exception:
            pass


@pytest.mark.asyncio
async def test_01_create_schema_and_seed_shop():
    """Проверка создания схемы и посева товаров магазина."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        # Посев базовых товаров
        items = [
            ShopItem(code="superlike_1", title="⭐️ Суперлайк", category="consumable", price_credits=15, bonus_type="superlike", bonus_value=1),
            ShopItem(code="rewind", title="🔄 Шпора", category="consumable", price_credits=10, bonus_type="rewind", bonus_value=1),
            ShopItem(code="freeze_streak", title="🩺 Справка", category="insurance", price_credits=25, bonus_type="freeze", bonus_value=1),
            ShopItem(code="premium_1d", title="💎 Премиум 1д", category="subscription", price_credits=30, bonus_type="premium", bonus_value=1, duration_days=1),
            ShopItem(code="frame_gold", title="🥇 Рамка Отличник", category="cosmetic", price_credits=150, bonus_type="frame", bonus_value=1, duration_days=30),
        ]
        db.add_all(items)
        await db.commit()

        catalog = await get_shop_catalog(db)
        assert len(catalog) == 5
        assert any(i.code == "superlike_1" for i in catalog)


@pytest.mark.asyncio
async def test_02_add_and_spend_credits():
    """Тестирование начисления и списания «Зачётов» и аудит-лога транзакций."""
    async with AsyncSessionLocal() as db:
        user = await get_or_create_user(db, user_id=10101, tg_username="test_student_1")
        assert user.credits_balance == 0

        # Начисление
        bal = await add_user_credits(db, user.id, amount=100, tx_type="onboarding", description="Тестовое начисление")
        assert bal == 100

        cur_bal = await get_user_credits_balance(db, user.id)
        assert cur_bal == 100

        # Успешное списание
        ok, new_bal = await spend_user_credits(db, user.id, amount=40, tx_type="purchase", description="Покупка")
        assert ok is True
        assert new_bal == 60

        # Попытка списать больше, чем есть
        fail, cur = await spend_user_credits(db, user.id, amount=150, tx_type="purchase", description="Слишком дорого")
        assert fail is False
        assert cur == 60


@pytest.mark.asyncio
async def test_03_daily_streak_and_freeze():
    """Тестирование ежедневного стрика входа и механики «Справка от врача»."""
    async with AsyncSessionLocal() as db:
        user = await get_or_create_user(db, user_id=20202, tg_username="test_streak_user")
        user.credits_balance = 0
        await db.commit()

        # День 1: первый клейм
        ok, msg, streak, reward = await claim_daily_streak(db, user.id)
        assert ok is True
        assert streak == 1
        assert reward == 4

        # Повторный клейм в тот же день -> блокировка
        ok2, msg2, streak2, reward2 = await claim_daily_streak(db, user.id)
        assert ok2 is False
        assert streak2 == 1

        # Имитируем вход на следующий день (diff = 1)
        yesterday = datetime.now(timezone.utc) - timedelta(days=1)
        user.last_streak_date = yesterday
        await db.commit()

        ok3, msg3, streak3, reward3 = await claim_daily_streak(db, user.id)
        assert ok3 is True
        assert streak3 == 2
        assert reward3 == 6

        # Имитируем пропуск 1 дня с наличием справки от врача (freeze_count = 1)
        two_days_ago = datetime.now(timezone.utc) - timedelta(days=2)
        user.last_streak_date = two_days_ago
        user.streak_freeze_count = 1
        await db.commit()

        ok4, msg4, streak4, reward4 = await claim_daily_streak(db, user.id)
        assert ok4 is True
        assert streak4 == 3  # Спасён!
        assert user.streak_freeze_count == 0
        assert "Справка от врача" in msg4


@pytest.mark.asyncio
async def test_04_daily_quests_lifecycle():
    """Тестирование жизненного цикла дейликов (создание, прогресс, клейм)."""
    async with AsyncSessionLocal() as db:
        user = await get_or_create_user(db, user_id=30303, tg_username="test_quest_user")
        user.credits_balance = 0
        await db.commit()

        # Создание дейликов на сегодня
        quests = await get_or_create_daily_quests(db, user.id)
        assert len(quests) == 3

        # Прогресс свайпов
        q = await track_daily_quest_event(db, user.id, "swipes_15", increment=5)
        assert q.current_progress == 5

        # Добиваем до 15
        q = await track_daily_quest_event(db, user.id, "swipes_15", increment=10)
        assert q.current_progress == 15

        # Забираем награду
        ok, msg, reward = await claim_daily_quest(db, user.id, "swipes_15")
        assert ok is True
        assert reward == 6

        bal = await get_user_credits_balance(db, user.id)
        assert bal == 6

        # Повторный клейм невозможен
        ok_again, _, _ = await claim_daily_quest(db, user.id, "swipes_15")
        assert ok_again is False


@pytest.mark.asyncio
async def test_05_shop_purchases_and_inventory():
    """Тестирование покупки различных типов товаров в магазине."""
    async with AsyncSessionLocal() as db:
        user = await get_or_create_user(db, user_id=40404, tg_username="test_buyer")
        await add_user_credits(db, user.id, amount=300, tx_type="onboarding", description="Стартовый баланс")

        # 1. Покупка суперлайка (15 🎓)
        ok1, msg1 = await buy_shop_item_with_credits(db, user.id, "superlike_1")
        assert ok1 is True
        assert user.superlike_balance == 1

        # 2. Покупка шпоры (10 🎓) -> инвентарь
        ok2, msg2 = await buy_shop_item_with_credits(db, user.id, "rewind")
        assert ok2 is True
        inv = await get_user_inventory(db, user.id)
        rewind_item = next((i for i in inv if i.item_code == "rewind"), None)
        assert rewind_item is not None
        assert rewind_item.quantity == 1

        # 3. Покупка рамки «Отличник» (150 🎓) -> авто-надевание
        ok3, msg3 = await buy_shop_item_with_credits(db, user.id, "frame_gold")
        assert ok3 is True
        assert user.equipped_frame == "frame_gold"

        # Снятие и повторное надевание рамки
        await equip_profile_frame(db, user.id, None)
        assert user.equipped_frame is None

        await equip_profile_frame(db, user.id, "frame_gold")
        assert user.equipped_frame == "frame_gold"


@pytest.mark.asyncio
async def test_06_rewind_swipe():
    """Тестирование механики отката свайпа («Шпора»)."""
    async with AsyncSessionLocal() as db:
        user = await get_or_create_user(db, user_id=50505, tg_username="test_rewinder")
        target = await get_or_create_user(db, user_id=50506, tg_username="target_user")

        # Свайпаем пользователя со скипом
        await create_swipe(db, from_id=user.id, to_id=target.id, action=SwipeAction.skip)

        # Без шпоры в инвентаре откат невозможен
        fail_rewind, _, _ = await rewind_last_swipe(db, user.id)
        assert fail_rewind is False

        # Добавляем 1 шпору в инвентарь
        db.add(UserInventoryItem(user_id=user.id, item_code="rewind", quantity=1))
        await db.commit()

        # Успешный откат
        ok_rewind, msg, reverted_id = await rewind_last_swipe(db, user.id)
        assert ok_rewind is True
        assert reverted_id == target.id

        # Проверяем, что свайп удалён из БД
        swipes_res = await db.execute(select(Swipe).where(Swipe.from_user_id == user.id))
        assert len(swipes_res.scalars().all()) == 0


@pytest.mark.asyncio
async def test_07_onboarding_and_referral_rewards():
    """Тестирование разовых онбординг-ачивок и реферальной программы."""
    async with AsyncSessionLocal() as db:
        u_ref = await get_or_create_user(db, user_id=60601, tg_username="referrer")
        u_new = await get_or_create_user(db, user_id=60602, tg_username="newbie")

        # Реферальная награда: +50 🎓 рефереру, +30 🎓 новичку
        ok_ref = await reward_referral(db, u_ref.id, u_new.id)
        assert ok_ref is True

        bal_ref = await get_user_credits_balance(db, u_ref.id)
        bal_new = await get_user_credits_balance(db, u_new.id)
        assert bal_ref == 50
        assert bal_new == 30

        # Повторная выдача рефералки тому же пользователю блокируется
        ok_ref_repeat = await reward_referral(db, u_ref.id, u_new.id)
        assert ok_ref_repeat is False

        # Верификация email (+100 🎓)
        ok_em, new_bal = await reward_email_verification(db, u_new.id)
        assert ok_em is True
        assert new_bal == 130

        # Повторно email награду не выдаёт
        ok_em_repeat, _ = await reward_email_verification(db, u_new.id)
        assert ok_em_repeat is False


def test_08_formatting_helpers():
    """Проверка форматирования текста валюты и рамок."""
    assert "зачёт" in format_credits(1)
    assert "зачёта" in format_credits(2)
    assert "зачётов" in format_credits(5)
    assert "зачётов" in format_credits(11)
    assert "зачётов" in format_credits(20)

    assert "Отличник" in get_frame_title("frame_gold")
    assert "Староста" in get_frame_title("frame_headman")
    assert "Неон" in get_frame_title("frame_neon")


@pytest.mark.asyncio
async def test_09_webapp_economy_api():
    """Тестирование эндпоинтов MiniApp API (обзор, клейм, витрина, покупка)."""
    from web.routers.webapp import (
        webapp_economy_overview,
        webapp_claim_streak,
        webapp_claim_quest,
        webapp_shop_catalog,
        webapp_shop_buy,
        webapp_equip_frame,
        BuyShopItemRequest,
        ClaimQuestRequest,
        EquipFrameRequest,
    )

    async with AsyncSessionLocal() as db:
        student = await get_or_create_user(db, user_id=70707, tg_username="webapp_student")
        await add_user_credits(db, student.id, 200, "onboarding", "Тестовый баланс")

        # 1. Overview
        data = await webapp_economy_overview(student=student, db=db)
        assert data["status"] == "success"
        assert data["credits_balance"] == 200
        assert data["can_claim_streak"] is True
        assert len(data["daily_quests"]) == 3

        # 2. Claim Streak
        res_streak = await webapp_claim_streak(student=student, db=db)
        assert res_streak["status"] == "success"
        assert res_streak["new_streak"] == 1

        # 3. Shop Catalog
        cat = await webapp_shop_catalog(student=student, db=db)
        assert cat["status"] == "success"
        assert len(cat["items"]) > 0

        # 4. Shop Buy
        buy_res = await webapp_shop_buy(req=BuyShopItemRequest(item_code="superlike_1"), student=student, db=db)
        assert buy_res["status"] == "success"
        assert buy_res["new_balance"] == 189  # 200 + 4 (streak day 1) - 15 (superlike) = 189

        # 5. Equip Frame
        frame_res = await webapp_equip_frame(req=EquipFrameRequest(frame_code="none"), student=student, db=db)
        assert frame_res["status"] == "success"


@pytest.mark.asyncio
async def test_09_permanent_quests():
    """Тестирование постоянных заданий (вех) и их ретроспективного учета."""
    from web.routers.webapp import (
        webapp_economy_overview,
        webapp_claim_permanent_quest,
        ClaimQuestRequest,
    )

    async with AsyncSessionLocal() as db:
        user = await get_or_create_user(db, user_id=88888, tg_username="achiever")
        user.email_verified = True
        user.streak_days = 7
        user.profile = Profile(user_id=user.id, name="Алексей", goal="Архитектура и дизайн проектов", is_complete=True)
        await db.commit()

        # 1. Получение постоянных заданий
        perm_quests = await get_or_create_permanent_quests(db, user.id)
        assert len(perm_quests) == 10

        gift_sent_q = next(q for q in perm_quests if q.quest_key == "gift_sent_1")
        assert gift_sent_q.target_progress == 1
        assert gift_sent_q.reward_credits == 20

        gift_rec_q = next(q for q in perm_quests if q.quest_key == "gifts_received_3")
        assert gift_rec_q.target_progress == 3
        assert gift_rec_q.reward_credits == 40

        profile_q = next(q for q in perm_quests if q.quest_key == "onboarding_profile")
        assert profile_q.current_progress == 1
        assert profile_q.is_claimed is False

        email_q = next(q for q in perm_quests if q.quest_key == "onboarding_email")
        assert email_q.current_progress == 1
        assert email_q.reward_credits == 40
        assert email_q.reward_badge == "Верифицирован 🎓"

        streak_q = next(q for q in perm_quests if q.quest_key == "streak_7")
        assert streak_q.current_progress == 7

        # 2. Сбор награды через WebApp API
        claim_res = await webapp_claim_permanent_quest(
            req=ClaimQuestRequest(quest_key="onboarding_email"),
            student=user,
            db=db,
        )
        assert claim_res["status"] == "success"
        assert claim_res["reward_credits"] == 40
        assert claim_res["reward_badge"] == "Верифицирован 🎓"
        assert claim_res["new_balance"] >= 40

        # Повторный сбор должен выдать ошибку
        claim_repeat = await webapp_claim_permanent_quest(
            req=ClaimQuestRequest(quest_key="onboarding_email"),
            student=user,
            db=db,
        )
        assert claim_repeat["status"] == "error"

        # 3. Проверка overview endpoint
        overview = await webapp_economy_overview(student=user, db=db)
        assert "permanent_quests" in overview
        assert len(overview["permanent_quests"]) == 10
        claimed_email = next(q for q in overview["permanent_quests"] if q["quest_key"] == "onboarding_email")
        assert claimed_email["is_claimed"] is True


@pytest.mark.asyncio
async def test_11_credit_packs_and_starter_pack():
    """Тестирование покупки пакетов зачётов за рубли и строгой однократности стартового набора."""
    from web.routers.webapp import (
        webapp_economy_overview,
        webapp_create_pack_payment,
        CreatePackPaymentRequest,
    )
    from database.crud import check_user_can_buy_starter_pack, get_user_inventory

    async with AsyncSessionLocal() as db:
        user = await get_or_create_user(db, user_id=99999, tg_username="pack_buyer")
        user.credits_balance = 10
        user.streak_freeze_count = 0
        user.has_bought_starter_pack = False
        await db.commit()

        # 1. Проверяем каталог пакетов в overview
        ov = await webapp_economy_overview(student=user, db=db)
        assert "credit_packages" in ov
        assert ov["can_buy_starter"] is True
        assert ov["has_bought_starter_pack"] is False

        starter_pack = next(p for p in ov["credit_packages"] if p["code"] == "starter_pack_99")
        assert starter_pack["price"] == 99
        assert starter_pack["credits"] == 300
        assert starter_pack["is_starter"] is True
        assert starter_pack["is_available"] is True

        # 2. Покупка обычного пакета (credits_300 -> 330 🎓)
        buy_reg = await webapp_create_pack_payment(
            req=CreatePackPaymentRequest(pack_code="credits_300"),
            student=user,
            db=db,
        )
        assert buy_reg["status"] == "success"
        await db.refresh(user)
        assert user.credits_balance == 340  # 10 + 330

        # 3. Покупка супер-стартового набора за 99 руб (300 🎓 + буст 24ч + 3 шпоры + 1 справка)
        buy_starter = await webapp_create_pack_payment(
            req=CreatePackPaymentRequest(pack_code="starter_pack_99"),
            student=user,
            db=db,
        )
        assert buy_starter["status"] == "success"
        await db.refresh(user)

        assert user.credits_balance == 640  # 340 + 300
        assert user.has_bought_starter_pack is True
        assert user.streak_freeze_count == 1
        assert user.boost_until is not None

        # Проверяем начисление 3 шпор в инвентарь
        inv = await get_user_inventory(db, user.id)
        rewind_item = next((it for it in inv if it.item_code == "rewind"), None)
        assert rewind_item is not None
        assert rewind_item.quantity == 3

        # 4. Проверяем строгий запрет на повторную покупку стартового набора
        buy_starter_again = await webapp_create_pack_payment(
            req=CreatePackPaymentRequest(pack_code="starter_pack_99"),
            student=user,
            db=db,
        )
        assert buy_starter_again["status"] == "error"
        assert "уже был приобретён" in buy_starter_again["message"]

        # 5. Проверяем, что в overview стартовый набор помечен как недоступный
        ov_after = await webapp_economy_overview(student=user, db=db)
        assert ov_after["can_buy_starter"] is False
        assert ov_after["has_bought_starter_pack"] is True
        starter_after = next(p for p in ov_after["credit_packages"] if p["code"] == "starter_pack_99")
        assert starter_after["is_available"] is False

        # 6. Проверка функции-валидатора
        assert await check_user_can_buy_starter_pack(db, user.id) is False

        # 7. Проверка VIP-пакета «Кампусный инвестор» (2799 ₽ -> 8000 🎓)
        pack_6000 = next(p for p in ov_after["credit_packages"] if p["code"] == "credits_6000")
        assert pack_6000["price"] == 2799
        assert pack_6000["credits"] == 6000
        assert pack_6000["bonus"] == 2000
        assert pack_6000["badge"] == "VIP ВЫГОДА 35%"
        assert pack_6000["is_starter"] is False

        bal_before = user.credits_balance
        buy_6000 = await webapp_create_pack_payment(
            req=CreatePackPaymentRequest(pack_code="credits_6000"),
            student=user,
            db=db,
        )
        assert buy_6000["status"] == "success"
        await db.refresh(user)
        assert user.credits_balance == bal_before + 8000


@pytest.mark.asyncio
async def test_12_fortune_wheel_and_campus_gifts():
    """Тестирование функционала Колеса Фортуны («Счастливый билет» 🎲) и витрины Подарков кампуса 🎁."""
    from database.crud import (
        get_fortune_wheel_status,
        spin_fortune_wheel,
        get_campus_gifts_catalog,
        send_campus_gift,
        get_user_received_gifts,
        toggle_pin_user_gift,
        add_user_credits,
    )
    from web.routers.webapp import (
        webapp_wheel_status,
        webapp_wheel_spin,
        webapp_gifts_catalog,
        webapp_send_gift,
        webapp_get_user_gifts,
        webapp_toggle_pin_gift,
        SpinWheelRequest,
        SendGiftRequest,
    )

    async with AsyncSessionLocal() as db:
        # Создаём двух тестовых студентов
        user1 = await get_or_create_user(db, user_id=888001, tg_username="wheel_tester_1")
        user1.first_name = "Алексей"
        user2 = await get_or_create_user(db, user_id=888002, tg_username="gift_receiver_2")
        user2.first_name = "Мария"
        await db.commit()

        # 1. Проверяем начальный статус Колеса Фортуны для user1
        st = await get_fortune_wheel_status(db, user1.id)
        assert st["can_spin_free"] is True
        assert st["seconds_left"] == 0
        assert st["paid_price"] == 15
        assert len(st["sectors"]) == 8

        # 2. Бесплатное вращение Колеса
        spin_ok, msg, sector = await spin_fortune_wheel(db, user1.id, use_paid=False)
        assert spin_ok is True
        assert sector is not None
        assert "sector_id" in sector
        assert sector["is_free"] is True
        await db.refresh(user1)
        assert user1.last_fortune_spin_at is not None
        assert user1.fortune_spins_count == 1

        # 3. Повторная попытка бесплатного вращения сразу же должна отклоняться (cooldown 24ч)
        spin_fail, fail_msg, _ = await spin_fortune_wheel(db, user1.id, use_paid=False)
        assert spin_fail is False
        assert "не доступно" in fail_msg

        # Проверяем статус через API endpoint
        api_st = await webapp_wheel_status(student=user1, db=db)
        assert api_st["status"] == "success"
        assert api_st["can_spin_free"] is False
        assert api_st["seconds_left"] > 86000

        # 4. Платное вращение при нулевом балансе
        user1.credits_balance = 5
        await db.commit()
        spin_paid_fail, paid_fail_msg, _ = await spin_fortune_wheel(db, user1.id, use_paid=True)
        assert spin_paid_fail is False
        assert "Недостаточно зачётов" in paid_fail_msg

        # 5. Платное вращение при достаточном балансе (например, 100 🎓)
        await add_user_credits(db, user1.id, 100, tx_type="admin", description="Пополнение для теста колеса")
        await db.refresh(user1)
        bal_before = user1.credits_balance

        api_spin_res = await webapp_wheel_spin(
            req=SpinWheelRequest(use_paid=True),
            student=user1,
            db=db,
        )
        assert api_spin_res["status"] == "success"
        assert api_spin_res["sector"] is not None
        await db.refresh(user1)
        assert user1.fortune_spins_count == 2

        # 6. Каталог подарков Telegram (11 классических + 4 коллекционных NFT)
        gifts_cat = await get_campus_gifts_catalog(db)
        assert len(gifts_cat) == 15
        codes = [g["code"] for g in gifts_cat]
        assert "gift_heart" in codes
        assert "gift_bear" in codes
        assert "gift_box" in codes
        assert "gift_rose" in codes
        assert "gift_cake" in codes
        assert "gift_bouquet" in codes
        assert "gift_rocket" in codes
        assert "gift_trophy" in codes
        assert "gift_ring" in codes
        assert "gift_champagne" in codes
        assert "gift_gem" in codes
        assert "gift_stellar_rocket" in codes
        assert "gift_lollipop" in codes
        assert "gift_lush_bouquet" in codes
        assert "gift_valentine_box" in codes

        # Проверяем метку коллекционности
        stellar_meta = next(g for g in gifts_cat if g["code"] == "gift_stellar_rocket")
        assert stellar_meta["is_collectible"] is True
        assert stellar_meta["exchange_credits"] == 1600

        api_cat = await webapp_gifts_catalog(student=user1, db=db)
        assert api_cat["status"] == "success"
        assert len(api_cat["gifts"]) == 15

        # 7. Отправка подарка (user1 -> user2): Плюшевый мишка (50 🎓)
        await add_user_credits(db, user1.id, 200, tx_type="admin", description="Тест подарков")
        await db.refresh(user1)
        bal_before_gift = user1.credits_balance

        send_res = await webapp_send_gift(
            req=SendGiftRequest(
                recipient_id=user2.id,
                gift_code="gift_bear",
                message="Держи мишку на удачу! 🧸",
                is_anonymous=False,
            ),
            student=user1,
            db=db,
        )
        assert send_res["status"] == "success"
        assert "успешно отправлен" in send_res["message"]
        await db.refresh(user1)
        assert user1.credits_balance == bal_before_gift - 15  # плюшевый мишка Telegram стоит 15 🎓

        # 8. Отправка анонимного подарка (user1 -> user2): Ракета (50 🎓)
        send_anon_res = await webapp_send_gift(
            req=SendGiftRequest(
                recipient_id=user2.id,
                gift_code="gift_rocket",
                message="Только вперёд к звёздам! 🚀",
                is_anonymous=True,
            ),
            student=user1,
            db=db,
        )
        assert send_anon_res["status"] == "success"
        assert send_anon_res["gift"]["is_anonymous"] is True

        # 9. Проверка витрины подарков у получателя (user2)
        u2_gifts_res = await webapp_get_user_gifts(user_id=user2.id, student=user2, db=db)
        assert u2_gifts_res["status"] == "success"
        assert u2_gifts_res["count"] >= 2
        gifts_list = u2_gifts_res["gifts"]

        # Находим подарок с мишкой
        bear_gift = next(g for g in gifts_list if g["gift_code"] == "gift_bear")
        assert bear_gift["is_anonymous"] is False
        assert bear_gift["sender_name"] == "Алексей"
        assert "мишку" in bear_gift["message"]
        assert bear_gift["exchange_credits"] == 12

        # Находим анонимный подарок с ракетой
        rocket_gift = next(g for g in gifts_list if g["gift_code"] == "gift_rocket")
        assert rocket_gift["is_anonymous"] is True
        assert rocket_gift["sender_id"] is None
        assert "Скрытый" in rocket_gift["sender_name"]

        # 10. Закрепление подарка в профиле (pin / unpin)
        gift_id = bear_gift["id"]
        pin_res = await webapp_toggle_pin_gift(gift_id=gift_id, student=user2, db=db)
        assert pin_res["status"] == "success"
        assert pin_res["is_pinned"] is True

        # 11. Попытка обмена закреплённого подарка (должна вернуть ошибку)
        from web.routers.webapp import webapp_convert_gift
        convert_pinned_fail = await webapp_convert_gift(gift_id=gift_id, student=user2, db=db)
        assert convert_pinned_fail["status"] == "error"
        assert "открепите" in convert_pinned_fail["message"].lower()

        # Открепление
        unpin_res = await webapp_toggle_pin_gift(gift_id=gift_id, student=user2, db=db)
        assert unpin_res["status"] == "success"
        assert unpin_res["is_pinned"] is False

        # 12. Успешный обмен откреплённого подарка на зачёты 🎓
        await db.refresh(user2)
        u2_bal_before = user2.credits_balance or 0
        convert_ok = await webapp_convert_gift(gift_id=gift_id, student=user2, db=db)
        assert convert_ok["status"] == "success"
        assert convert_ok["credits_added"] == 12
        await db.refresh(user2)
        assert user2.credits_balance == u2_bal_before + 12

        # Проверяем, что подарок удалён из профиля
        u2_gifts_after = await webapp_get_user_gifts(user_id=user2.id, student=user2, db=db)
        assert not any(g["id"] == gift_id for g in u2_gifts_after["gifts"])


@pytest.mark.asyncio
async def test_13_premium_x3_quest_rewards():
    """Тестирование x3 множителя наград за ежедневные и постоянные задания для Премиум-пользователей."""
    from database.crud import (
        set_user_premium,
        revoke_user_premium,
        get_or_create_daily_quests,
        track_daily_quest_event,
        claim_daily_quest,
        get_or_create_permanent_quests,
        claim_permanent_quest,
    )
    from web.routers.webapp import webapp_economy_overview, webapp_claim_quest, webapp_claim_permanent_quest, ClaimQuestRequest

    async with AsyncSessionLocal() as db:
        user = await get_or_create_user(db, user_id=98765, tg_username="prem_quest_tester")
        user.credits_balance = 0
        user.premium_until = None
        await db.commit()

        # 1. Обычный пользователь (не премиум): награда за дейлик 1x (6 🎓)
        quests_norm = await get_or_create_daily_quests(db, user.id)
        q_swipes = next(q for q in quests_norm if q.quest_key == "swipes_15")
        assert q_swipes.reward_credits == 6

        # 2. Выдаем Премиум
        await set_user_premium(db, user.id, days=30)
        await db.refresh(user)
        assert user.is_premium is True

        # 3. get_or_create_daily_quests должен обновить награду до x3 (18 🎓)
        quests_prem = await get_or_create_daily_quests(db, user.id)
        q_swipes_prem = next(q for q in quests_prem if q.quest_key == "swipes_15")
        assert q_swipes_prem.reward_credits == 18

        # 4. Выполняем дейлик и забираем награду через WebApp API
        await track_daily_quest_event(db, user.id, "swipes_15", increment=15)
        claim_resp = await webapp_claim_quest(
            req=ClaimQuestRequest(quest_key="swipes_15"),
            student=user,
            db=db,
        )
        assert claim_resp["status"] == "success"
        assert claim_resp["reward_credits"] == 18
        assert claim_resp["new_balance"] == 18

        # 5. Проверяем постоянные задания (ачивки): должны быть x3
        user.profile = Profile(user_id=user.id, name="Тестер", goal="Тест профиля для ачивки", is_complete=True)
        await db.commit()

        perm_quests = await get_or_create_permanent_quests(db, user.id)
        perm_profile = next(pq for pq in perm_quests if pq.quest_key == "onboarding_profile")
        assert perm_profile.reward_credits == 60  # 20 * 3 = 60
        assert perm_profile.current_progress == 1

        # Клеймим постоянное задание
        claim_perm_resp = await webapp_claim_permanent_quest(
            req=ClaimQuestRequest(quest_key="onboarding_profile"),
            student=user,
            db=db,
        )
        assert claim_perm_resp["status"] == "success"
        assert claim_perm_resp["reward_credits"] == 60
        assert claim_perm_resp["new_balance"] == 78  # 18 + 60

        # 6. Проверяем overview API
        ov = await webapp_economy_overview(student=user, db=db)
        assert ov["is_premium"] is True
        assert ov["quest_multiplier"] == 3
        swipes_ov = next(q for q in ov["daily_quests"] if q["quest_key"] == "swipes_15")
        assert swipes_ov["is_premium_boosted"] is True
        assert swipes_ov["reward_multiplier"] == 3




