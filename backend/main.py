"""
FastAPI MVP: генератор тест-кейсов + библиотека страниц (Mistral)
"""

import os
import re
import json
import logging
import traceback
from pathlib import Path
from contextlib import asynccontextmanager
from typing import List, Optional, Union

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, RedirectResponse
from openai import AsyncOpenAI
from pydantic import BaseModel, Field, create_model, ValidationError

# ----------- Загрузка конфигурации ----------
env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

PROVIDER = os.getenv("LLM_PROVIDER", "mistral").lower()
if PROVIDER == "mistral":
    api_key = os.getenv("MISTRAL_API_KEY")
    base_url = "https://api.mistral.ai/v1"
    default_model = "open-mistral-nemo"
else:
    raise RuntimeError(f"Провайдер {PROVIDER} не поддерживается")

if not api_key:
    raise RuntimeError("MISTRAL_API_KEY не задан в .env")

MODEL = os.getenv("LLM_MODEL", default_model)
VISION_MODEL = os.getenv("VISION_MODEL", "pixtral-12b-2409")

client = AsyncOpenAI(api_key=api_key, base_url=base_url)

# ----------- Инициализация БД страниц ----------
from .database import init_db, get_page_description, get_all_pages


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    os.makedirs(
        os.path.join(os.path.dirname(__file__), "static", "uploads"), exist_ok=True
    )
    yield


# ----------- FastAPI приложение ----------
app = FastAPI(title="QA Case Generator MVP + Pages", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory="backend/static"), name="static")

# ----------- Роутеры ----------
from .pages import router as pages_router

app.include_router(pages_router)


# ----------- Модели для генерации ----------
class GenerateRequest(BaseModel):
    task_text: str
    fields: List[str]
    checklist_items: Optional[List["ChecklistItemData"]] = None


class ChecklistItemData(BaseModel):
    id: str
    text: str
    category: str
    area: str = ""


class GenerateChecklistRequest(BaseModel):
    task_text: str


def build_dynamic_test_case_model(fields: List[str]) -> BaseModel:
    field_defs = {}
    for idx, name in enumerate(fields):
        # Разрешаем строку или список строк
        field_defs[f"field_{idx}"] = (
            Optional[Union[str, List[str]]],
            Field(default=None, alias=name),
        )
    model = create_model("DynamicTestCase", **field_defs)
    model.model_config = {"extra": "ignore"}
    return model


# ----------- Замена плейсхолдеров ----------
logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s: %(message)s")
logger = logging.getLogger(__name__)

# ----------- Загрузка скилла (промпта) для генерации тест-кейсов ----------
SKILLS_DIR = Path(__file__).resolve().parent / "prompts"

def load_test_case_prompt() -> str:
    path = SKILLS_DIR / "test_case_generator.md"
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        logger.warning("Файл скилла не найден: %s", path)
        return "Ты — опытный QA-инженер. Сгенерируй список тест-кейсов."

TEST_CASE_SKILL_PROMPT = load_test_case_prompt()

def load_checklist_prompt() -> str:
    path = SKILLS_DIR / "checklist_generator.md"
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        logger.warning("Файл скилла не найден: %s", path)
        return (
            "Ты — профессиональный QA-инженер. "
            "Создай контрольный список тестирования."
        )

CHECKLIST_SKILL_PROMPT = load_checklist_prompt()


def replace_placeholders(text: str) -> str:
    """
    Заменяет {{Имя страницы}} на полное описание из БД.
    Если описание не найдено, оставляет плейсхолдер без изменений.
    """

    def replacer(match):
        name = match.group(1).strip()
        desc = get_page_description(name)
        if desc is not None:
            logger.info("Подставлена страница '%s': %s...", name, desc[:50])
            return f"\n--- Описание страницы '{name}' ---\n{desc}\n---"
        else:
            available = ", ".join(p["name"] for p in get_all_pages())
            logger.warning(
                "Страница '%s' не найдена в БД. Доступные: %s", name, available
            )
            return match.group(0)

    return re.sub(r"\{\{(.+?)\}\}", replacer, text)


# ----------- Промпт для генерации чек-листа загружается из файла ----------


# ----------- Эндпоинт генерации чек-листа ----------
@app.post("/generate-checklist")
async def generate_checklist(req: GenerateChecklistRequest):
    if not req.task_text.strip():
        return JSONResponse(status_code=400, content={"error": "Текст задачи пуст"})

    processed_task = replace_placeholders(req.task_text)

    raw_content = ""
    try:
        response = await client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": CHECKLIST_SKILL_PROMPT},
                {"role": "user", "content": f"Описание задачи:\n{processed_task}"},
            ],
            temperature=0.3,
            response_format={"type": "json_object"},
        )
        raw_content = response.choices[0].message.content.strip()

        try:
            parsed = json.loads(raw_content)
        except json.JSONDecodeError:
            return JSONResponse(
                status_code=500,
                content={
                    "error": "Ответ модели не является валидным JSON",
                    "raw_response": raw_content,
                },
            )

        checklist = None
        if isinstance(parsed, dict) and "checklist" in parsed:
            checklist = parsed["checklist"]
        elif isinstance(parsed, dict):
            if "positive" in parsed or "negative" in parsed:
                checklist = parsed
            else:
                for key, val in parsed.items():
                    if isinstance(val, dict) and ("positive" in val or "negative" in val):
                        checklist = val
                        break

        if checklist is None:
            return JSONResponse(
                status_code=500,
                content={
                    "error": "Не удалось найти структуру чек-листа в ответе модели",
                    "raw_response": raw_content,
                },
            )

        for key in ["positive", "negative"]:
            if key not in checklist or not isinstance(checklist[key], list):
                checklist[key] = []
        if "affected_areas" not in checklist or not isinstance(checklist["affected_areas"], list):
            checklist["affected_areas"] = []

        return {"checklist": checklist}

    except Exception as e:
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"error": f"Ошибка: {str(e)}"})


