"""
FastAPI MVP: генератор тест-кейсов с динамической Pydantic-схемой для ответа OpenAI
"""
import json
import os
import sys
from pathlib import Path
from typing import List

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from openai import AsyncOpenAI
from pydantic import BaseModel, Field, create_model, ConfigDict, ValidationError

# Принудительно использовать UTF-8 для всего ввода-вывода
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr.encoding != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8')
os.environ["PYTHONIOENCODING"] = "utf-8"

# Загрузка переменных окружения
env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

PROVIDER = os.getenv("LLM_PROVIDER", "openai").lower()
if PROVIDER == "groq":
    api_key = os.getenv("GROQ_API_KEY")
    base_url = "https://api.groq.com/openai/v1"
    default_model = "llama-3.1-8b-instant"
elif PROVIDER == "mistral":
    api_key = os.getenv("MISTRAL_API_KEY")
    base_url = "https://api.mistral.ai/v1"
    default_model = "open-mistral-nemo"
elif PROVIDER == "openai":
    api_key = os.getenv("OPENAI_API_KEY")
    base_url = None
    default_model = "gpt-4o-mini"
else:
    raise RuntimeError(
        f"Неизвестный LLM_PROVIDER '{PROVIDER}'. Допустимые: openai, groq, mistral"
    )

if not api_key:
    raise RuntimeError(
        f"API-ключ для провайдера '{PROVIDER}' не найден. Проверьте .env файл."
    )

client = AsyncOpenAI(
    api_key=api_key,
    base_url=base_url,
)

app = FastAPI(title="QA Case Generator MVP")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

static_dir = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


class GenerateRequest(BaseModel):
    task_text: str
    fields: List[str]   # например: ["Название", "Предусловия", ...]


def build_dynamic_test_case_model(fields: List[str]) -> BaseModel:
    """
    Создаёт Pydantic-модель для одного тест-кейса с заданным набором полей.
    Используем Field(alias=...) для поддержки произвольных имён (в т.ч. с пробелами).
    """
    field_defs = {}
    for idx, field_name in enumerate(fields):
        # Имя внутреннего поля не может содержать пробелы, поэтому используем field_0, field_1...
        field_defs[f"field_{idx}"] = (str, Field(alias=field_name))
    model = create_model("DynamicTestCase", __config__=ConfigDict(extra='forbid'), **field_defs)
    return model


def build_response_model(test_case_model: BaseModel) -> BaseModel:
    """
    Оборачивает список тест-кейсов в модель верхнего уровня с ключом "test_cases".
    """
    return create_model(
        "OpenAITestCasesResponse",
        test_cases=(List[test_case_model], Field(default=[])),
    )


@app.post("/generate")
async def generate_test_cases(req: GenerateRequest):
    """
    Принимает текст задачи и список полей, возвращает массив тест-кейсов.
    """
    if not req.task_text.strip():
        return JSONResponse(status_code=400, content={"error": "Текст задачи пуст"})
    if not req.fields:
        return JSONResponse(status_code=400, content={"error": "Список полей шаблона пуст"})

    # Строим динамические Pydantic-схемы
    TestCaseModel = build_dynamic_test_case_model(req.fields)
    ResponseModel = build_response_model(TestCaseModel)

    # Строгий промпт с указанием вернуть объект {"test_cases": [...]}
    fields_list = ", ".join(req.fields)
    system_prompt = (
        "Ты — опытный QA-инженер. На основе описания задачи сгенерируй список тест-кейсов. "
        "Ответ должен быть JSON-объектом с единственным ключом 'test_cases'. "
        "Значение 'test_cases' — массив объектов. Каждый объект содержит ТОЛЬКО указанные поля: "
        f"{fields_list}. "
        "Не добавляй других ключей. Оберни ответ в чистый JSON, без markdown-разметки."
        "При составлении 'Ожидаемого результата' запрещено использовать общие фразы вроде 'Система работает корректно'"
        "или 'Пользователь видит страницу'. Ожидаемый результат должен быть атомарным и описывать:"
        "Изменение UI-элементов (изменение цвета, блокировка/разблокировка,"
        "появление/исчезновение элементов из описания страницы)."
        "Изменение данных (какие конкретно цифры/текст обновились)."
        "Редиректы и URL (если применимо)"
    )
    user_prompt = f"Описание задачи:\n{req.task_text}"

    try:
        response = await client.chat.completions.create(
            model=default_model,          # используем модель провайдера из .env
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
            response_format={"type": "json_object"},   # принудительный JSON
        )

        raw_content = response.choices[0].message.content.strip()
        parsed = json.loads(raw_content)

        # Валидация через динамическую Pydantic-схему
        validated = ResponseModel.model_validate(parsed)
        test_cases = [
            tc.model_dump(by_alias=True) for tc in validated.test_cases
        ]

        return {"test_cases": test_cases}

    except json.JSONDecodeError:
        return JSONResponse(
            status_code=500,
            content={
                "error": "Ответ модели не является валидным JSON",
                "raw_response": raw_content,
            },
        )
    except ValidationError as e:
        return JSONResponse(
            status_code=422,
            content={
                "error": "Структура ответа не соответствует ожидаемой схеме",
                "details": e.errors(),
                "raw_response": raw_content,
            },
        )
    except Exception as e:
        # В production стоит логировать ошибку, пользователю – общее сообщение
        return JSONResponse(
            status_code=500,
            content={"error": "Внутренняя ошибка сервера при генерации тест-кейсов"},
        )


@app.get("/")
async def read_index():
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/static/index.html")
