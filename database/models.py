"""
Все модели SQLAlchemy для СтудМэч.
"""
import uuid
from datetime import datetime
from typing import Optional, List

from sqlalchemy import (
    BigInteger, Boolean, DateTime, Enum, Float, ForeignKey,
    Integer, Numeric, String, Text, ARRAY, func, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.session import Base


# ─────────────────────────────────────────────────────────────
# Вспомогательные типы
# ─────────────────────────────────────────────────────────────
import enum


class ModeEnum(str, enum.Enum):
    career = "career"
    dating = "dating"


class SwipeAction(str, enum.Enum):
    like = "like"
    superlike = "superlike"
    skip = "skip"


class AchievementType(str, enum.Enum):
    gpa = "gpa"
    competition = "competition"
    case = "case"
    olympiad = "olympiad"
    diploma = "diploma"
    publication = "publication"
    participation = "participation"


class VerifiedStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class AdminRole(str, enum.Enum):
    superadmin = "superadmin"
    moderator = "moderator"


class PaymentProduct(str, enum.Enum):
    superlike_1 = "superlike_1"
    superlike_3 = "superlike_3"
    superlike_10 = "superlike_10"
    boost_24h = "boost_24h"
    premium_1m = "premium_1m"


class PaymentStatus(str, enum.Enum):
    pending = "pending"
    succeeded = "succeeded"
    canceled = "canceled"


class ReportStatus(str, enum.Enum):
    pending = "pending"
    resolved = "resolved"
    dismissed = "dismissed"


class ExportStatus(str, enum.Enum):
    pending = "pending"
    sent = "sent"


# ─────────────────────────────────────────────────────────────
# Университеты
# ─────────────────────────────────────────────────────────────
class University(Base):
    __tablename__ = "universities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    short_name: Mapped[str] = mapped_column(String(20), nullable=False)
    # Несколько доменов через запятую: "@rudn.ru,@pfur.ru"
    email_domains: Mapped[str] = mapped_column(Text, nullable=False)
    city: Mapped[str] = mapped_column(String(100), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    users: Mapped[List["User"]] = relationship(back_populates="university")


# ─────────────────────────────────────────────────────────────
# Теги интересов
# ─────────────────────────────────────────────────────────────
class InterestTag(Base):
    __tablename__ = "interest_tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    emoji: Mapped[str] = mapped_column(String(10), default="🏷")


# ─────────────────────────────────────────────────────────────
# Пользователи
# ─────────────────────────────────────────────────────────────
class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # Telegram user_id
    tg_username: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, unique=True)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    university_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("universities.id"), nullable=True)

    consent_given: Mapped[bool] = mapped_column(Boolean, default=False)
    consent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    mode: Mapped[ModeEnum] = mapped_column(Enum(ModeEnum), default=ModeEnum.dating)
    superlike_balance: Mapped[int] = mapped_column(Integer, default=0)
    boost_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Связи
    university: Mapped[Optional["University"]] = relationship(back_populates="users")
    profile: Mapped[Optional["Profile"]] = relationship(back_populates="user", uselist=False)
    email_tokens: Mapped[List["EmailToken"]] = relationship(back_populates="user")
    achievements: Mapped[List["Achievement"]] = relationship(back_populates="user")
    payments: Mapped[List["Payment"]] = relationship(back_populates="user")
    swipes_given: Mapped[List["Swipe"]] = relationship(
        foreign_keys="Swipe.from_user_id", back_populates="from_user"
    )
    swipes_received: Mapped[List["Swipe"]] = relationship(
        foreign_keys="Swipe.to_user_id", back_populates="to_user"
    )


# ─────────────────────────────────────────────────────────────
# Профиль студента
# ─────────────────────────────────────────────────────────────
class Profile(Base):
    __tablename__ = "profiles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), unique=True)

    # Анкета (5 вопросов)
    name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)        # 1
    year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)             # 2 (1–6)
    major: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)        # 3
    interest_ids: Mapped[Optional[List[int]]] = mapped_column(ARRAY(Integer), nullable=True)  # 4
    goal: Mapped[Optional[str]] = mapped_column(Text, nullable=True)                # 5

    # Фото — храним Telegram file_id
    avatar_file_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)

    # Рейтинг
    rating_score: Mapped[float] = mapped_column(Float, default=0.0)

    # Видимость в топе
    is_visible: Mapped[bool] = mapped_column(Boolean, default=True)
    is_complete: Mapped[bool] = mapped_column(Boolean, default=False)  # Анкета заполнена

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="profile")


