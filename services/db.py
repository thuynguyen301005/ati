"""
Lưu user và các project SpecForge vào SQLite (file nằm trong thư mục instance/).
"""
import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List

from config import DATABASE_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL DEFAULT '',
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_projects_user ON projects(user_id, updated_at);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _connect() -> sqlite3.Connection:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.executescript(SCHEMA)
        # DB tạo trước khi có cột name: bổ sung cột.
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(users)")}
        if "name" not in columns:
            conn.execute("ALTER TABLE users ADD COLUMN name TEXT NOT NULL DEFAULT ''")


# ========= USERS =========

def create_user(email: str, password_hash: str, name: str = "") -> int | None:
    """Trả về id user mới, hoặc None nếu email đã tồn tại."""
    try:
        with _connect() as conn:
            cursor = conn.execute(
                "INSERT INTO users (email, name, password_hash, created_at) VALUES (?, ?, ?, ?)",
                (email, name, password_hash, _now()),
            )
            return cursor.lastrowid
    except sqlite3.IntegrityError:
        return None


def get_user_by_email(email: str) -> Dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    return dict(row) if row else None


def get_user(user_id: int) -> Dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute("SELECT id, email, name, created_at FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


# ========= PROJECTS =========

def save_project(user_id: int, project: Dict[str, Any]) -> None:
    """Tạo mới hoặc ghi đè project (giữ nguyên created_at nếu đã có)."""
    now = _now()
    project.setdefault("created_at", now)
    project["updated_at"] = now
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO projects (id, user_id, title, data, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                title = excluded.title, data = excluded.data, updated_at = excluded.updated_at
            WHERE projects.user_id = excluded.user_id
            """,
            (project["id"], user_id, project["title"], json.dumps(project), project["created_at"], now),
        )


def get_project(user_id: int, project_id: str) -> Dict[str, Any] | None:
    """Chỉ trả về project thuộc đúng user đang đăng nhập."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT data FROM projects WHERE id = ? AND user_id = ?", (project_id, user_id)
        ).fetchone()
    return json.loads(row["data"]) if row else None


def list_projects(user_id: int) -> List[Dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, title, created_at, updated_at FROM projects WHERE user_id = ? ORDER BY updated_at DESC",
            (user_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def delete_project(user_id: int, project_id: str) -> bool:
    with _connect() as conn:
        cursor = conn.execute("DELETE FROM projects WHERE id = ? AND user_id = ?", (project_id, user_id))
        return cursor.rowcount > 0
