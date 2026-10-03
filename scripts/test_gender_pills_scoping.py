"""
Тест проверки изоляции переключателей пола в Telegram Mini App:
1. Проверка наличия независимых контейнеров #editDatingGenderPills и #editDatingTargetGenderPills в webapp.html
2. Проверка, что в webapp.js отсутствуют некорректные глобальные выборки document.querySelectorAll(".gender-pill")
   без привязки к родительскому контейнеру, которые сбрасывали активное состояние соседних групп.
"""
import os
import re

def test_webapp_gender_pills_scoping():
    js_path = os.path.join(os.path.dirname(__file__), "..", "web", "static", "webapp", "webapp.js")
    with open(js_path, "r", encoding="utf-8") as f:
        js_content = f.read()

    # Проверяем, что нет глобальных document.querySelectorAll(".gender-pill") без ID контейнера
    unscoped_matches = re.findall(r'document\.querySelectorAll\(["\']\.gender-pill["\']\)', js_content)
    assert len(unscoped_matches) == 0, f"Найдено {len(unscoped_matches)} неизолированных вызовов querySelectorAll('.gender-pill')!"

    # Проверяем наличие корректных изолированных вызовов
    assert 'document.querySelectorAll("#genderFilterPills .gender-pill")' in js_content
    assert 'document.querySelectorAll("#editDatingGenderPills .gender-pill")' in js_content
    assert 'document.querySelectorAll("#editDatingTargetGenderPills .gender-pill")' in js_content


def test_webapp_html_gender_containers():
    html_path = os.path.join(os.path.dirname(__file__), "..", "web", "templates", "webapp.html")
    with open(html_path, "r", encoding="utf-8") as f:
        html_content = f.read()

    assert 'id="editDatingGenderPills"' in html_content
    assert 'id="editDatingTargetGenderPills"' in html_content
    assert 'id="genderFilterPills"' in html_content
