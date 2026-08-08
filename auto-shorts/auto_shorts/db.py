import sqlite3
from pathlib import Path
from typing import Optional, Dict, Any, List


def init_db(db_path: str) -> None:
    p = Path(db_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        """
    CREATE TABLE IF NOT EXISTS projects (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        source TEXT,
        status TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """
    )
    cur.execute(
        """
    CREATE TABLE IF NOT EXISTS clips (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER,
        start REAL,
        end REAL,
        file TEXT,
        score REAL,
        reason TEXT
    )
    """
    )
    conn.commit()
    conn.close()


def create_project(db_path: str, name: str, source: str) -> int:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("INSERT INTO projects (name, source, status) VALUES (?, ?, ?)", (name, source, "created"))
    pid = cur.lastrowid
    conn.commit()
    conn.close()
    return pid


def update_project_status(db_path: str, project_id: int, status: str) -> None:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("UPDATE projects SET status = ? WHERE id = ?", (status, project_id))
    conn.commit()
    conn.close()


def add_clip(db_path: str, project_id: int, start: float, end: float, file: str, score: float, reason: str) -> None:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO clips (project_id, start, end, file, score, reason) VALUES (?, ?, ?, ?, ?, ?)",
        (project_id, start, end, file, score, reason),
    )
    conn.commit()
    conn.close()


def get_project(db_path: str, project_id: int) -> Optional[Dict[str, Any]]:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT id, name, source, status, created_at FROM projects WHERE id = ?", (project_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    return {"id": row[0], "name": row[1], "source": row[2], "status": row[3], "created_at": row[4]}


def list_projects(db_path: str) -> List[Dict[str, Any]]:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT id, name, source, status, created_at FROM projects ORDER BY id DESC")
    rows = cur.fetchall()
    conn.close()
    return [{"id": r[0], "name": r[1], "source": r[2], "status": r[3], "created_at": r[4]} for r in rows]
