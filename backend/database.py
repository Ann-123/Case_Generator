import sqlite3
import os
import logging
import re

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(__file__), "pages.db")

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS pages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            image_path TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()
    logger.info("Database pages.db initialized")

def clean_page_name(raw_name: str) -> str:
    cleaned = re.sub(r'[^\w\s\-]', '', raw_name, flags=re.UNICODE)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned.lower()

def add_or_update_page(name: str, image_path: str, description: str):
    name = clean_page_name(name)  # очищаем перед записью
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # Удаляем старый файл если есть
    old = c.execute("SELECT image_path FROM pages WHERE name = ?", (name,)).fetchone()
    if old and os.path.exists(old[0]):
        try:
            os.remove(old[0])
        except OSError:
            pass
    c.execute("""
        INSERT OR REPLACE INTO pages (name, image_path, description, created_at)
        VALUES (?, ?, ?, CURRENT_TIMESTAMP)
    """, (name, image_path, description))
    conn.commit()
    conn.close()
    logger.info(f"Page '{name}' saved with description: {description[:500]}...")

def get_all_pages():
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("SELECT name, description FROM pages ORDER BY name").fetchall()
    conn.close()
    return [{"name": r[0], "description": r[1]} for r in rows]


# В файле database.py
def get_page_description(name: str) -> str | None:
    """Возвращает описание страницы, игнорируя регистр и невидимые символы."""
    # Используем ту же самую функцию очистки, что и при сохранении
    cleaned_name = clean_page_name(name)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.execute(
        "SELECT description FROM pages WHERE name = ?",
        (cleaned_name,)
    )
    row = cursor.fetchone()
    conn.close()
    if row:
        return row[0]
    return None

def get_pages_descriptions_batch(names: list[str]) -> list[tuple[str, str]]:
    if not names:
        return []
    cleaned = [clean_page_name(n) for n in names]
    placeholders = ','.join(['?'] * len(cleaned))
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.execute(
        f"SELECT name, description FROM pages WHERE name IN ({placeholders})",
        cleaned
    )
    result = cursor.fetchall()
    conn.close()
    return result


def delete_page(name: str) -> bool:
    name = clean_page_name(name)
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT image_path FROM pages WHERE name = ?", (name,)).fetchone()
    if row:
        if os.path.exists(row[0]):
            try:
                os.remove(row[0])
            except OSError:
                pass
        conn.execute("DELETE FROM pages WHERE name = ?", (name,))
        conn.commit()
        conn.close()
        logger.info(f"Page '{name}' deleted")
        return True
    conn.close()
    return False