# ─────────────────────────────────────────────────────────────
# Email-токены верификации
# ─────────────────────────────────────────────────────────────
class EmailToken(Base):
    __tablename__ = "email_tokens"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    token: Mapped[str] = mapped_column(String(6), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used: Mapped[bool] = mapped_column(Boolean, default=False)

    user: Mapped["User"] = relationship(back_populates="email_tokens")


# ─────────────────────────────────────────────────────────────
# Достижения студента
# ─────────────────────────────────────────────────────────────
class Achievement(Base):
    __tablename__ = "achievements"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))

    type: Mapped[AchievementType] = mapped_column(Enum(AchievementType))
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    document_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)   # MinIO URL

    score: Mapped[float] = mapped_column(Float, default=0.0)  # Очки к рейтингу
    verified: Mapped[VerifiedStatus] = mapped_column(Enum(VerifiedStatus), default=VerifiedStatus.pending)
    verified_by: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("admins.id"), nullable=True)
    reject_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="achievements")


# ─────────────────────────────────────────────────────────────
# Свайпы
# ─────────────────────────────────────────────────────────────
class Swipe(Base):
    __tablename__ = "swipes"
    __table_args__ = (
        UniqueConstraint("from_user_id", "to_user_id", name="uq_swipe_pair"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    from_user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    to_user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    action: Mapped[SwipeAction] = mapped_column(Enum(SwipeAction))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    from_user: Mapped["User"] = relationship(foreign_keys=[from_user_id], back_populates="swipes_given")
    to_user: Mapped["User"] = relationship(foreign_keys=[to_user_id], back_populates="swipes_received")


# ─────────────────────────────────────────────────────────────
# Мэтчи
# ─────────────────────────────────────────────────────────────
class Match(Base):
    __tablename__ = "matches"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user1_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    user2_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    mode: Mapped[ModeEnum] = mapped_column(Enum(ModeEnum))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ─────────────────────────────────────────────────────────────
# Администраторы (модераторы)
# ─────────────────────────────────────────────────────────────
class Admin(Base):
    __tablename__ = "admins"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    login: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[AdminRole] = mapped_column(Enum(AdminRole), default=AdminRole.moderator)
    tg_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)  # Для 2FA
    last_login: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ─────────────────────────────────────────────────────────────
# Работодатели / HR
# ─────────────────────────────────────────────────────────────
class Employer(Base):
    __tablename__ = "employers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_name: Mapped[str] = mapped_column(String(200), nullable=False)
    contact_name: Mapped[str] = mapped_column(String(100), nullable=False)
    login: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_by: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("admins.id"), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    profile_accesses: Mapped[List["EmployerProfileAccess"]] = relationship(back_populates="employer")


# ─────────────────────────────────────────────────────────────
# Доступ работодателя к анкетам
# ─────────────────────────────────────────────────────────────
class EmployerProfileAccess(Base):
    __tablename__ = "employer_profile_access"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    employer_id: Mapped[int] = mapped_column(Integer, ForeignKey("employers.id"))
    profile_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("profiles.id"))
    granted_by: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("admins.id"), nullable=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # "Стажировка 2025"
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    viewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    employer: Mapped["Employer"] = relationship(back_populates="profile_accesses")
    profile: Mapped["Profile"] = relationship()


# ─────────────────────────────────────────────────────────────
# Платежи (ЮКасса)
# ─────────────────────────────────────────────────────────────
class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    yookassa_payment_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, unique=True)
    product: Mapped[PaymentProduct] = mapped_column(Enum(PaymentProduct))
    amount_rub: Mapped[float] = mapped_column(Numeric(10, 2))
    status: Mapped[PaymentStatus] = mapped_column(Enum(PaymentStatus), default=PaymentStatus.pending)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship(back_populates="payments")


# ─────────────────────────────────────────────────────────────
# Жалобы
# ─────────────────────────────────────────────────────────────
class Report(Base):
    __tablename__ = "reports"
    __table_args__ = (
        UniqueConstraint("reporter_id", "reported_id", name="uq_report_pair"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    reporter_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    reported_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[ReportStatus] = mapped_column(Enum(ReportStatus), default=ReportStatus.pending)
    resolved_by: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("admins.id"), nullable=True)
    resolution_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    reporter: Mapped["User"] = relationship(foreign_keys=[reporter_id])
    reported: Mapped["User"] = relationship(foreign_keys=[reported_id])


# ─────────────────────────────────────────────────────────────
# История рассылок
# ─────────────────────────────────────────────────────────────
class BroadcastLog(Base):
    __tablename__ = "broadcast_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    admin_id: Mapped[int] = mapped_column(Integer, ForeignKey("admins.id"))
    text: Mapped[str] = mapped_column(Text, nullable=False)
    target: Mapped[str] = mapped_column(String(50), nullable=False)  # all/verified/career/dating
    sent_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ─────────────────────────────────────────────────────────────
# Запросы на выгрузку персональных данных (ФЗ-152)
# ─────────────────────────────────────────────────────────────
class DataExportRequest(Base):
    __tablename__ = "data_export_requests"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    status: Mapped[ExportStatus] = mapped_column(Enum(ExportStatus), default=ExportStatus.pending)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship()
