"""
CLI-утилита для создания или обновления администратора веб-панели.
Использование:
  python3 create_admin.py <логин> <пароль> [superadmin/moderator]
"""
import sys
import asyncio
from sqlalchemy import select, update

from database.session import AsyncSessionLocal
from database.models import Admin, AdminRole
from web.dependencies import hash_password


async def create_or_update_admin(login: str, password: str, role_str: str = "superadmin"):
    role = AdminRole.superadmin if role_str == "superadmin" else AdminRole.moderator
    password_hash = hash_password(password)

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Admin).where(Admin.login == login))
        admin = result.scalar_one_or_none()

        if admin:
            await db.execute(
                update(Admin)
                .where(Admin.id == admin.id)
                .values(password_hash=password_hash, role=role, is_active=True)
            )
            await db.commit()
            print(f"✅ Пароль администратора '{login}' успешно обновлён!")
        else:
            new_admin = Admin(
                login=login,
                password_hash=password_hash,
                role=role,
                is_active=True,
            )
            db.add(new_admin)
            await db.commit()
            print(f"🎉 Администратор '{login}' с ролью '{role.value}' успешно создан!")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Использование: python3 create_admin.py <логин> <пароль> [superadmin/moderator]")
        print("Пример: python3 create_admin.py admin my_secure_password")
        sys.exit(1)

    login_arg = sys.argv[1]
    password_arg = sys.argv[2]
    role_arg = sys.argv[3] if len(sys.argv) > 3 else "superadmin"

    asyncio.run(create_or_update_admin(login_arg, password_arg, role_arg))
