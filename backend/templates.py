import os
import shutil
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from .auth import verify_api_key
from .database import (
    create_template,
    delete_template,
    get_project,
    get_template_by_type,
    get_templates_by_project,
)

router = APIRouter(prefix="/projects", tags=["templates"])

# Директория для хранения шаблонов .docx
TEMPLATE_UPLOAD_DIR = os.path.join(
    os.path.dirname(__file__), "static", "uploads", "templates"
)
os.makedirs(TEMPLATE_UPLOAD_DIR, exist_ok=True)


class TemplateResponse(BaseModel):
    id: int
    doc_type: str
    file_path: str


class TemplateListItem(BaseModel):
    doc_type: str
    file_path: str


def _get_template_dir(project_id: int) -> str:
    """Возвращает директорию для хранения шаблонов конкретного проекта."""
    directory = os.path.join(TEMPLATE_UPLOAD_DIR, str(project_id))
    os.makedirs(directory, exist_ok=True)
    return directory


def _is_safe_path(base_dir: str, target_path: str) -> bool:
    """Проверяет, что целевой путь находится внутри base_dir."""
    real_base = os.path.realpath(base_dir)
    real_target = os.path.realpath(target_path)
    return os.path.commonpath([real_base, real_target]) == real_base


@router.post("/{project_id}/templates", response_model=TemplateResponse)
async def upload_template(
    project_id: int,
    doc_type: str = Form(..., min_length=1),
    file: UploadFile = File(...),
    api_key: str = Depends(verify_api_key),
):
    """Загрузить шаблон .docx для проекта."""
    project = get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Проект не найден")

    if not file.filename:
        raise HTTPException(status_code=400, detail="Имя файла не указано")

    suffix = Path(file.filename).suffix.lower()
    if suffix != ".docx":
        raise HTTPException(status_code=400, detail="Поддерживаются только файлы .docx")

    # Проверяем уникальность doc_type в рамках проекта
    if get_template_by_type(project_id, doc_type):
        raise HTTPException(
            status_code=409,
            detail=f"Шаблон с типом '{doc_type}' уже существует в проекте",
        )

    contents = await file.read()
    if not contents:
        raise HTTPException(status_code=400, detail="Загружен пустой файл")

    project_template_dir = _get_template_dir(project_id)
    unique_name = f"{uuid.uuid4().hex}{suffix}"
    file_path = os.path.join(project_template_dir, unique_name)

    with open(file_path, "wb") as buffer:
        buffer.write(contents)

    try:
        template = create_template(project_id, doc_type, file_path)
    except ValueError as exc:
        # Удаляем сохранённый файл, если запись не создалась
        if os.path.exists(file_path):
            os.remove(file_path)
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception:
        if os.path.exists(file_path):
            os.remove(file_path)
        raise

    return template


@router.get("/{project_id}/templates", response_model=list[TemplateListItem])
async def list_templates(project_id: int, api_key: str = Depends(verify_api_key)):
    """Получить список загруженных шаблонов проекта."""
    project = get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Проект не найден")

    templates = get_templates_by_project(project_id)
    return [
        TemplateListItem(doc_type=t["doc_type"], file_path=t["file_path"])
        for t in templates
    ]


@router.delete("/{project_id}/templates/{doc_type}")
async def remove_template(
    project_id: int,
    doc_type: str,
    api_key: str = Depends(verify_api_key),
):
    """Удалить шаблон проекта (запись в БД и файл)."""
    project = get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Проект не найден")

    template = get_template_by_type(project_id, doc_type)
    if not template:
        raise HTTPException(status_code=404, detail="Шаблон не найден")

    file_path = template["file_path"]
    if file_path and _is_safe_path(TEMPLATE_UPLOAD_DIR, file_path) and os.path.exists(file_path):
        try:
            os.remove(file_path)
        except OSError as exc:
            raise HTTPException(
                status_code=500, detail=f"Не удалось удалить файл шаблона: {exc}"
            ) from exc

    if not delete_template(project_id, doc_type):
        raise HTTPException(status_code=404, detail="Шаблон не найден")

    return {"status": "deleted", "doc_type": doc_type}
