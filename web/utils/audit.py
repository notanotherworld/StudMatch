"""
Утилита для централизованной записи действий администраторов в журнал аудита.
"""
from typing import Optional, Any
from sqlalchemy.ext.asyncio import AsyncSession
from database.models import AdminAuditLog, Admin


async def log_admin_action(
    db: Optional[AsyncSession] = None,
    admin: Optional[Admin] = None,
    action: str = "",
    target_type: Optional[str] = None,
    target_id: Optional[str] = None,
    details: Optional[str] = None,
    ip_address: Optional[str] = None,
    admin_id: Optional[int] = None,
    **kwargs: Any,
) -> None:
    """Записать действие администратора в журнал аудита."""
    try:
        if db is None and "session" in kwargs:
            db = kwargs["session"]

        resolved_admin_id = None
        resolved_login = "system"
        if admin:
            resolved_admin_id = getattr(admin, "id", None)
            resolved_login = getattr(admin, "login", "admin")
        elif admin_id is not None:
            resolved_admin_id = admin_id

        resolved_action = action or kwargs.get("action", "unknown_action")
        resolved_details = details or kwargs.get("details", None)
        resolved_target_type = target_type or kwargs.get("target_type", None)
        resolved_target_id = target_id or kwargs.get("target_id", None)

        log_entry = AdminAuditLog(
            admin_id=resolved_admin_id,
            admin_login=resolved_login,
            action=resolved_action,
            target_type=resolved_target_type,
            target_id=str(resolved_target_id) if resolved_target_id is not None else None,
            details=resolved_details,
            ip_address=ip_address or kwargs.get("ip_address", None),
        )
        if db:
            db.add(log_entry)
            await db.commit()
    except Exception as e:
        # Аудит не должен ломать основную операцию
        import logging
        logging.getLogger(__name__).warning(f"Failed to record admin audit log: {e}")
