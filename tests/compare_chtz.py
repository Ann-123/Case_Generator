"""
Скрипт для оценки качества генерации ЧТЗ.
Загружает эталонный ЧТЗ из файла и сравнивает с результатом API.
"""

import json
import sys

import requests

API_URL = "http://localhost:8000"
API_KEY = "333fytxrf333"  # замени на актуальный ключ
PROJECT_ID = 1  # проект с загруженным тестовым ТЗ


# Эталонный ЧТЗ (фрагмент из твоего примера)
with open("tests/etalon_chtz.json", "r", encoding="utf-8") as f:
    etalon = json.load(f)


def flatten_requirements(sections):
    """Превращает иерархию в плоский словарь {code: title}."""
    reqs = {}
    for section in sections:
        for req in section.get("requirements", []):
            reqs[req["code"]] = req["title"]
    return reqs


# Получить сгенерированный ЧТЗ из API
resp = requests.post(
    f"{API_URL}/projects/{PROJECT_ID}/generate-chtz",
    headers={"X-API-Key": API_KEY},
)
if resp.status_code != 200:
    print(f"Ошибка генерации: {resp.status_code}")
    print(resp.text)
    sys.exit(1)

generated = resp.json()
# Новая генерация возвращает список секций в поле sections
flat_generated = flatten_requirements(generated.get("sections", []))

# Для сравнения с деревом можно раскрыть его рекурсивно

def flatten_tree(nodes):
    reqs = {}
    for node in nodes:
        if node.get("code"):
            reqs[node["code"]] = node["title"]
        if node.get("children"):
            reqs.update(flatten_tree(node["children"]))
    return reqs


tree_resp = requests.get(
    f"{API_URL}/projects/{PROJECT_ID}/requirements-tree",
    headers={"X-API-Key": API_KEY},
)
if tree_resp.status_code == 200:
    tree_reqs = flatten_tree(tree_resp.json().get("tree", []))
    print(f"Требований в дереве: {len(tree_reqs)}")
else:
    tree_reqs = {}

et_reqs = flatten_requirements(etalon["sections"])

# Сравнение
missing = set(et_reqs.keys()) - set(flat_generated.keys())
extra = set(flat_generated.keys()) - set(et_reqs.keys())

print(f"Эталонных требований: {len(et_reqs)}")
print(f"Сгенерированных требований: {len(flat_generated)}")
print(f"Пропущено: {len(missing)}")
for code in sorted(missing):
    print(f"  - {code}: {et_reqs[code]}")
print(f"Лишних: {len(extra)}")
for code in sorted(extra):
    print(f"  + {code}: {flat_generated[code]}")

# Оценка точности (по наличию кодов)
accuracy = (len(et_reqs) - len(missing)) / len(et_reqs) * 100 if et_reqs else 0
print(f"\nТочность (по кодам): {accuracy:.1f}%")
