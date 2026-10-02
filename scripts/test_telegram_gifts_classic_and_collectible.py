"""
Тестирование классических и коллекционных подарков Telegram:
- 15 подарков в каталоге (11 классических + 4 коллекционных NFT)
- Бейджи: ⭐ Классика и 💎 NFT / Редкий
- Обмен подарков на зачёты 🎓 (кэшаут 80-85%)
- Запрет обмена закреплённого подарка
- Постоянные квесты: gift_sent_1 и gifts_received_3
- Карточка подарка в чате мэтча
"""
import os
import sys
import json
import uuid
import sqlite3
import pytest
from datetime import datetime, timezone

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

sqlite3.register_adapter(list, json.dumps)
sqlite3.register_converter("JSON", json.loads)

@compiles(ARRAY, "sqlite")
def compile_array_sqlite(type_, compiler, **kw):
    return "JSON"

@compiles(UUID, "sqlite")
def compile_uuid_sqlite(type_, compiler, **kw):
    return "VARCHAR(36)"

from sqlalchemy import delete, or_
from database.session import engine, AsyncSessionLocal
from database.models import User, Profile, Match, ChatMessage, ModeEnum, EconomyTransaction, UserPermanentQuest, UserReceivedGift
from database.crud import (
    get_or_create_user,
    get_profile,
    get_campus_gifts_catalog,
    send_campus_gift,
    get_user_received_gifts,
    toggle_pin_user_gift,
    convert_user_gift_to_credits,
    add_user_credits,
    get_or_create_permanent_quests,
    claim_permanent_quest,
    get_chat_messages,
)
from web.routers.webapp import (
    webapp_gifts_catalog,
    webapp_send_gift,
    webapp_get_user_gifts,
    webapp_toggle_pin_gift,
    webapp_convert_gift,
    webapp_get_match_messages,
    SendGiftRequest,
)

