"""
FastAPI MVP: генератор тест-кейсов + библиотека страниц (Mistral)
"""
import os
import re
from pathlib import Path
from contextlib import asynccontextmanager
import traceback

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, RedirectResponse
from openai import AsyncOpenAI
from pydantic import BaseModel, Field, create_model, ValidationError
from typing import List, Optional

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
from .database import init_db

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
    field_defs = {
        f"field_{idx}": (Optional[str], Field(default=None, alias=name))
        for idx, name in enumerate(fields)
    }
    model = create_model("DynamicTestCase", **field_defs)
    model.model_config = {"extra": "ignore"}
    return model

def build_response_model(test_case_model: BaseModel) -> BaseModel:
    return create_model(
        "OpenAITestCasesResponse",
        test_cases=(List[test_case_model], Field(default=[])),
    )

# ----------- Замена плейсхолдеров ----------
from .database import get_page_description

def replace_placeholders(text: str) -> str:
    """Подставляет описания страниц из БД вместо {{Имя страницы}}"""
    def replacer(match):
        name = match.group(1).strip()
        desc = get_page_description(name)
        if desc:
            return f"[Описание страницы '{name}': {desc}]"
        return match.group(0)  # оставляем как есть, если не найдено
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
    ResponseModel = build_response_model(TestCaseModel)
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
        parsed = raw_content  # JSON string
        import json
        parsed = json.loads(parsed)
        validated = ResponseModel.model_validate(parsed)
        test_cases = [tc.model_dump(by_alias=True) for tc in validated.test_cases]
        return {"test_cases": test_cases}
    except json.JSONDecodeError:
        return JSONResponse(
            status_code=500,
            content={"error": "Ответ модели не является валидным JSON", "raw_response": raw_content}
        )
    except ValidationError as e:
        return JSONResponse(
            status_code=422,
            content={"error": "Структура ответа не соответствует ожидаемой", "details": e.errors(), "raw_response": raw_content}
        )
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
