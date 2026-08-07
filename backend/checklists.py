import json
import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field

from .auth import verify_api_key
from .database import (
    get_requirement_by_id,
    get_checklist_by_id,
    create_checklist_dict,
    update_checklist,
    delete_checklist,
    get_checklists_by_requirement,
    create_testcase,
    get_testcase_by_id,
    update_testcase,
    delete_testcase,
    get_testcases_by_requirement,
)
from .main import client, MODEL

router = APIRouter(tags=["checklists"])

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


def _load_prompt(name: str, fallback: str) -> str:
    path = PROMPTS_DIR / name
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        logger.warning("Файл скилла не найден: %s", path)
        return fallback


CHECKLIST_PROMPT = _load_prompt(
    "checklist_per_ft.md",
    "Ты — опытный QA-инженер. Создай чек-лист проверок в JSON-формате.",
)
TESTCASE_PROMPT = _load_prompt(
    "testcase_from_item.md",
    "Ты — QA-инженер. На основе пункта чек-листа создай детальный тест-кейс в JSON-формате.",
)


# ---------- Pydantic модели ----------

class ChecklistItems(BaseModel):
    items_json: dict


class ChecklistUpdate(BaseModel):
    items_json: dict


class TestcaseUpdate(BaseModel):
    title: Optional[str] = None
    steps: Optional[str] = None
    expected_result: Optional[str] = None
    include_in_pmi: Optional[bool] = None


# ---------- Вспомогательные функции ----------


def _extract_checklist_json(raw_content: str) -> dict:
    """Извлекает и валидирует JSON-чек-лист из ответа модели."""
    try:
        parsed = json.loads(raw_content)
    except json.JSONDecodeError as e:
        raise ValueError(f"Ответ модели не является валидным JSON: {e}") from e

    if not isinstance(parsed, dict):
        raise ValueError("Ответ модели должен быть JSON-объектом")

    if "checklist" not in parsed:
        raise ValueError("В ответе модели отсутствует ключ 'checklist'")

    checklist = parsed["checklist"]
    if not isinstance(checklist, dict):
        raise ValueError("Значение 'checklist' должно быть объектом")

    for key in ("positive", "negative"):
        if key not in checklist or not isinstance(checklist[key], list):
            checklist[key] = []

    return checklist


def _extract_testcase_json(raw_content: str) -> dict:
    """Извлекает и валидирует JSON-тест-кейс из ответа модели."""
    try:
        parsed = json.loads(raw_content)
    except json.JSONDecodeError as e:
        raise ValueError(f"Ответ модели не является валидным JSON: {e}") from e

    if not isinstance(parsed, dict):
        raise ValueError("Ответ модели должен быть JSON-объектом")

    for key in ("title", "steps", "expected_result"):
        if key not in parsed:
            raise ValueError(f"В ответе модели отсутствует ключ '{key}'")

    return parsed


def _steps_to_text(steps: list[str] | str) -> str:
    """Сохраняет шаги как текст с переносами строк."""
    if isinstance(steps, list):
        return "\n".join(str(s) for s in steps)
    return str(steps)


def _find_item_by_id(items: dict, item_id: str) -> tuple[Optional[dict], Optional[str]]:
    """Ищет пункт чек-листа по id и возвращает (пункт, категория)."""
    for category in ("positive", "negative"):
        for item in items.get(category, []):
            if item.get("id") == item_id:
                return item, category
    return None, None


# ---------- Эндпоинты ----------


@router.post("/requirements/{requirement_id}/checklist")
async def generate_checklist(
    requirement_id: int,
    api_key: str = Depends(verify_api_key),
):
    """Сгенерировать чек-лист для функционального требования."""
    requirement = get_requirement_by_id(requirement_id)
    if not requirement:
        raise HTTPException(status_code=404, detail="Требование не найдено")

    prompt_context = f"Требование: {requirement['title']}\n"
    if requirement["code"]:
        prompt_context += f"Код: {requirement['code']}\n"
    prompt_context += f"\nОписание:\n{requirement['description'] or 'Описание отсутствует'}"

    try:
        response = await client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": CHECKLIST_PROMPT},
                {"role": "user", "content": prompt_context},
            ],
            temperature=0.3,
            response_format={"type": "json_object"},
        )
        raw_content = response.choices[0].message.content.strip()
        logger.info("Сырой ответ чек-листа по требованию: %s", raw_content[:1000])

        checklist = _extract_checklist_json(raw_content)
        saved = create_checklist_dict(requirement_id, checklist)
        return saved
    except HTTPException:
        raise
    except ValueError as e:
        logger.error("Ошибка парсинга чек-листа: %s", e)
        raise HTTPException(status_code=500, detail=f"Ошибка парсинга чек-листа: {e}")
    except Exception as e:
        logger.error("Ошибка генерации чек-листа: %s", e)
        raise HTTPException(status_code=500, detail=f"Ошибка генерации чек-листа: {str(e)}")


@router.get("/checklists/{checklist_id}")
async def get_checklist(checklist_id: int, api_key: str = Depends(verify_api_key)):
    """Получить чек-лист по id."""
    checklist = get_checklist_by_id(checklist_id)
    if not checklist:
        raise HTTPException(status_code=404, detail="Чек-лист не найден")
    return checklist


