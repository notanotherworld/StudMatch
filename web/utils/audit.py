"""
Утилита для централизованной записи действий администраторов в журнал аудита.
"""
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from database.models import AdminAuditLog, Admin


async def log_admin_action(
    db: AsyncSession,
    admin: Admin,
    action: str,
    target_type: Optional[str] = None,
    target_id: Optional[str] = None,
    details: Optional[str] = None,
    ip_address: Optional[str] = None,
) -> None:
    """Записать действие администратора в журнал аудита."""
    try:
        log_entry = AdminAuditLog(
            admin_id=admin.id if admin else None,
            admin_login=admin.login if admin else "system",
            action=action,
            target_type=target_type,
            target_id=str(target_id) if target_id is not None else None,
            details=details,
            ip_address=ip_address,
        )
        db.add(log_entry)
        await db.commit()
    except Exception as e:
        # Аудит не должен ломать основную операцию, но ошибку логируем
        import logging
        logging.getLogger(__name__).warning(f"Failed to record admin audit log: {e}")
