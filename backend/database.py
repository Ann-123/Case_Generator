import sqlite3
import os
import logging
import re
import json
from typing import Optional

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(__file__), "pages.db")
UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "static", "uploads")
UPLOAD_DIR = os.path.realpath(UPLOAD_DIR)


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    c = conn.cursor()

    # Существующая таблица страниц
    c.execute("""
        CREATE TABLE IF NOT EXISTS pages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            image_path TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Проекты
    c.execute("""
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            tz_text TEXT NOT NULL DEFAULT '',
            tz_filename TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Требования (иерархическое дерево ЧТЗ)
    c.execute("""
        CREATE TABLE IF NOT EXISTS requirements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            parent_id INTEGER,
            code TEXT,
            title TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            section_path TEXT NOT NULL DEFAULT '',
            sort_order INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
            FOREIGN KEY (parent_id) REFERENCES requirements(id) ON DELETE CASCADE
        )
    """)

    # Чек-листы, привязанные к требованию
    c.execute("""
        CREATE TABLE IF NOT EXISTS checklists (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            requirement_id INTEGER NOT NULL,
            items_json TEXT NOT NULL DEFAULT '[]',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (requirement_id) REFERENCES requirements(id) ON DELETE CASCADE
        )
    """)

    # Тест-кейсы, привязанные к чек-листам и требованиям
    c.execute("""
        CREATE TABLE IF NOT EXISTS testcases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            checklist_item_id TEXT,
            checklist_id INTEGER,
            requirement_id INTEGER,
            title TEXT NOT NULL,
            steps TEXT NOT NULL DEFAULT '',
            expected_result TEXT NOT NULL DEFAULT '',
            include_in_pmi INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (checklist_id) REFERENCES checklists(id) ON DELETE CASCADE,
            FOREIGN KEY (requirement_id) REFERENCES requirements(id) ON DELETE CASCADE
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
    name = clean_page_name(name)
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT image_path FROM pages WHERE name = ?", (name,)).fetchone()
    if row:
        file_path = os.path.realpath(row[0])
        if os.path.commonpath([file_path, UPLOAD_DIR]) == UPLOAD_DIR and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except OSError as e:
                logger.error(f"Не удалось удалить файл {file_path}: {e}")
    conn.execute(
        "INSERT OR REPLACE INTO pages (name, image_path, description, created_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
        (name, image_path, description),
    )
    conn.commit()
    conn.close()
    return True

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
        file_path = os.path.realpath(row[0])  # реальный путь
        # Проверяем, что файл находится внутри UPLOAD_DIR
        if os.path.commonpath([file_path, UPLOAD_DIR]) != UPLOAD_DIR:
            conn.close()
            logger.error(f"Попытка удаления файла вне UPLOAD_DIR: {file_path}")
            return False  # или выбросить исключение

        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except OSError as e:
                logger.error(f"Не удалось удалить файл {file_path}: {e}")
        conn.execute("DELETE FROM pages WHERE name = ?", (name,))
        conn.commit()
        conn.close()
        return True
    conn.close()
    return False


# ---------- CRUD для проектов ----------

def create_project(name: str) -> dict:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    cursor = conn.execute(
        "INSERT INTO projects (name) VALUES (?) RETURNING id, name, created_at",
        (name,),
    )
    row = cursor.fetchone()
    conn.commit()
    conn.close()
    return {"id": row[0], "name": row[1], "created_at": row[2]}


def get_projects() -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT id, name, created_at FROM projects ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return [{"id": r[0], "name": r[1], "created_at": r[2]} for r in rows]


def get_project(project_id: int) -> Optional[dict]:
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT id, name, tz_text, tz_filename, created_at FROM projects WHERE id = ?",
        (project_id,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    return {
        "id": row[0],
        "name": row[1],
        "tz_text": row[2],
        "tz_filename": row[3],
        "created_at": row[4],
    }


def update_project_tz(project_id: int, tz_text: str, tz_filename: Optional[str] = None) -> dict:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    params = [tz_text]
    query = "UPDATE projects SET tz_text = ?"
    if tz_filename is not None:
        query += ", tz_filename = ?"
        params.append(tz_filename)
    query += " WHERE id = ?"
    params.append(project_id)
    conn.execute(query, params)
    conn.commit()
    conn.close()
    return get_project(project_id)


def delete_project(project_id: int) -> bool:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    cursor = conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    conn.commit()
    conn.close()
    return cursor.rowcount > 0


# ---------- CRUD для требований (ЧТЗ) ----------

def _build_tree(rows: list[dict]) -> list[dict]:
    """Преобразует плоский список требований во вложенное дерево."""
    by_id: dict[int, dict] = {}
    roots: list[dict] = []
    for row in rows:
        node = dict(row)
        node["children"] = []
        by_id[node["id"]] = node
    for row in rows:
        node = by_id[row["id"]]
        if row["parent_id"] is None:
            roots.append(node)
        else:
            parent = by_id.get(row["parent_id"])
            if parent:
                parent["children"].append(node)
    return roots


def create_requirement(
    project_id: int,
    title: str,
    description: str = "",
    code: Optional[str] = None,
    parent_id: Optional[int] = None,
    section_path: str = "",
    sort_order: int = 0,
) -> int:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    cursor = conn.execute(
        """
        INSERT INTO requirements
        (project_id, parent_id, code, title, description, section_path, sort_order)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        RETURNING id
        """,
        (project_id, parent_id, code, title, description, section_path, sort_order),
    )
    req_id = cursor.fetchone()[0]
    conn.commit()
    conn.close()
    return req_id


def get_requirements_by_project(project_id: int) -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT id, project_id, parent_id, code, title, description, section_path, sort_order
        FROM requirements
        WHERE project_id = ?
        ORDER BY sort_order, id
        """,
        (project_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_requirements_tree(project_id: int) -> list[dict]:
    rows = get_requirements_by_project(project_id)
    return _build_tree(rows)


def delete_requirements_by_project(project_id: int) -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("DELETE FROM requirements WHERE project_id = ?", (project_id,))
    conn.commit()
    conn.close()


# ---------- CRUD для чек-листов ----------

def create_checklist(requirement_id: int, items: list[dict]) -> dict:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    cursor = conn.execute(
        "INSERT INTO checklists (requirement_id, items_json) VALUES (?, ?) RETURNING id, requirement_id, items_json, created_at",
        (requirement_id, json.dumps(items, ensure_ascii=False)),
    )
    row = cursor.fetchone()
    conn.commit()
    conn.close()
    return {
        "id": row[0],
        "requirement_id": row[1],
        "items": json.loads(row[2]),
        "created_at": row[3],
    }


def get_checklists_by_requirement(requirement_id: int) -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT id, requirement_id, items_json, created_at FROM checklists WHERE requirement_id = ?",
        (requirement_id,),
    ).fetchall()
    conn.close()
    return [
        {
            "id": r[0],
            "requirement_id": r[1],
            "items": json.loads(r[2]),
            "created_at": r[3],
        }
        for r in rows
    ]


# ---------- CRUD для тест-кейсов ----------

def create_testcase(
    title: str,
    steps: str = "",
    expected_result: str = "",
    checklist_id: Optional[int] = None,
    checklist_item_id: Optional[str] = None,
    requirement_id: Optional[int] = None,
    include_in_pmi: bool = False,
) -> dict:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    cursor = conn.execute(
        """
        INSERT INTO testcases
        (checklist_item_id, checklist_id, requirement_id, title, steps, expected_result, include_in_pmi)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        RETURNING id, checklist_item_id, checklist_id, requirement_id, title, steps, expected_result, include_in_pmi, created_at
        """,
        (
            checklist_item_id,
            checklist_id,
            requirement_id,
            title,
            steps,
            expected_result,
            int(include_in_pmi),
        ),
    )
    row = cursor.fetchone()
    conn.commit()
    conn.close()
    return {
        "id": row[0],
        "checklist_item_id": row[1],
        "checklist_id": row[2],
        "requirement_id": row[3],
        "title": row[4],
        "steps": row[5],
        "expected_result": row[6],
        "include_in_pmi": bool(row[7]),
        "created_at": row[8],
    }


def get_testcases_by_requirement(requirement_id: int) -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        """
        SELECT id, checklist_item_id, checklist_id, requirement_id, title, steps, expected_result, include_in_pmi, created_at
        FROM testcases
        WHERE requirement_id = ?
        ORDER BY id
        """,
        (requirement_id,),
    ).fetchall()
    conn.close()
    return [
        {
            "id": r[0],
            "checklist_item_id": r[1],
            "checklist_id": r[2],
            "requirement_id": r[3],
            "title": r[4],
            "steps": r[5],
            "expected_result": r[6],
            "include_in_pmi": bool(r[7]),
            "created_at": r[8],
        }
        for r in rows
    ]
