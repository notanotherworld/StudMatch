"""
Тест проверки функционала диагностики и управления видимостью анкеты в ленте свайпов:
- Рендеринг блока "🔍 Статус в ленте свайпов" в user_detail.html
- Проверка кнопок переключения is_visible и is_complete
- Проверка баннеров подтверждения смены статуса
"""
import os
import sys
from jinja2 import Environment, FileSystemLoader

# UTF-8 вывод для Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


class DummyProfile:
    def __init__(self, is_visible=True, is_complete=True, career_is_complete=False, gender="male", target_gender="female"):
        self.name = "Иван"
        self.year = 3
        self.major = "ФИиИТ"
        self.gender = gender
        self.target_gender = target_gender
        self.goal = "Ищу друзей"
        self.custom_interests = "IT, музыка"
        self.rating_score = 120.0
        self.is_visible = is_visible
        self.is_complete = is_complete
        self.career_is_complete = career_is_complete
        self.career_goal = None
        self.career_custom_skills = None
        self.career_portfolio_url = None
        self.career_work_format = None


class DummyUser:
    def __init__(self, user_id=1071923009, is_active=True, profile=None):
        self.id = user_id
        self.tg_username = "testuser"
        self.email = "test@uni.ru"
        self.email_verified = True
        self.is_active = is_active
        self.is_premium = False
        self.premium_until = None
        self.superlike_balance = 5
        self.flood_ban_count = 0
        self.is_flagged_spammer = False
        self.university = None
        self.profile = profile or DummyProfile()
        self.achievements = []


class DummyRequest:
    def __init__(self, query_params=None):
        self.cookies = {"admin_token": "valid"}
        self.query_params = query_params or {}
        self.url = type("Url", (), {"path": "/admin/users/1071923009"})()


def test_user_detail_feed_status_rendering_active():
    env = Environment(loader=FileSystemLoader("web/templates"))
    template = env.get_template("admin/user_detail.html")

    user = DummyUser(is_active=True, profile=DummyProfile(is_visible=True, is_complete=True))
    rendered = template.render(
        user=user,
        csrf_token="csrf_123",
        temp_ban_info={"is_banned": False, "ttl": 0, "ban_level": 1},
        request=DummyRequest(),
        admin=type("Admin", (), {"id": 1, "username": "admin"})(),
    )

    assert "🔍 Статус в ленте свайпов" in rendered
    assert "🟢 Активна в поиске" in rendered
    assert "Включена" in rendered
    assert "🔒 Скрыть из поиска" in rendered
    assert "/admin/users/1071923009/toggle-visibility" in rendered
    assert "/admin/users/1071923009/toggle-complete" in rendered


def test_user_detail_feed_status_rendering_hidden():
    env = Environment(loader=FileSystemLoader("web/templates"))
    template = env.get_template("admin/user_detail.html")

    # Анкета со скрытой видимостью (is_visible = False)
    user = DummyUser(is_active=True, profile=DummyProfile(is_visible=False, is_complete=True))
    rendered = template.render(
        user=user,
        csrf_token="csrf_123",
        temp_ban_info={"is_banned": False, "ttl": 0, "ban_level": 1},
        request=DummyRequest(),
        admin=type("Admin", (), {"id": 1, "username": "admin"})(),
    )

    assert "🔒 Скрыта из поиска" in rendered
    assert "Скрыта (is_visible=False)" in rendered
    assert "👁 Включить видимость в поиске" in rendered


def test_user_detail_feed_status_banners():
    env = Environment(loader=FileSystemLoader("web/templates"))
    template = env.get_template("admin/user_detail.html")

    user = DummyUser()
    rendered = template.render(
        user=user,
        csrf_token="csrf_123",
        temp_ban_info={"is_banned": False, "ttl": 0, "ban_level": 1},
        request=DummyRequest(query_params={"visibility_changed": "1"}),
        admin=type("Admin", (), {"id": 1, "username": "admin"})(),
    )

    assert "Статус видимости анкеты в поиске успешно изменён!" in rendered


