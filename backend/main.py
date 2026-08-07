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
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, RedirectResponse
from openai import AsyncOpenAI
from pydantic import BaseModel, Field, create_model, ValidationError
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

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
from .database import init_db, get_page_description, get_all_pages, get_pages_descriptions_batch


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    os.makedirs(
        os.path.join(os.path.dirname(__file__), "static", "uploads"), exist_ok=True
    )
    yield


# ----------- FastAPI приложение ----------
app = FastAPI(title="QA Case Generator MVP + Pages", lifespan=lifespan)

# Rate limiter
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS (настройте origins под свои нужды)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # ← замените на конкретные домены в production
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory="backend/static"), name="static")

# ----------- Аутентификация ----------
from .auth import verify_api_key

@app.post("/auth/check")
async def check_auth(api_key: str = Depends(verify_api_key)):
    return {"status": "ok"}

# ----------- Роутеры ----------
from .pages import router as pages_router
from .projects import router as projects_router
from .checklists import router as checklists_router

app.include_router(pages_router)
app.include_router(projects_router)
app.include_router(checklists_router)


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
    names = re.findall(r"\{\{(.+?)\}\}", text)
    if not names:
        return text

    unique_names = list(set(n.strip() for n in names))
    cache = {name: desc for name, desc in get_pages_descriptions_batch(unique_names)}

    def replacer(match):
        name = match.group(1).strip()
        from .database import clean_page_name
        desc = cache.get(clean_page_name(name))
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


def extract_json_list(raw_content: str, expected_key: str = "test_cases") -> tuple[Optional[list], Optional[str]]:
    try:
        parsed = json.loads(raw_content)
    except json.JSONDecodeError:
        return None, "Ответ модели не является валидным JSON"

    if isinstance(parsed, list):
        return parsed, None
    if isinstance(parsed, dict):
        if expected_key in parsed and isinstance(parsed[expected_key], list):
            return parsed[expected_key], None
        for val in parsed.values():
            if isinstance(val, list):
                return val, None
    return None, f"Ключ '{expected_key}' не найден"


def extract_checklist_structure(raw_content: str) -> tuple[Optional[dict], Optional[str]]:
    try:
        parsed = json.loads(raw_content)
    except json.JSONDecodeError:
        return None, "Ответ модели не является валидным JSON"

    if not isinstance(parsed, dict):
        return None, "Ответ модели не является JSON-объектом"

    if "checklist" in parsed and isinstance(parsed["checklist"], dict):
        return parsed["checklist"], None
    if "positive" in parsed or "negative" in parsed:
        return parsed, None
    for val in parsed.values():
        if isinstance(val, dict) and ("positive" in val or "negative" in val):
            return val, None
    return None, "Не удалось найти структуру чек-листа в ответе модели"


# ----------- Глобальные обработчики ошибок ----------
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.detail, "type": "http_error"}
    )

@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    logger.error(f"Необработанная ошибка: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"error": "Внутренняя ошибка сервера", "type": "internal_error"}
    )


# ----------- Эндпоинт генерации чек-листа ----------
@app.post("/generate-checklist")
@limiter.limit("10/minute")
async def generate_checklist(req: GenerateChecklistRequest, request: Request, api_key: str = Depends(verify_api_key)):
    if not req.task_text.strip():
        raise HTTPException(status_code=400, detail="Текст задачи пуст")

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
        logger.info("Сырой ответ чек-листа: %s", raw_content[:1000])

        checklist, error = extract_checklist_structure(raw_content)
        if error:
            raise HTTPException(status_code=500, detail=f"Ошибка парсинга чек-листа: {error}")

        for key in ["positive", "negative"]:
            if key not in checklist or not isinstance(checklist[key], list):
                checklist[key] = []
        if "affected_areas" not in checklist or not isinstance(checklist["affected_areas"], list):
            checklist["affected_areas"] = []

        return {"checklist": checklist}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail="Ошибка при генерации чек-листа")


