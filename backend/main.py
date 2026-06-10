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
    os.makedirs(os.path.join(os.path.dirname(__file__), "static", "uploads"), exist_ok=True)
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

def build_dynamic_test_case_model(fields: List[str]) -> BaseModel:
    field_defs = {}
    for idx, name in enumerate(fields):
        # Разрешаем строку или список строк
        field_defs[f"field_{idx}"] = (Optional[Union[str, List[str]]], Field(default=None, alias=name))
    model = create_model("DynamicTestCase", **field_defs)
    model.model_config = {"extra": "ignore"}
    return model

# ----------- Замена плейсхолдеров ----------
logger = logging.getLogger(__name__)

def replace_placeholders(text: str) -> str:
    """
    Заменяет {{Имя страницы}} на полное описание из БД.
    Если описание не найдено, оставляет плейсхолдер без изменений.
    """
    def replacer(match):
        name = match.group(1).strip()
        desc = get_page_description(name)
        if desc is not None:
            logger.info(f"Подставлена страница '{name}': {desc[:50]}...")
            return f"[Страница '{name}': {desc}]"
        else:
            logger.warning(f"Страница '{name}' не найдена в БД. Доступные страницы: {[p['name'] for p in get_all_pages()]}")
            return match.group(0)
    return re.sub(r'\{\{(.+?)\}\}', replacer, text)

# ----------- Основной эндпоинт генерации ----------
@app.post("/generate")
async def generate_test_cases(req: GenerateRequest):
    if not req.task_text.strip():
        return JSONResponse(status_code=400, content={"error": "Текст задачи пуст"})
    if not req.fields:
        return JSONResponse(status_code=400, content={"error": "Список полей шаблона пуст"})
    if len(req.fields) != len(set(req.fields)):
        return JSONResponse(status_code=400, content={"error": "Названия полей должны быть уникальными"})

    # Подстановка описаний страниц
    processed_task = replace_placeholders(req.task_text)

    TestCaseModel = build_dynamic_test_case_model(req.fields)
    fields_list = ", ".join(req.fields)

    system_prompt = (
        "Ты — опытный QA-инженер. На основе описания задачи сгенерируй список тест-кейсов. "
        "Ответ должен быть JSON-объектом с единственным ключом 'test_cases'. "
        "Значение 'test_cases' — массив объектов. Каждый объект содержит ТОЛЬКО указанные поля: "
        f"{fields_list}. "
        "Не добавляй других ключей. Оберни ответ в чистый JSON, без markdown-разметки."
    )
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
                content={"error": "Ответ модели не является валидным JSON", "raw_response": raw_content}
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
                        logger.warning(f"Ключ 'test_cases' отсутствует, использован '{key}'")
                        break

        if test_cases_data is None:
            return JSONResponse(
                status_code=500,
                content={"error": "Не удалось найти массив тест-кейсов в ответе модели", "raw_response": raw_content}
            )

        # Валидируем каждый кейс индивидуально, пропуская невалидные
        valid_cases = []
        for idx, case in enumerate(test_cases_data):
            try:
                validated = TestCaseModel.model_validate(case)
                # Преобразуем поля-списки в строки
                case_dict = {}
                for field_name, alias in zip([f"field_{i}" for i in range(len(req.fields))], req.fields):
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
                content={"error": "Ни один тест-кейс не прошёл валидацию", "raw_response": raw_content}
            )

        return {"test_cases": valid_cases}

    except Exception as e:
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"error": f"Ошибка: {str(e)}"}
        )

# ----------- Отдача фронтенда ----------
@app.get("/")
async def read_index():
    return RedirectResponse(url="/static/index.html")