# ----------- Основной эндпоинт генерации ----------
@app.post("/generate")
async def generate_test_cases(req: GenerateRequest):
    if not req.task_text.strip():
        return JSONResponse(status_code=400, content={"error": "Текст задачи пуст"})
    if not req.fields:
        return JSONResponse(
            status_code=400, content={"error": "Список полей шаблона пуст"}
        )
    if len(req.fields) != len(set(req.fields)):
        return JSONResponse(
            status_code=400, content={"error": "Названия полей должны быть уникальными"}
        )

    # Подстановка описаний страниц
    processed_task = replace_placeholders(req.task_text)

    active_fields = list(req.fields)
    if req.checklist_items:
        if "Тип" not in active_fields:
            active_fields.append("Тип")

    TestCaseModel = build_dynamic_test_case_model(active_fields)
    fields_list = ", ".join(active_fields)

    system_prompt = (
        f"{TEST_CASE_SKILL_PROMPT}\n\n"
        "## Поля тест-кейсов\n"
        "Ответ должен быть JSON-объектом с единственным ключом 'test_cases'. "
        "Значение 'test_cases' — массив объектов. Каждый объект содержит ТОЛЬКО указанные поля: "
        f"{fields_list}. "
        "Не добавляй других ключей. Оберни ответ в чистый JSON, без markdown-разметки."
    )

    if req.checklist_items:
        system_prompt += (
            "\n\nТакже для каждого тест-кейса обязательно укажи поле 'Тип' "
            "(Позитивный/Негативный) в соответствии с категорией проверки из чек-листа."
        )

        cat_labels = {"positive": "Позитивные", "negative": "Негативные"}
        grouped = {}
        for item in req.checklist_items:
            area = item.area or "Общее"
            if area not in grouped:
                grouped[area] = []
            grouped[area].append(item)

        lines = [
            "Генерация должна выполняться ТОЛЬКО для следующих выбранных пунктов "
            "чек-листа:\n"
        ]
        for area, items in grouped.items():
            lines.append(f"--- {area} ---")
            for it in items:
                cat_label = cat_labels.get(it.category, it.category)
                lines.append(f"  [{it.id}] {it.text} ({cat_label})")
            lines.append("")
        checklist_context = "\n".join(lines)

        user_prompt = (
            f"Описание задачи:\n{processed_task}\n\n{checklist_context}"
        )
    else:
        user_prompt = f"Описание задачи:\n{processed_task}"

    raw_content = ""
    try:
        response = await client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
            response_format={"type": "json_object"},
        )
        raw_content = response.choices[0].message.content.strip()

        # Парсим JSON
        try:
            parsed = json.loads(raw_content)
        except json.JSONDecodeError:
            return JSONResponse(
                status_code=500,
                content={
                    "error": "Ответ модели не является валидным JSON",
                    "raw_response": raw_content,
                },
            )

        # Извлекаем массив тест-кейсов из любого формата
        test_cases_data = None
        if isinstance(parsed, list):
            test_cases_data = parsed
            logger.info("Модель вернула массив без обёртки")
        elif isinstance(parsed, dict):
            if "test_cases" in parsed and isinstance(parsed["test_cases"], list):
                test_cases_data = parsed["test_cases"]
            else:
                # Ищем первый попавшийся список в значениях словаря
                for key, val in parsed.items():
                    if isinstance(val, list):
                        test_cases_data = val
                        logger.warning(
                            f"Ключ 'test_cases' отсутствует, использован '{key}'"
                        )
                        break

        if test_cases_data is None:
            return JSONResponse(
                status_code=500,
                content={
                    "error": "Не удалось найти массив тест-кейсов в ответе модели",
                    "raw_response": raw_content,
                },
            )

        # Валидируем каждый кейс индивидуально, пропуская невалидные
        valid_cases = []
        for idx, case in enumerate(test_cases_data):
            try:
                validated = TestCaseModel.model_validate(case)
                # Преобразуем поля-списки в строки
                case_dict = {}
                for field_name, alias in zip(
                    [f"field_{i}" for i in range(len(active_fields))], active_fields
                ):
                    value = getattr(validated, field_name)
                    if isinstance(value, list):
                        case_dict[alias] = "\n".join(str(v) for v in value)
                    else:
                        case_dict[alias] = value
                valid_cases.append(case_dict)
            except ValidationError as e:
                logger.warning(f"Тест-кейс #{idx + 1} пропущен: {e}")

        if not valid_cases:
            return JSONResponse(
                status_code=422,
                content={
                    "error": "Ни один тест-кейс не прошёл валидацию",
                    "raw_response": raw_content,
                },
            )

        return {"test_cases": valid_cases}

    except Exception as e:
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"error": f"Ошибка: {str(e)}"})


# ----------- Отдача фронтенда ----------
@app.get("/")
async def read_index():
    return RedirectResponse(url="/static/index.html")
