"""Persistencia en SQLite: tareas, historial de mensajes y estado."""
from __future__ import annotations

import re
import sqlite3
import threading
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    category TEXT NOT NULL,
    urgency TEXT NOT NULL CHECK (urgency IN ('baja', 'media', 'alta')),
    due_at INTEGER,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'done', 'cancelled')),
    notified_at INTEGER,
    repeat_minutes INTEGER,
    parent_id INTEGER REFERENCES tasks (id),
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
CREATE TABLE IF NOT EXISTS llm_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    purpose TEXT NOT NULL,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    cache_read_tokens INTEGER NOT NULL,
    cache_write_tokens INTEGER NOT NULL,
    cost_usd REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_llm_usage_ts ON llm_usage (ts);
CREATE TABLE IF NOT EXISTS facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    created_at INTEGER NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    text, content='messages', content_rowid='id', tokenize='unicode61 remove_diacritics 2'
);
CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts USING fts5(
    text, content='facts', content_rowid='id', tokenize='unicode61 remove_diacritics 2'
);
CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
    INSERT INTO messages_fts (rowid, text) VALUES (new.id, new.text);
END;
CREATE TRIGGER IF NOT EXISTS facts_ai AFTER INSERT ON facts BEGIN
    INSERT INTO facts_fts (rowid, text) VALUES (new.id, new.text);
END;
CREATE TRIGGER IF NOT EXISTS facts_ad AFTER DELETE ON facts BEGIN
    INSERT INTO facts_fts (facts_fts, rowid, text) VALUES ('delete', old.id, old.text);
