import sqlite3
import os
from datetime import datetime

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

def add_or_update_page(name: str, image_path: str, description: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # Если запись с таким именем уже есть – удалим старый файл и перезапишем
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

def get_all_pages():
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("SELECT name, description FROM pages ORDER BY name").fetchall()
    conn.close()
    return [{"name": r[0], "description": r[1]} for r in rows]

def get_page_description(name: str) -> str:
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT description FROM pages WHERE name = ?", (name,)).fetchone()
    conn.close()
    return row[0] if row else ""

def delete_page(name: str) -> bool:
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT image_path FROM pages WHERE name = ?", (name,)).fetchone()
    if row:
        # удаляем файл
        if os.path.exists(row[0]):
            try:
                os.remove(row[0])
            except OSError:
                pass
        conn.execute("DELETE FROM pages WHERE name = ?", (name,))
        conn.commit()
        conn.close()
        return True
    conn.close()
    return False