@pytest.mark.asyncio
async def test_telegram_classic_and_collectible_gifts():
    from database.session import engine
    from database.models import Base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        # Очищаем старые данные теста если они остались
        await db.execute(delete(ChatMessage).where(ChatMessage.sender_id.in_([999001, 999002])))
        await db.execute(delete(Match).where(or_(Match.user1_id.in_([999001, 999002]), Match.user2_id.in_([999001, 999002]))))
        await db.execute(delete(EconomyTransaction).where(EconomyTransaction.user_id.in_([999001, 999002])))
        await db.execute(delete(UserPermanentQuest).where(UserPermanentQuest.user_id.in_([999001, 999002])))
        await db.execute(delete(UserReceivedGift).where(or_(UserReceivedGift.recipient_id.in_([999001, 999002]), UserReceivedGift.sender_id.in_([999001, 999002]))))
        await db.execute(delete(User).where(User.id.in_([999001, 999002])))
        await db.commit()

        # 1. Создаем двух студентов
        u_sender = await get_or_create_user(db, user_id=999001, tg_username="gift_sender_test")
        u_sender.first_name = "Иван"
        p_sender = await get_profile(db, u_sender.id)
        if p_sender:
            p_sender.name = "Иван"
            p_sender.is_complete = True

        u_rec = await get_or_create_user(db, user_id=999002, tg_username="gift_rec_test")
        u_rec.first_name = "Мария"
        p_rec = await get_profile(db, u_rec.id)
        if p_rec:
            p_rec.name = "Мария"
            p_rec.is_complete = True

        # Создаем мэтч между ними для проверки чат-карточки
        match = Match(
            id=uuid.uuid4(),
            user1_id=u_sender.id,
            user2_id=u_rec.id,
            mode=ModeEnum.dating,
        )
        db.add(match)
        await db.commit()

        # 2. Проверяем каталог подарков
        cat = await get_campus_gifts_catalog(db)
        assert len(cat) == 15
        
        classics = [g for g in cat if not g.get("is_collectible")]
        collectibles = [g for g in cat if g.get("is_collectible")]
        assert len(classics) == 11
        assert len(collectibles) == 4

        # Проверяем наличие всех 11 классических подарков
        classic_codes = {g["code"] for g in classics}
        assert classic_codes == {
            "gift_heart", "gift_bear", "gift_box", "gift_rose", "gift_cake",
            "gift_bouquet", "gift_rocket", "gift_trophy", "gift_ring",
            "gift_champagne", "gift_gem"
        }

        # Проверяем 4 редких подарка
        collectible_codes = {g["code"] for g in collectibles}
        assert collectible_codes == {
            "gift_stellar_rocket", "gift_lollipop", "gift_lush_bouquet", "gift_valentine_box"
        }

        # 3. Начисляем баланс отправителю и дарим классический подарок
        await add_user_credits(db, u_sender.id, 500, tx_type="admin", description="Баланс для тестов")
        await db.refresh(u_sender)
        sender_bal_start = u_sender.credits_balance

        # Отправляем Розу (25 🎓)
        send_res = await webapp_send_gift(
            req=SendGiftRequest(
                recipient_id=u_rec.id,
                gift_code="gift_rose",
                message="Тебе прекрасная роза! 🌹",
                is_anonymous=False,
            ),
            student=u_sender,
            db=db,
        )
        assert send_res["status"] == "success"
        assert send_res["new_balance"] == sender_bal_start - 25

        # 4. Проверяем, что во внутреннем чате появилось сообщение типа "gift"
        msgs_res = await webapp_get_match_messages(match_id=str(match.id), student=u_rec, db=db)
        gift_chat_msg = next((m for m in msgs_res["messages"] if m["msg_type"] == "gift"), None)
        assert gift_chat_msg is not None
        assert gift_chat_msg["gift_data"] is not None
        assert gift_chat_msg["gift_data"]["gift_code"] == "gift_rose"
        assert "роза" in gift_chat_msg["gift_data"]["gift_title"].lower()

        # 5. Проверяем квест «🎁 Щедрая душа» у отправителя
        quests_sender = await get_or_create_permanent_quests(db, u_sender.id)
        gift_sent_q = next(q for q in quests_sender if q.quest_key == "gift_sent_1")
        assert gift_sent_q.current_progress >= 1
        assert gift_sent_q.target_progress == 1

        # Клеймим награду за отправку подарка (+50 🎓)
        claim_ok, claim_msg, rew, badge, _ = await claim_permanent_quest(db, u_sender.id, "gift_sent_1")
        assert claim_ok is True, f"Claim failed: {claim_msg}"
        assert rew == 50
        assert badge == "Меценат 🎁"

        # 6. Отправляем коллекционный подарок NFT: «Звёздная ракета» (150 🎓) анонимно
        send_nft_res = await webapp_send_gift(
            req=SendGiftRequest(
                recipient_id=u_rec.id,
                gift_code="gift_stellar_rocket",
                message="Тайный подарок для звезды! 🚀",
                is_anonymous=True,
            ),
            student=u_sender,
            db=db,
        )
        assert send_nft_res["status"] == "success"

        # 7. Отправляем третий подарок: «Коробка подарка» (15 🎓), чтобы выполнить квест получения 3 подарков
        send_box_res = await webapp_send_gift(
            req=SendGiftRequest(
                recipient_id=u_rec.id,
                gift_code="gift_box",
                message="Сюрприз в коробочке 🎁",
                is_anonymous=False,
            ),
            student=u_sender,
            db=db,
        )
        assert send_box_res["status"] == "success"

        # 8. Проверяем витрину подарков у Марии
        rec_gifts = await webapp_get_user_gifts(user_id=u_rec.id, student=u_rec, db=db)
        assert rec_gifts["status"] == "success"
        assert rec_gifts["count"] == 3
        
        # Находим ракету
        nft_gift = next(g for g in rec_gifts["gifts"] if g["gift_code"] == "gift_stellar_rocket")
        assert nft_gift["is_collectible"] is True
        assert nft_gift["is_anonymous"] is True
        assert nft_gift["sender_id"] is None
        assert nft_gift["sender_name"] == "Скрытый отправитель 🤫"
        assert nft_gift["exchange_credits"] == 125

        # 9. Проверяем квест «👑 Любимчик кампуса» (3 подарка)
        quests_rec = await get_or_create_permanent_quests(db, u_rec.id)
        gift_rec_q = next(q for q in quests_rec if q.quest_key == "gifts_received_3")
        assert gift_rec_q.current_progress >= 3

        # Клеймим награду (+100 🎓)
        claim_rec_ok, _, rew_rec, badge_rec, _ = await claim_permanent_quest(db, u_rec.id, "gifts_received_3")
        assert claim_rec_ok is True
        assert rew_rec == 100
        assert badge_rec == "Звезда ⭐️"

        # 10. Проверяем механику конвертации подарка
        rose_gift = next(g for g in rec_gifts["gifts"] if g["gift_code"] == "gift_rose")
        rose_id = rose_gift["id"]

        # Сначала закрепляем розу
        await webapp_toggle_pin_gift(gift_id=rose_id, student=u_rec, db=db)
        
        # Попытка конвертировать закрепленный подарок -> ошибка
        conv_pinned = await webapp_convert_gift(gift_id=rose_id, student=u_rec, db=db)
        assert conv_pinned["status"] == "error"
        assert "открепите" in conv_pinned["message"].lower()

        # Открепляем
        await webapp_toggle_pin_gift(gift_id=rose_id, student=u_rec, db=db)

        # Конвертируем открепленный подарок -> успех (+20 🎓 за розу)
        await db.refresh(u_rec)
        bal_before_conv = u_rec.credits_balance or 0
        conv_ok = await webapp_convert_gift(gift_id=rose_id, student=u_rec, db=db)
        assert conv_ok["status"] == "success"
        assert conv_ok["credits_added"] == 20
        assert conv_ok["new_balance"] == bal_before_conv + 20

        # Также конвертируем редкий коллекционный подарок (Звёздная ракета) -> +125 🎓
        nft_id = nft_gift["id"]
        conv_nft = await webapp_convert_gift(gift_id=nft_id, student=u_rec, db=db)
        assert conv_nft["status"] == "success"
        assert conv_nft["credits_added"] == 125

        # Проверяем, что конвертированные подарки удалены из профиля
        final_gifts = await webapp_get_user_gifts(user_id=u_rec.id, student=u_rec, db=db)
        assert final_gifts["count"] == 1  # осталась только коробка подарка
        assert final_gifts["gifts"][0]["gift_code"] == "gift_box"
