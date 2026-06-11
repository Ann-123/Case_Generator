import os
import base64
import shutil
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from .database import add_or_update_page, get_all_pages, delete_page, clean_page_name
from openai import AsyncOpenAI
import logging
import re

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/pages", tags=["pages"])

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "static", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Импортируем глобальный клиент из main
from .main import client, VISION_MODEL

@router.post("/upload")
async def upload_page(
    file: UploadFile = File(...),
    name: str = Form("")
):
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(400, "Файл должен быть изображением")
    if not name or not name.strip():
        raise HTTPException(400, "Имя страницы обязательно")

    name = clean_page_name(name)
    if not name:
        raise HTTPException(400, "Имя страницы не должно быть пустым после очистки")
    # Сохраняем файл
    ext = os.path.splitext(file.filename)[1] or ".png"
    filename = f"{name.replace(' ', '_')}_{os.urandom(4).hex()}{ext}"
    file_path = os.path.join(UPLOAD_DIR, filename)

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    # Читаем и кодируем в base64
    with open(file_path, "rb") as f:
        image_data = base64.b64encode(f.read()).decode("utf-8")

    # Отправляем в Mistral vision
    try:
        response = await client.chat.completions.create(
            model=VISION_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Кратко опиши эту страницу интерфейса на русском языке:"
                                                 "ключевые элементы, кнопки. Описывай каждый элемент слева направо."
                                                 "Сверху вниз. Наименованиие элемента должно быть в ковычках,"
                                                 "без дополнительных символов "
                                                 "Описание должно начинаться с: 'на странице расположены элементы: ... '"},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_data}"}}
                    ]
                }
            ],
            max_tokens=1000,
            temperature=0.3
        )
        description = response.choices[0].message.content.strip()
    except Exception as e:
        # Ошибка при распознавании – удаляем сохранённый файл
        if os.path.exists(file_path):
            os.remove(file_path)
        logger.error(f"Vision API error: {e}")
        raise HTTPException(500, f"Ошибка распознавания изображения: {str(e)}")

    # Сохраняем в БД
    add_or_update_page(name, file_path, description)
    return {"status": "ok", "name": name, "description": description}

@router.get("/list")
async def list_pages():
    return get_all_pages()

@router.delete("/{name}")
async def remove_page(name: str):
    if not delete_page(name):
        raise HTTPException(404, "Страница не найдена")
    return {"status": "deleted"}
