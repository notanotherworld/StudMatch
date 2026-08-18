"""Сервис добавления и управления фейковыми / тестовыми анкетами."""
import html
import random
import uuid
from typing import Optional, List
from fastapi import APIRouter, Request, Depends, Form, UploadFile, File, Response, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

from web.dependencies import get_db, get_current_admin, check_csrf
from web.utils.audit import log_admin_action
from web.utils.uploads import save_avatar_upload
from database.models import (
    User, Profile, University, InterestTag, ModeEnum, Swipe, Match, Report, Achievement
)

router = APIRouter()
templates = Jinja2Templates(directory="web/templates")


@router.get("/users/create-fake", response_class=HTMLResponse)
@router.get("/fake-users/create", response_class=HTMLResponse)
async def create_fake_user_page(
    request: Request,
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Страница создания новой тестовой/фейковой анкеты."""
    # Получаем вузы для выпадающего списка
    res_uni = await db.execute(select(University).order_by(University.name))
    universities = res_uni.scalars().all()

    # Получаем теги интересов
    res_tags = await db.execute(select(InterestTag).order_by(InterestTag.id))
    tags = res_tags.scalars().all()

    return templates.TemplateResponse(
        "admin/fake_user_create.html",
        {
            "request": request,
            "admin": admin,
            "universities": universities,
            "tags": tags,
            "csrf_token": getattr(request.state, "csrf_token", ""),
        },
    )


@router.post("/users/create-fake")
@router.post("/fake-users/create")
async def create_fake_user_action(
    request: Request,
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
    # Общие поля
    name: str = Form(...),
    tg_username: Optional[str] = Form(None),
    email: Optional[str] = Form(None),
    university_id: Optional[int] = Form(None),
    major: Optional[str] = Form(None),
    year: int = Form(1),
    rating_score: float = Form(50.0),
    auto_match_mode: str = Form("instant"),
    # Знакомства
    gender: Optional[str] = Form("female"),
    target_gender: Optional[str] = Form("male"),
    goal: Optional[str] = Form(None),
    custom_interests: Optional[str] = Form(None),
    dating_photo: Optional[UploadFile] = File(None),
    # Карьера
    career_goal: Optional[str] = Form(None),
    career_custom_skills: Optional[str] = Form(None),
    career_portfolio_url: Optional[str] = Form(None),
    career_work_format: Optional[str] = Form(None),
    career_photo: Optional[UploadFile] = File(None),
    # Чекбоксы
    is_dating_complete: Optional[str] = Form(None),
    is_career_complete: Optional[str] = Form(None),
    is_visible: Optional[str] = Form("on"),
):
    """Обработка создания фейковой анкеты."""
    await check_csrf(request)

    # Загрузка фото
    dating_photo_url = await save_avatar_upload(dating_photo)
    career_photo_url = await save_avatar_upload(career_photo)

    # Если загружено только одно фото, используем его для обоих режимов
    if not career_photo_url and dating_photo_url:
        career_photo_url = dating_photo_url
    elif not dating_photo_url and career_photo_url:
        dating_photo_url = career_photo_url

    # Генерация уникального ID для бота/фейка (диапазон 9_000_000_000+)
    while True:
        candidate_id = 9000000000 + random.randint(100000, 9999999)
        existing = await db.execute(select(User).where(User.id == candidate_id))
        if not existing.scalar_one_or_none():
            fake_user_id = candidate_id
            break

    clean_username = tg_username.strip().lstrip("@") if tg_username else None
    clean_email = email.strip() if email else f"bot_{fake_user_id}@rudn.ru"

    # Создание User
    new_user = User(
        id=fake_user_id,
        tg_username=clean_username,
        email=clean_email,
        email_verified=True,
        is_active=True,
        is_fake=True,
        auto_match_mode=auto_match_mode,
        mode=ModeEnum.dating,
        university_id=university_id if university_id else None,
        consent_given=True,
        superlike_balance=10,
    )
    db.add(new_user)
    await db.flush()

    # Создание Profile
    new_profile = Profile(
        user_id=fake_user_id,
        name=name.strip(),
        year=year,
        major=major.strip() if major else "Информационные технологии",
        goal=goal.strip() if goal else "Люблю активный отдых, спорт и общение!",
        custom_interests=custom_interests.strip() if custom_interests else None,
        gender=gender,
        target_gender=target_gender,
        avatar_file_id=dating_photo_url,
        career_avatar_file_id=career_photo_url,
        career_goal=career_goal.strip() if career_goal else "Ищу стажировку в IT и команду для хакатонов",
        career_custom_skills=career_custom_skills.strip() if career_custom_skills else "Python, FastApi, SQL, Git",
        career_portfolio_url=career_portfolio_url.strip() if career_portfolio_url else None,
        career_work_format=career_work_format if career_work_format else "🌐 Удалённо",
        rating_score=rating_score,
        is_complete=(is_dating_complete == "on" or is_dating_complete == "true" or is_dating_complete == "1"),
        career_is_complete=(is_career_complete == "on" or is_career_complete == "true" or is_career_complete == "1"),
        is_visible=(is_visible == "on" or is_visible == "true" or is_visible == "1"),
    )
    db.add(new_profile)
    await db.commit()

    await log_admin_action(
        db, admin.id, "create_fake_user",
        f"Создана тестовая анкета #{fake_user_id} ({name})"
    )

    return RedirectResponse(url="/admin/users?is_fake=true", status_code=303)


@router.post("/users/{user_id}/delete-fake")
async def delete_fake_user(
    user_id: int,
    request: Request,
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Удаление тестовой анкеты и связанных данных."""
    await check_csrf(request)

    res = await db.execute(select(User).where(User.id == user_id, User.is_fake == True))
    fake_user = res.scalar_one_or_none()
    if not fake_user:
        raise HTTPException(status_code=404, detail="Тестовый пользователь не найден")

    # Удаляем зависимости
    await db.execute(delete(Swipe).where((Swipe.from_user_id == user_id) | (Swipe.to_user_id == user_id)))
    await db.execute(delete(Match).where((Match.user1_id == user_id) | (Match.user2_id == user_id)))
    await db.execute(delete(Report).where((Report.reporter_id == user_id) | (Report.reported_id == user_id)))
    await db.execute(delete(Achievement).where(Achievement.user_id == user_id))
    await db.execute(delete(Profile).where(Profile.user_id == user_id))
    await db.execute(delete(User).where(User.id == user_id))
    await db.commit()

    await log_admin_action(
        db, admin.id, "delete_fake_user", f"Удалена тестовая анкета #{user_id}"
    )

    return RedirectResponse(url="/admin/users?is_fake=true", status_code=303)
