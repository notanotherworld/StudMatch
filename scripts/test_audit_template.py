"""
Тест корректности рендеринга шаблона web/templates/admin/audit.html:
- Проверка генерации ссылки /admin/users/{id} для target_type="user"
- Проверка генерации ссылки /admin/employers/{id} для target_type="employer"
- Проверка корректной обработки обычного target_type
"""
import os
import sys
from datetime import datetime, timezone
from jinja2 import Environment, FileSystemLoader

# UTF-8 вывод для Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

class DummyLog:
    def __init__(self, target_type, target_id, action="test_action", admin_login="admin1", details="тест"):
        self.created_at = datetime.now(timezone.utc)
        self.admin_login = admin_login
        self.action = action
        self.target_type = target_type
        self.target_id = target_id
        self.details = details
        self.ip_address = "127.0.0.1"


def test_audit_html_rendering():
    env = Environment(loader=FileSystemLoader("web/templates"))
    template = env.get_template("admin/audit.html")

    logs = [
        DummyLog("user", "1857821748", action="user_ban"),
        DummyLog("employer", "42", action="approve_employer"),
        DummyLog("settings", "maintenance", action="toggle_setting"),
    ]

    class DummyState:
        csrf_token = "dummy_csrf_token"

    class DummyRequest:
        cookies = {"admin_token": "valid"}
        state = DummyState()
        url = type("Url", (), {"path": "/admin/audit"})()

    rendered = template.render(
        logs=logs,
        page=1,
        action="",
        csrf_token="dummy_csrf_token",
        request=DummyRequest(),
    )

    # 1. Проверяем ссылку на пользователя
    assert 'href="/admin/users/1857821748"' in rendered, "Должна присутствовать ссылка на /admin/users/1857821748"
    assert 'target="_blank"' in rendered, "Ссылка должна открываться в новой вкладке"
    assert '1857821748' in rendered
    print("  ✅ [1] Ссылка на /admin/users/1857821748 успешно отрендерена с target='_blank'")

    # 2. Проверяем ссылку на работодателя
    assert 'href="/admin/employers/42"' in rendered, "Должна присутствовать ссылка на /admin/employers/42"
    print("  ✅ [2] Ссылка на /admin/employers/42 успешно отрендерена")

    # 3. Проверяем обычный объект без ссылки
    assert 'settings:' in rendered
    print("  ✅ [3] Неизвестный target_type отображается текстом без поломки верстки")


if __name__ == "__main__":
    print("=" * 60)
    print("📜 ТЕСТИРОВАНИЕ РЕНДЕРИНГА ЖУРНАЛА АУДИТА")
    print("=" * 60)
    test_audit_html_rendering()
    print("=" * 60)
    print("🎉 ВСЕ ПРОВЕРКИ ШАБЛОНА АУДИТА УСПЕШНО ПРОЙДЕНЫ!")
    print("=" * 60)