END;
"""

EDITABLE_FIELDS = {"title", "category", "urgency", "due_at", "notified_at", "repeat_minutes"}

FTS_READY_KEY = "fts_ready"
STOPWORDS = frozenset(
    """
    que cual cuales como cuando donde quien quienes cuanto cuanta cuantos cuantas por para con sin
    una uno unos unas los las del mis tus sus mio mia hay esta este estos estas esa ese esos esas
    soy eres son era fue tengo tiene tienes tenia sabes sabe dime decir recuerdas acuerdas llama
    llaman hermes favor algo sobre pero porque muy mas
    """.split()
)


def fts_query(text: str) -> str:
    """Convierte una frase en una consulta FTS5 segura: solo palabras, unidas con OR."""
    plain = "".join(
        c for c in unicodedata.normalize("NFD", text.lower()) if unicodedata.category(c) != "Mn"
    )
    words = dict.fromkeys(w for w in re.findall(r"\w{3,}", plain) if w not in STOPWORDS)
    return " OR ".join(f'"{w}"*' for w in words)


@dataclass(frozen=True)
class LLMUsage:
    provider: str
    purpose: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: float = 0.0
    model: str = ""


@dataclass(frozen=True)
class Task:
    id: int
    title: str
    category: str
    urgency: str
    due_at: int | None
    status: str
    notified_at: int | None
    repeat_minutes: int | None = None
    parent_id: int | None = None


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
            columns = {row["name"] for row in self._conn.execute("PRAGMA table_info(tasks)")}
            # Bases creadas antes de existir estas columnas.
            for name, definition in (("repeat_minutes", "INTEGER"), ("parent_id", "INTEGER REFERENCES tasks (id)")):
                if name not in columns:
                    self._conn.execute(f"ALTER TABLE tasks ADD COLUMN {name} {definition}")
            if self.kv_get(FTS_READY_KEY) is None:
                # Indexa los mensajes guardados antes de que existiera la búsqueda.
                self._conn.execute("INSERT INTO messages_fts (messages_fts) VALUES ('rebuild')")
                self.kv_set(FTS_READY_KEY, "1")

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
            repeat_minutes=row["repeat_minutes"],
            parent_id=row["parent_id"],
        )

    def add_task(
        self,
        title: str,
        category: str,
        urgency: str,
        due_at: int | None,
        source_text: str,
        now: int,
        repeat_minutes: int | None = None,
        parent_id: int | None = None,
    ) -> Task:
        with self._lock, self._conn:
            cursor = self._conn.execute(
                "INSERT INTO tasks (title, category, urgency, due_at, repeat_minutes, parent_id, source_text,"
                " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (title, category, urgency, due_at, repeat_minutes, parent_id, source_text, now, now),
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

    def reopen(self, task_id: int, now: int) -> None:
        """Devuelve a pendientes una tarea hecha o cancelada por error."""
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE tasks SET status = 'pending', updated_at = ?, completed_at = NULL WHERE id = ?",
                (now, task_id),
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

    def recently_finished(self, since: int, limit: int = 40) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, title, category, status, completed_at, parent_id FROM tasks"
                " WHERE status != 'pending' AND completed_at >= ? ORDER BY completed_at DESC, id DESC LIMIT ?",
                (since, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def subtasks(self, parent_id: int, status: str | None = None) -> list[Task]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM tasks WHERE parent_id = ? AND (? IS NULL OR status = ?) ORDER BY id",
                (parent_id, status, status),
            ).fetchall()
        return [self._task(r) for r in rows]

    def due_repeats(self, now: int) -> list[Task]:
        """Tareas repetitivas ya avisadas cuyo intervalo se cumplió y que siguen pendientes."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM tasks WHERE status = 'pending' AND repeat_minutes IS NOT NULL"
                " AND notified_at IS NOT NULL AND due_at IS NOT NULL AND due_at <= ?"
                " AND notified_at + repeat_minutes * 60 <= ? ORDER BY due_at, id",
                (now, now),
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

    def add_usage(self, usage: LLMUsage, now: int) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO llm_usage (ts, provider, model, purpose, input_tokens, output_tokens,"
                " cache_read_tokens, cache_write_tokens, cost_usd) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    now, usage.provider, usage.model, usage.purpose, usage.input_tokens, usage.output_tokens,
                    usage.cache_read_tokens, usage.cache_write_tokens, usage.cost_usd,
                ),
            )

    def _usage_totals(self, since: int) -> dict[str, dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT provider, COUNT(*) calls, SUM(input_tokens) input, SUM(output_tokens) output,"
            " SUM(cache_read_tokens) cache_read, SUM(cache_write_tokens) cache_write, SUM(cost_usd) cost"
            " FROM llm_usage WHERE ts >= ? GROUP BY provider",
            (since,),
        ).fetchall()
        return {row["provider"]: {key: row[key] for key in row.keys() if key != "provider"} for row in rows}

    def usage_daily(self, since: int) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT date(ts, 'unixepoch', 'localtime') day, provider, COUNT(*) calls,"
                " SUM(input_tokens + cache_read_tokens + cache_write_tokens) input, SUM(output_tokens) output,"
                " SUM(cost_usd) cost FROM llm_usage WHERE ts >= ? GROUP BY day, provider ORDER BY day",
                (since,),
            ).fetchall()
        return [dict(row) for row in rows]

    def usage_by_purpose(self, since: int) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT provider, purpose, COUNT(*) calls,"
                " SUM(input_tokens + cache_read_tokens + cache_write_tokens) input, SUM(output_tokens) output,"
                " SUM(cost_usd) cost FROM llm_usage WHERE ts >= ? GROUP BY provider, purpose ORDER BY input + output DESC",
                (since,),
            ).fetchall()
        return [dict(row) for row in rows]

    def message_history(self, limit: int) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, ts, role, text FROM messages ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def usage_summary(self, day_start: int, month_start: int, recent: int = 8) -> dict[str, Any]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT ts, provider, model, purpose, input_tokens, output_tokens, cache_read_tokens,"
                " cache_write_tokens, cost_usd FROM llm_usage ORDER BY id DESC LIMIT ?",
                (recent,),
            ).fetchall()
            return {
                "today": self._usage_totals(day_start),
                "month": self._usage_totals(month_start),
                "recent": [dict(row) for row in rows],
            }

    def add_fact(self, text: str, now: int) -> int:
        with self._lock, self._conn:
            existing = self._conn.execute(
                "SELECT id FROM facts WHERE lower(text) = lower(?)", (text,)
            ).fetchone()
            if existing:
                return int(existing["id"])
            cursor = self._conn.execute("INSERT INTO facts (text, created_at) VALUES (?, ?)", (text, now))
            return int(cursor.lastrowid)

    def list_facts(self, limit: int = 50) -> list[tuple[int, str]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, text FROM facts ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [(r["id"], r["text"]) for r in rows]

    def delete_fact(self, fact_id: int) -> bool:
        with self._lock, self._conn:
            return self._conn.execute("DELETE FROM facts WHERE id = ?", (fact_id,)).rowcount > 0

    def search_facts(self, text: str, limit: int) -> list[tuple[int, str]]:
        query = fts_query(text)
        if not query:
            return []
        with self._lock:
            rows = self._conn.execute(
                "SELECT f.id, f.text FROM facts_fts JOIN facts f ON f.id = facts_fts.rowid"
                " WHERE facts_fts MATCH ? ORDER BY bm25(facts_fts) LIMIT ?",
                (query, limit),
            ).fetchall()
        return [(r["id"], r["text"]) for r in rows]

    def search_messages(self, text: str, limit: int, skip_latest: int) -> list[tuple[int, str]]:
        """Busca en lo que dijo el usuario; omite lo más reciente, que ya va en el historial."""
        query = fts_query(text)
        if not query:
            return []
        with self._lock:
            rows = self._conn.execute(
                "SELECT m.ts, m.text FROM messages_fts JOIN messages m ON m.id = messages_fts.rowid"
                " WHERE messages_fts MATCH ? AND m.role = 'user' AND m.text NOT LIKE '/%'"
                " AND m.id NOT IN (SELECT id FROM messages ORDER BY id DESC LIMIT ?)"
                " ORDER BY bm25(messages_fts) LIMIT ?",
                (query, skip_latest, limit),
            ).fetchall()
        return [(r["ts"], r["text"]) for r in rows]

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
