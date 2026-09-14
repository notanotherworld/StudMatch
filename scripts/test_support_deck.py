"""
Тесты для Support Deck (Служба заботы и поддержки StudMatch):
1. Модель SupportTicket и перечисление TicketStatus.
2. Создание и валидация тикетов студентом (эндпоинт webapp_create_support_ticket).
3. Просмотр истории тикетов студентом (эндпоинт webapp_get_support_tickets).
4. Телеграм-уведомления администраторам при создании тикета.
5. Администрирование в Superadmin Hub (эндпоинты webapp_admin_get_support_tickets и webapp_admin_reply_support_ticket).
6. Веб-админка поддержки (смена статуса и ответ администратора).
"""
import os
import sys
import json
import uuid
import sqlite3
import pytest
from datetime import datetime, timezone
from unittest.mock import patch, AsyncMock, MagicMock

# Настраиваем UTF-8 для вывода в консоль Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

os.environ.setdefault("BOT_TOKEN", "123456:TEST_TOKEN_FOR_SUPPORT_RUNNER")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///test_support_deck.db")

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

from fastapi import HTTPException
from database.session import engine, AsyncSessionLocal
from database.models import Base, User, Profile, SupportTicket, TicketStatus, Admin
from web.routers.webapp import (
    webapp_create_support_ticket,
    webapp_get_support_tickets,
    webapp_admin_get_support_tickets,
    webapp_admin_reply_support_ticket,
    AdminTicketReplyRequest,
)
from web.routers.admin.support import (
    reply_support_ticket,
    update_ticket_status,
)
from bot.config import settings


@pytest.mark.asyncio
async def test_support_ticket_model_and_creation():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        user = User(id=888111, tg_username="ticket_tester", is_active=True)
        db.add(user)
        profile = Profile(user_id=888111, name="Тестер Саппорта", major="МГУ ВМК")
        db.add(profile)
        await db.commit()

        diag_data = {
            "platform": "ios",
            "tg_version": "10.14",
            "screen_width": 393,
            "screen_height": 852,
            "viewport_height": 720,
        }

        ticket = SupportTicket(
            user_id=888111,
            category="bug",
            subject="Не открывается камера",
            message="При нажатии на добавление фото ничего не происходит",
            device_info=json.dumps(diag_data),
            status=TicketStatus.open,
        )
        db.add(ticket)
        await db.commit()
        await db.refresh(ticket)

        assert ticket.id is not None
        assert ticket.category == "bug"
        assert ticket.status == TicketStatus.open
        assert ticket.created_at is not None
        assert ticket.admin_reply is None

        parsed_diag = json.loads(ticket.device_info)
        assert parsed_diag["platform"] == "ios"
        assert parsed_diag["screen_width"] == 393


@pytest.mark.asyncio
async def test_webapp_support_create_api_and_validation():
    async with AsyncSessionLocal() as db:
        user = await db.get(User, 888111)

        # 1. Валидация короткого сообщения (<5 символов)
        mock_req_short = MagicMock()
        mock_req_short.headers = {"content-type": "application/json"}
        mock_req_short.json = AsyncMock(return_value={"category": "bug", "message": "нет"})

        with pytest.raises(HTTPException) as exc_info:
            await webapp_create_support_ticket(request=mock_req_short, student=user, db=db)
        assert exc_info.value.status_code == 400
        assert "не менее 5 символов" in exc_info.value.detail

        # 2. Успешное создание с моком Telegram бота
        mock_req_valid = MagicMock()
        mock_req_valid.headers = {"content-type": "application/json"}
        mock_req_valid.json = AsyncMock(return_value={
            "category": "feature",
            "subject": "Темная тема",
            "message": "Добавьте темную тему для ночного режима!",
            "device_info": {"platform": "android", "screen_width": 412, "screen_height": 915},
        })

        with patch("aiogram.Bot.send_message", new_callable=AsyncMock) as mock_send, \
             patch("aiogram.client.session.aiohttp.AiohttpSession.close", new_callable=AsyncMock):
            res = await webapp_create_support_ticket(request=mock_req_valid, student=user, db=db)
            assert res["status"] == "ok"
            assert res["ticket"]["category"] == "feature"
            assert res["ticket"]["status"] == "open"
            assert mock_send.call_count >= 1


