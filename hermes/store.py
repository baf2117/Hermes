"""Persistencia en SQLite: tareas, historial de mensajes y estado."""
from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    category TEXT NOT NULL,
    urgency TEXT NOT NULL CHECK (urgency IN ('baja', 'media', 'alta')),
    due_at INTEGER,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'done', 'cancelled')),
    notified_at INTEGER,
    source_text TEXT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    completed_at INTEGER
);
CREATE INDEX IF NOT EXISTS idx_tasks_due ON tasks (status, notified_at, due_at);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('user', 'hermes')),
    text TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""

EDITABLE_FIELDS = {"title", "category", "urgency", "due_at", "notified_at"}


@dataclass(frozen=True)
class Task:
    id: int
    title: str
    category: str
    urgency: str
    due_at: int | None
    status: str
    notified_at: int | None


class Store:
    def __init__(self, path: Path | str):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock, self._conn:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(SCHEMA)

    @staticmethod
    def _task(row: sqlite3.Row) -> Task:
        return Task(
            id=row["id"],
            title=row["title"],
            category=row["category"],
            urgency=row["urgency"],
            due_at=row["due_at"],
            status=row["status"],
            notified_at=row["notified_at"],
        )

    def add_task(
        self,
        title: str,
        category: str,
        urgency: str,
        due_at: int | None,
        source_text: str,
        now: int,
    ) -> Task:
        with self._lock, self._conn:
            cursor = self._conn.execute(
                "INSERT INTO tasks (title, category, urgency, due_at, source_text, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (title, category, urgency, due_at, source_text, now, now),
            )
            return self.get_task(int(cursor.lastrowid))  # type: ignore[return-value]

    def get_task(self, task_id: int) -> Task | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return self._task(row) if row else None

    def update_task(self, task_id: int, now: int, **fields: object) -> Task | None:
        unknown = set(fields) - EDITABLE_FIELDS
        if unknown:
            raise ValueError(f"campos no editables: {sorted(unknown)}")
        if fields:
            assignments = ", ".join(f"{name} = ?" for name in fields)
            with self._lock, self._conn:
                self._conn.execute(
                    f"UPDATE tasks SET {assignments}, updated_at = ? WHERE id = ?",
                    (*fields.values(), now, task_id),
                )
        return self.get_task(task_id)

    def set_status(self, task_id: int, status: str, now: int) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE tasks SET status = ?, updated_at = ?, completed_at = ? WHERE id = ?",
                (status, now, now, task_id),
            )

    def pending_tasks(self) -> list[Task]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM tasks WHERE status = 'pending'"
                " ORDER BY due_at IS NULL, due_at,"
                " CASE urgency WHEN 'alta' THEN 0 WHEN 'media' THEN 1 ELSE 2 END, id"
            ).fetchall()
        return [self._task(r) for r in rows]

    def due_unnotified(self, now: int) -> list[Task]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM tasks WHERE status = 'pending' AND notified_at IS NULL"
                " AND due_at IS NOT NULL AND due_at <= ? ORDER BY due_at, id",
                (now,),
            ).fetchall()
        return [self._task(r) for r in rows]

    def log_message(self, role: str, text: str, now: int) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO messages (ts, role, text) VALUES (?, ?, ?)", (now, role, text)
            )

    def recent_messages(self, limit: int) -> list[tuple[str, str]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT role, text FROM messages ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [(r["role"], r["text"]) for r in reversed(rows)]

    def kv_get(self, key: str) -> str | None:
        with self._lock:
            row = self._conn.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def kv_set(self, key: str, value: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO kv (key, value) VALUES (?, ?)"
                " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