# ----------- Основной эндпоинт генерации ----------
@app.post("/generate")
@limiter.limit("10/minute")
async def generate_test_cases(req: GenerateRequest, request: Request, api_key: str = Depends(verify_api_key)):
    if not req.task_text.strip():
        raise HTTPException(status_code=400, detail="Текст задачи пуст")
    if not req.fields:
        raise HTTPException(status_code=400, detail="Список полей шаблона пуст")
    if len(req.fields) != len(set(req.fields)):
        raise HTTPException(status_code=400, detail="Названия полей должны быть уникальными")

    processed_task = replace_placeholders(req.task_text)

    active_fields = list(req.fields)
    if req.checklist_items:
        if "Тип" not in active_fields:
            active_fields.append("Тип")

    TestCaseModel = build_dynamic_test_case_model(active_fields)
    fields_list = ", ".join(active_fields)

    # Генерируем пример с актуальными названиями полей
    example_fields = {name: f"<значение поля '{name}'>" for name in active_fields}
    example_fields[active_fields[0]] = "Успешная отправка формы обратной связи"
    if len(active_fields) > 1:
        example_fields[active_fields[1]] = "Пользователь на странице 'Контакты'. Все поля формы пусты."
    if len(active_fields) > 2:
        example_fields[active_fields[2]] = ["Ввести в поле 'Имя' значение 'Иван'", "Нажать кнопку 'Отправить'"]
    if len(active_fields) > 3:
        example_fields[active_fields[3]] = "Появляется сообщение 'Сообщение отправлено'. Форма очищается."
    if "Тип" in active_fields:
        example_fields["Тип"] = "Позитивный"
    example_json = json.dumps({"test_cases": [example_fields]}, ensure_ascii=False, indent=2)

    system_prompt = (
        "## Поля тест-кейсов\n\n"
        "Ответ должен быть JSON-объектом с единственным ключом 'test_cases'. "
        "Значение 'test_cases' — массив объектов.\n\n"
        "Каждый объект тест-кейса содержит ТОЛЬКО указанные поля. "
        "НЕ ИСПОЛЬЗУЙ поля id, title, precondition, steps, expected_result, type, checklist_item_id, "
        "если они не входят в список ниже. "
        "Каждое поле должно быть заполнено строкой или массивом строк (не null, не пустая строка).\n\n"
        f"Обязательные поля: {fields_list}.\n\n"
        "Пример правильного объекта (используй ИМЕННО ЭТИ названия полей):\n"
        f"{example_json}\n\n"
        f"{TEST_CASE_SKILL_PROMPT}\n\n"
        "Оберни ответ в чистый JSON, без markdown-разметки."
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

        user_prompt = f"Описание задачи:\n{processed_task}\n\n{checklist_context}"
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
        logger.info("Сырой ответ генерации: %s", raw_content[:1000])

        test_cases_data, error = extract_json_list(raw_content, "test_cases")
        if error:
            raise HTTPException(status_code=500, detail=f"Ошибка парсинга ответа: {error}")

        logger.info("Ожидаемые поля: %s", active_fields)
        valid_cases = []
        for idx, case in enumerate(test_cases_data):
            logger.info("Сырой тест-кейс #%d: %s", idx + 1, json.dumps(case, ensure_ascii=False))
            try:
                validated = TestCaseModel.model_validate(case)
                case_dict = {}
                for field_name, alias in zip(
                    [f"field_{i}" for i in range(len(active_fields))], active_fields
                ):
                    value = getattr(validated, field_name)
                    if isinstance(value, list):
                        case_dict[alias] = "\n".join(str(v) for v in value)
                    else:
                        case_dict[alias] = value
                logger.info("Валидный тест-кейс #%d: %s", idx + 1, json.dumps(case_dict, ensure_ascii=False))
                valid_cases.append(case_dict)
            except ValidationError as e:
                logger.warning("Тест-кейс #%d пропущен: %s", idx + 1, e)

        if not valid_cases:
            raise HTTPException(status_code=422, detail="Ни один тест-кейс не прошёл валидацию")

        return {"test_cases": valid_cases}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail="Ошибка при генерации тест-кейсов")


# ----------- Отдача фронтенда ----------
@app.get("/")
async def read_index():
    return RedirectResponse(url="/static/index.html")