@router.put("/checklists/{checklist_id}")
async def update_checklist_endpoint(
    checklist_id: int,
    body: ChecklistUpdate,
    api_key: str = Depends(verify_api_key),
):
    """Обновить items_json чек-листа."""
    existing = get_checklist_by_id(checklist_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Чек-лист не найден")

    updated = update_checklist(checklist_id, body.items_json)
    if not updated:
        raise HTTPException(status_code=500, detail="Не удалось обновить чек-лист")
    return updated


@router.delete("/checklists/{checklist_id}")
async def remove_checklist(checklist_id: int, api_key: str = Depends(verify_api_key)):
    """Удалить чек-лист и связанные тест-кейсы (каскадно)."""
    existing = get_checklist_by_id(checklist_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Чек-лист не найден")

    if not delete_checklist(checklist_id):
        raise HTTPException(status_code=500, detail="Не удалось удалить чек-лист")
    return {"status": "deleted", "checklist_id": checklist_id}


@router.post("/checklists/{checklist_id}/testcase/{item_id}")
async def generate_testcase(
    checklist_id: int,
    item_id: str,
    api_key: str = Depends(verify_api_key),
):
    """Сгенерировать тест-кейс по пункту чек-листа."""
    checklist = get_checklist_by_id(checklist_id)
    if not checklist:
        raise HTTPException(status_code=404, detail="Чек-лист не найден")

    item, category = _find_item_by_id(checklist["items"], item_id)
    if not item:
        raise HTTPException(status_code=400, detail="Пункт чек-листа не найден")

    requirement = get_requirement_by_id(checklist["requirement_id"])
    requirement_text = ""
    if requirement:
        requirement_text = f"\nТребование: {requirement['title']}\nОписание: {requirement['description'] or '—'}"

    prompt_context = (
        f"Пункт чек-листа ({category}): {item['text']}\n"
        f"Категория: {'позитивная' if category == 'positive' else 'негативная'} проверка"
        f"{requirement_text}"
    )

    try:
        response = await client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": TESTCASE_PROMPT},
                {"role": "user", "content": prompt_context},
            ],
            temperature=0.3,
            response_format={"type": "json_object"},
        )
        raw_content = response.choices[0].message.content.strip()
        logger.info("Сырой ответ тест-кейса: %s", raw_content[:1000])

        testcase = _extract_testcase_json(raw_content)
        saved = create_testcase(
            title=testcase["title"],
            steps=_steps_to_text(testcase["steps"]),
            expected_result=testcase["expected_result"],
            checklist_id=checklist_id,
            checklist_item_id=item_id,
            requirement_id=checklist["requirement_id"],
            include_in_pmi=False,
        )
        return saved
    except HTTPException:
        raise
    except ValueError as e:
        logger.error("Ошибка парсинга тест-кейса: %s", e)
        raise HTTPException(status_code=500, detail=f"Ошибка парсинга тест-кейса: {e}")
    except Exception as e:
        logger.error("Ошибка генерации тест-кейса: %s", e)
        raise HTTPException(status_code=500, detail=f"Ошибка генерации тест-кейса: {str(e)}")


@router.get("/testcases/{testcase_id}")
async def get_testcase(testcase_id: int, api_key: str = Depends(verify_api_key)):
    """Получить тест-кейс по id."""
    testcase = get_testcase_by_id(testcase_id)
    if not testcase:
        raise HTTPException(status_code=404, detail="Тест-кейс не найден")
    return testcase


@router.put("/testcases/{testcase_id}")
async def update_testcase_endpoint(
    testcase_id: int,
    body: TestcaseUpdate,
    api_key: str = Depends(verify_api_key),
):
    """Частично обновить тест-кейс."""
    existing = get_testcase_by_id(testcase_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Тест-кейс не найден")

    updated = update_testcase(
        testcase_id=testcase_id,
        title=body.title,
        steps=body.steps,
        expected_result=body.expected_result,
        include_in_pmi=body.include_in_pmi,
    )
    if not updated:
        raise HTTPException(status_code=500, detail="Не удалось обновить тест-кейс")
    return updated


@router.delete("/testcases/{testcase_id}")
async def remove_testcase(testcase_id: int, api_key: str = Depends(verify_api_key)):
    """Удалить тест-кейс."""
    existing = get_testcase_by_id(testcase_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Тест-кейс не найден")

    if not delete_testcase(testcase_id):
        raise HTTPException(status_code=500, detail="Не удалось удалить тест-кейс")
    return {"status": "deleted", "testcase_id": testcase_id}


@router.get("/requirements/{requirement_id}/coverage")
async def get_requirement_coverage(
    requirement_id: int,
    api_key: str = Depends(verify_api_key),
):
    """Получить сводку покрытия требования чек-листами и тест-кейсами."""
    requirement = get_requirement_by_id(requirement_id)
    if not requirement:
        raise HTTPException(status_code=404, detail="Требование не найдено")

    checklists = get_checklists_by_requirement(requirement_id)
    testcases = get_testcases_by_requirement(requirement_id)

    return {
        "requirement": {
            "id": requirement["id"],
            "code": requirement["code"],
            "title": requirement["title"],
            "description": requirement["description"],
        },
        "checklists": checklists,
        "testcases": [
            {
                "id": tc["id"],
                "title": tc["title"],
                "include_in_pmi": tc["include_in_pmi"],
                "checklist_id": tc["checklist_id"],
                "checklist_item_id": tc["checklist_item_id"],
            }
            for tc in testcases
        ],
        "summary": {
            "checklists_count": len(checklists),
            "testcases_count": len(testcases),
            "pmi_testcases_count": sum(1 for tc in testcases if tc["include_in_pmi"]),
        },
    }