def test_users_html_restore_all_button_and_banner():
    env = Environment(loader=FileSystemLoader("web/templates"))
    template = env.get_template("admin/users.html")

    request = DummyRequest(query_params={"restored_count": "15"})
    rendered = template.render(
        users=[DummyUser()],
        admin=type("Admin", (), {"id": 1, "username": "admin"})(),
        q="",
        page=1,
        is_fake=False,
        filter_type=None,
        spammers_count=0,
        premium_count=0,
        verified_count=0,
        csrf_token="csrf_123",
        request=request,
    )

    assert "/admin/users/restore-all-visibility" in rendered
    assert "Восстановить видимость" in rendered
    assert "Успешно восстановлена видимость в поиске для <b>15</b> анкет" in rendered
    assert "/admin/users/reset-all-swipes" in rendered


def test_user_detail_feed_diagnostics_active_candidate():
    env = Environment(loader=FileSystemLoader("web/templates"))
    template = env.get_template("admin/user_detail.html")

    user = DummyUser()
    cand = DummyProfile()
    cand.user_id = 999111
    cand.name = "Алёна"
    cand.year = 2
    cand.major = "Экономика"
    cand.rating_score = 45.0

    diag = {
        "user_mode": "dating",
        "next_candidate": cand,
        "total_active_others": 50,
        "hidden_profiles_count": 2,
        "incomplete_profiles_count": 3,
        "liked_by_user_count": 10,
        "matches_count": 2,
        "liked_this_user_count": 5,
    }

    rendered = template.render(
        user=user,
        csrf_token="csrf_123",
        temp_ban_info={"is_banned": False, "ttl": 0, "ban_level": 1},
        feed_diagnostic=diag,
        request=DummyRequest(),
        admin=type("Admin", (), {"id": 1, "username": "admin"})(),
    )

    assert "Тест выдачи ленты для этого аккаунта" in rendered
    assert "Лента работает! Следующая анкета в выдаче:" in rendered
    assert "Алёна (#999111)" in rendered
    assert "/admin/users/1071923009/activate-profile" in rendered
    assert "/admin/users/1071923009/reset-swipes" in rendered
    assert "/admin/users/1071923009/reset-all-interactions" in rendered
    assert "/admin/users/1071923009/reset-filters" in rendered


def test_user_detail_feed_diagnostics_empty_feed_breakdown():
    env = Environment(loader=FileSystemLoader("web/templates"))
    template = env.get_template("admin/user_detail.html")

    user = DummyUser()
    diag = {
        "user_mode": "dating",
        "next_candidate": None,
        "total_active_others": 20,
        "hidden_profiles_count": 5,
        "incomplete_profiles_count": 8,
        "liked_by_user_count": 20,
        "matches_count": 3,
        "liked_this_user_count": 4,
    }

    rendered = template.render(
        user=user,
        csrf_token="csrf_123",
        temp_ban_info={"is_banned": False, "ttl": 0, "ban_level": 1},
        feed_diagnostic=diag,
        request=DummyRequest(),
        admin=type("Admin", (), {"id": 1, "username": "admin"})(),
    )

    assert "В ленте свайпов этого пользователя сейчас 0 анкет (лента пуста)!" in rendered
    assert "Всего других активных пользователей: <b>20</b>" in rendered
    assert "is_visible=False" in rendered
    assert "is_complete=False" in rendered
    assert "liked_by_user_count" not in rendered  # rendered nicely
    assert "Уже лайкнуто этим пользователем: <b>20</b>" in rendered


def test_user_detail_action_banners():
    env = Environment(loader=FileSystemLoader("web/templates"))
    template = env.get_template("admin/user_detail.html")

    user = DummyUser()
    for qparam, expected_text in [
        ({"activated": "1"}, "Анкета успешно активирована!"),
        ({"swipes_reset": "1"}, "Исходящие свайпы и мэтчи успешно сброшены!"),
        ({"all_interactions_reset": "1"}, "Все связи (входящие, исходящие свайпы и мэтчи) полностью очищены!"),
        ({"filters_reset": "1"}, "Поисковые фильтры успешно сброшены к стандартным значениям!"),
    ]:
        rendered = template.render(
            user=user,
            csrf_token="csrf_123",
            temp_ban_info={"is_banned": False, "ttl": 0, "ban_level": 1},
            request=DummyRequest(query_params=qparam),
            admin=type("Admin", (), {"id": 1, "username": "admin"})(),
        )
        assert expected_text in rendered