@pytest.mark.asyncio
async def test_webapp_support_get_tickets():
    async with AsyncSessionLocal() as db:
        user = await db.get(User, 888111)
        res = await webapp_get_support_tickets(student=user, db=db)
        assert res["status"] == "ok"
        assert len(res["tickets"]) >= 2
        assert res["tickets"][0]["category"] in ("bug", "feature")


@pytest.mark.asyncio
async def test_superadmin_support_hub_api():
    async with AsyncSessionLocal() as db:
        admin_id = settings.SUPERADMIN_ID
        admin_user = await db.get(User, admin_id)
        if not admin_user:
            admin_user = User(id=admin_id, tg_username="superadmin", is_active=True)
            db.add(admin_user)
            await db.commit()
            await db.refresh(admin_user)

        # 1. Получение списка тикетов супервайзером
        res = await webapp_admin_get_support_tickets(admin=admin_user, db=db)
        assert res["status"] == "ok"
        assert len(res["tickets"]) >= 1

        first_ticket = res["tickets"][0]
        ticket_id = first_ticket["id"]

        # 2. Ответ на тикет через Superadmin Hub API
        with patch("aiogram.Bot.send_message", new_callable=AsyncMock) as mock_send_user, \
             patch("aiogram.client.session.aiohttp.AiohttpSession.close", new_callable=AsyncMock):
            reply_payload = AdminTicketReplyRequest(
                reply="Мы добавили темную тему в обновление v2.0!",
                status="resolved",
            )
            reply_res = await webapp_admin_reply_support_ticket(
                ticket_id=ticket_id,
                payload=reply_payload,
                admin=admin_user,
                db=db,
            )
            assert reply_res["status"] == "ok"
            assert mock_send_user.call_count == 1

        # 3. Проверяем статус в БД
        updated = await db.get(SupportTicket, uuid.UUID(ticket_id))
        assert updated.status == TicketStatus.resolved
        assert "добавили темную тему" in updated.admin_reply
        assert updated.resolved_at is not None


@pytest.mark.asyncio
async def test_web_admin_support_actions():
    async with AsyncSessionLocal() as db:
        # Создаем тестового админа
        admin = await db.get(Admin, 1)
        if not admin:
            admin = Admin(id=1, login="admin_support", password_hash="dummy")
            db.add(admin)
            await db.commit()
            await db.refresh(admin)

        # Создаем новый тикет
        new_ticket = SupportTicket(
            user_id=888111,
            category="question",
            message="Как верифицировать студенческий билет?",
            status=TicketStatus.open,
        )
        db.add(new_ticket)
        await db.commit()
        await db.refresh(new_ticket)

        # 1. Смена статуса через веб-админку
        status_res = await update_ticket_status(
            ticket_id=str(new_ticket.id),
            status="in_progress",
            admin=admin,
            db=db,
        )
        assert status_res.status_code == 302
        await db.refresh(new_ticket)
        assert new_ticket.status == TicketStatus.in_progress

        # 2. Ответ через веб-админку
        with patch("aiogram.Bot.send_message", new_callable=AsyncMock) as mock_send, \
             patch("aiogram.client.session.aiohttp.AiohttpSession.close", new_callable=AsyncMock):
            reply_res = await reply_support_ticket(
                ticket_id=str(new_ticket.id),
                reply="Перейдите в раздел Профиль -> Верификация и загрузите фото студбилета.",
                status="resolved",
                admin=admin,
                db=db,
            )
            assert reply_res.status_code == 302
            assert "success" in reply_res.headers["location"]
            assert mock_send.call_count == 1

        await db.refresh(new_ticket)
        assert new_ticket.status == TicketStatus.resolved
        assert "Перейдите в раздел Профиль" in new_ticket.admin_reply
