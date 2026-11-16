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
CREATE TABLE IF NOT EXISTS emails (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    gmail_id TEXT NOT NULL UNIQUE,
    ts INTEGER NOT NULL,
    sender TEXT NOT NULL,
    subject TEXT NOT NULL,
    summary TEXT NOT NULL,
    important INTEGER NOT NULL,
    task_title TEXT,
    task_category TEXT,
    task_due_at INTEGER,
    notified_at INTEGER,
    handled INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS list_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    list TEXT NOT NULL,
    text TEXT NOT NULL,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token_hash TEXT NOT NULL UNIQUE,
    created_at INTEGER NOT NULL,
    last_seen INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    label TEXT NOT NULL,
    ip TEXT NOT NULL,
    approved INTEGER NOT NULL,
    revoked_at INTEGER
);
CREATE TABLE IF NOT EXISTS receipts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    merchant TEXT NOT NULL,
    day TEXT NOT NULL,
    total REAL NOT NULL,
    currency TEXT NOT NULL,
    category TEXT NOT NULL,
    warranty_until TEXT,
    items TEXT NOT NULL DEFAULT '[]',
    photo TEXT,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS receipts_day ON receipts (day);
CREATE TABLE IF NOT EXISTS lists (
    name TEXT PRIMARY KEY,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS dates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    name TEXT NOT NULL,
    month INTEGER NOT NULL,
    day INTEGER NOT NULL,
    year INTEGER,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS habits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    remind_at TEXT,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS habit_log (
    habit_id INTEGER NOT NULL,
    day TEXT NOT NULL,
    PRIMARY KEY (habit_id, day)
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
CREATE TRIGGER IF NOT EXISTS facts_au AFTER UPDATE OF text ON facts BEGIN
    INSERT INTO facts_fts (facts_fts, rowid, text) VALUES ('delete', old.id, old.text);
    INSERT INTO facts_fts (rowid, text) VALUES (new.id, new.text);
END;
"""

EDITABLE_FIELDS = {
    "title", "category", "urgency", "due_at", "notified_at", "repeat_minutes", "deadline_at", "deadline_notified_at",
    "deadline_warned",
}
DAY_SECONDS = 86400


def warn_stage(deadline_at: int | None, now: int) -> int:
    """Avisos previos al vencimiento que ya no tocan: 0 ninguno, 1 el de un día antes, 2 también el de una hora.

    Una tarea que nace a pocas horas de vencer no debe avisar «falta un día» en ese mismo momento.
    """
    if deadline_at is None:
        return 0
    remaining = deadline_at - now
    return 2 if remaining <= 3600 else 1 if remaining <= DAY_SECONDS else 0

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
    deadline_at: int | None = None  # Hora de vencimiento; due_at es la hora de inicio (el aviso).
    deadline_notified_at: int | None = None
    kind: str = "task"  # "waiting": algo que el dueño espera de otra persona; el aviso pregunta si ya llegó.
    deadline_warned: int = 0
    completed_at: int | None = None  # Cuándo se terminó o se canceló.
    deleted_at: int | None = None  # Borrada: sigue en la base, pero ya no aparece en ninguna parte.

    @property
    def overdue_from(self) -> int | None:
        """Desde cuándo cuenta como vencida: el vencimiento si lo tiene; si no, el inicio."""
        return self.deadline_at if self.deadline_at is not None else self.due_at


@dataclass(frozen=True)
class MailNote:
    """Lo que Hermes guarda de un correo: remitente, asunto y el resumen del modelo. Nunca el texto completo."""

    id: int
    gmail_id: str
    ts: int
    sender: str
    subject: str
    summary: str
    important: bool
    task_title: str | None = None
    task_category: str | None = None
    task_due_at: int | None = None
    notified_at: int | None = None
    handled: bool = False
    account: str = "personal"  # De qué cuenta de correo vino.


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
            for name, definition in (
                ("repeat_minutes", "INTEGER"),
                ("parent_id", "INTEGER REFERENCES tasks (id)"),
                ("deadline_at", "INTEGER"),
                ("deadline_notified_at", "INTEGER"),
                ("kind", "TEXT NOT NULL DEFAULT 'task'"),
                ("deadline_warned", "INTEGER NOT NULL DEFAULT 0"),
                ("deleted_at", "INTEGER"),
                ("deleted_from", "TEXT"),
            ):
                if name not in columns:
                    self._conn.execute(f"ALTER TABLE tasks ADD COLUMN {name} {definition}")
            if "account" not in {row["name"] for row in self._conn.execute("PRAGMA table_info(emails)")}:
                self._conn.execute("ALTER TABLE emails ADD COLUMN account TEXT NOT NULL DEFAULT 'personal'")
            if "done" not in {row["name"] for row in self._conn.execute("PRAGMA table_info(list_items)")}:
                self._conn.execute("ALTER TABLE list_items ADD COLUMN done INTEGER NOT NULL DEFAULT 0")
            # Las listas creadas antes de poder existir vacías: se registran por sus elementos.
            self._conn.execute(
                "INSERT OR IGNORE INTO lists (name, created_at) SELECT list, MIN(created_at) FROM list_items GROUP BY list"
            )
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
            deadline_at=row["deadline_at"],
            deadline_notified_at=row["deadline_notified_at"],
            kind=row["kind"],
            deadline_warned=row["deadline_warned"],
            completed_at=row["completed_at"],
            deleted_at=row["deleted_at"],
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
        deadline_at: int | None = None,
        kind: str = "task",
    ) -> Task:
        with self._lock, self._conn:
            cursor = self._conn.execute(
                "INSERT INTO tasks (title, category, urgency, due_at, repeat_minutes, parent_id, deadline_at,"
                " source_text, created_at, updated_at, kind, deadline_warned) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    title, category, urgency, due_at, repeat_minutes, parent_id, deadline_at, source_text, now, now,
                    kind, warn_stage(deadline_at, now),
                ),
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
        if "deadline_at" in fields and "deadline_warned" not in fields:
            fields["deadline_warned"] = warn_stage(fields["deadline_at"], now)  # type: ignore[arg-type]
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

    def finished_tasks(self, limit: int = 300) -> list[Task]:
        """Tareas hechas o canceladas, con toda su información, de la más reciente a la más antigua."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM tasks WHERE status != 'pending' AND deleted_at IS NULL"
                " ORDER BY completed_at DESC, id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._task(r) for r in rows]

    def delete_task(self, task_id: int, now: int) -> int:
        """Borrado lógico de una tarea y sus pasos: dejan de aparecer y de avisar, pero se pueden recuperar."""
        with self._lock, self._conn:
            return self._conn.execute(
                "UPDATE tasks SET deleted_from = status, deleted_at = ?, updated_at = ?,"
                " completed_at = COALESCE(completed_at, ?),"
                " status = CASE WHEN status = 'pending' THEN 'cancelled' ELSE status END"
                " WHERE (id = ? OR parent_id = ?) AND deleted_at IS NULL",
                (now, now, now, task_id, task_id),
            ).rowcount

    def restore_task(self, task_id: int, now: int) -> bool:
        """Deshace un borrado: la tarea y los pasos que se borraron con ella vuelven a como estaban."""
        with self._lock, self._conn:
            row = self._conn.execute("SELECT deleted_at FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if row is None or row["deleted_at"] is None:
                return False
            self._conn.execute(
                "UPDATE tasks SET status = COALESCE(deleted_from, status),"
                " completed_at = CASE WHEN deleted_from = 'pending' THEN NULL ELSE completed_at END,"
                " deleted_at = NULL, deleted_from = NULL, updated_at = ?"
                " WHERE (id = ? OR parent_id = ?) AND deleted_at = ?",
                (now, task_id, task_id, row["deleted_at"]),
            )
            return True

    def pending_tasks(self) -> list[Task]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM tasks WHERE status = 'pending'"
                " ORDER BY COALESCE(due_at, deadline_at) IS NULL, COALESCE(due_at, deadline_at),"
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
                " WHERE status != 'pending' AND deleted_at IS NULL AND completed_at >= ?"
                " ORDER BY completed_at DESC, id DESC LIMIT ?",
                (since, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def subtasks(self, parent_id: int, status: str | None = None) -> list[Task]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM tasks WHERE parent_id = ? AND (? IS NULL OR status = ?) AND deleted_at IS NULL ORDER BY id",
                (parent_id, status, status),
            ).fetchall()
        return [self._task(r) for r in rows]

    def due_deadlines(self, now: int) -> list[Task]:
        """Tareas pendientes cuya hora de vencimiento pasó y que aún no se avisaron."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM tasks WHERE status = 'pending' AND deadline_notified_at IS NULL"
                " AND deadline_at IS NOT NULL AND deadline_at <= ? ORDER BY deadline_at, id",
                (now,),
            ).fetchall()
        return [self._task(r) for r in rows]

    def deadline_warnings(self, now: int) -> list[Task]:
        """Tareas que vencen dentro de un día y a las que todavía les falta algún aviso previo."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM tasks WHERE status = 'pending' AND deadline_at IS NOT NULL AND deadline_at > ?"
                " AND deadline_at - ? <= ? AND deadline_warned < 2 ORDER BY deadline_at, id",
                (now, DAY_SECONDS, now),
            ).fetchall()
        return [self._task(r) for r in rows]

    def stale_tasks(self, before: int, limit: int = 5) -> list[Task]:
        """Tareas sin fecha que nadie ha tocado desde `before`: candidatas a posponer o cancelar."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM tasks WHERE status = 'pending' AND parent_id IS NULL AND kind = 'task'"
                " AND due_at IS NULL AND deadline_at IS NULL AND updated_at < ? ORDER BY updated_at, id LIMIT ?",
                (before, limit),
            ).fetchall()
        return [self._task(r) for r in rows]

    def finished_count(self, since: int, status: str = "done") -> int:
        with self._lock:
            return int(
                self._conn.execute(
                    "SELECT COUNT(*) FROM tasks WHERE status = ? AND completed_at >= ?", (status, since)
                ).fetchone()[0]
            )

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

    def edit_fact(self, fact_id: int, text: str) -> str | None:
        """Corrige un dato: "ok", "duplicate" si ya hay otro igual, o None si no existe. La búsqueda se actualiza sola."""
        with self._lock, self._conn:
            if self._conn.execute("SELECT 1 FROM facts WHERE id = ?", (fact_id,)).fetchone() is None:
                return None
            # Se compara aquí y no en SQL: SQLite no pasa a minúsculas las letras con tilde.
            others = self._conn.execute("SELECT text FROM facts WHERE id != ?", (fact_id,)).fetchall()
            if any(row["text"].casefold() == text.casefold() for row in others):
                return "duplicate"
            self._conn.execute("UPDATE facts SET text = ? WHERE id = ?", (text, fact_id))
            return "ok"

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

    @staticmethod
    def _mail(row: sqlite3.Row) -> MailNote:
        return MailNote(
            id=row["id"], gmail_id=row["gmail_id"], ts=row["ts"], sender=row["sender"], subject=row["subject"],
            summary=row["summary"], important=bool(row["important"]), task_title=row["task_title"],
            task_category=row["task_category"], task_due_at=row["task_due_at"], notified_at=row["notified_at"],
            handled=bool(row["handled"]), account=row["account"],
        )

    def email_known(self, gmail_id: str) -> bool:
        with self._lock:
            return self._conn.execute("SELECT 1 FROM emails WHERE gmail_id = ?", (gmail_id,)).fetchone() is not None

    def add_email(
        self,
        gmail_id: str,
        ts: int,
        sender: str,
        subject: str,
        summary: str,
        important: bool,
        task_title: str | None = None,
        task_category: str | None = None,
        task_due_at: int | None = None,
        account: str = "personal",
    ) -> MailNote:
        with self._lock, self._conn:
            cursor = self._conn.execute(
                "INSERT INTO emails (gmail_id, ts, sender, subject, summary, important, task_title, task_category,"
                " task_due_at, account) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (gmail_id, ts, sender, subject, summary, int(important), task_title, task_category, task_due_at, account),
            )
            return self.get_email(int(cursor.lastrowid))  # type: ignore[return-value]

    def get_email(self, email_id: int) -> MailNote | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM emails WHERE id = ?", (email_id,)).fetchone()
        return self._mail(row) if row else None

    def mark_email(self, email_id: int, notified_at: int | None = None, handled: bool | None = None) -> None:
        with self._lock, self._conn:
            if notified_at is not None:
                self._conn.execute("UPDATE emails SET notified_at = ? WHERE id = ?", (notified_at, email_id))
            if handled is not None:
                self._conn.execute("UPDATE emails SET handled = ? WHERE id = ?", (int(handled), email_id))

    def unnotified_emails(self, account: str = "personal") -> list[MailNote]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM emails WHERE important = 1 AND notified_at IS NULL AND handled = 0 AND account = ?"
                " ORDER BY ts",
                (account,),
            ).fetchall()
        return [self._mail(r) for r in rows]

    def open_emails(self, since: int) -> list[MailNote]:
        """Correos importantes recientes que el dueño todavía no atendió con los botones."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM emails WHERE important = 1 AND handled = 0 AND ts >= ? ORDER BY ts DESC", (since,)
            ).fetchall()
        return [self._mail(r) for r in rows]

    # --- Listas simples (súper, compras): elementos sin fecha ni urgencia ---

    def list_add(self, name: str, text: str, now: int) -> bool:
        """Agrega un elemento; devuelve False si ya estaba en esa lista."""
        with self._lock, self._conn:
            if self._conn.execute(
                "SELECT 1 FROM list_items WHERE list = ? AND lower(text) = lower(?)", (name, text)
            ).fetchone():
                return False
            self._conn.execute("INSERT OR IGNORE INTO lists (name, created_at) VALUES (?, ?)", (name, now))
            self._conn.execute("INSERT INTO list_items (list, text, created_at) VALUES (?, ?, ?)", (name, text, now))
            return True

    def list_items(self, name: str) -> list[tuple[int, str]]:
        with self._lock:
            rows = self._conn.execute("SELECT id, text FROM list_items WHERE list = ? ORDER BY id", (name,)).fetchall()
        return [(r["id"], r["text"]) for r in rows]

    def list_entries(self, name: str) -> list[dict[str, Any]]:
        """Los elementos de una lista con su marca: los marcados siguen ahí hasta que se quiten."""
        with self._lock:
            rows = self._conn.execute("SELECT id, text, done FROM list_items WHERE list = ? ORDER BY id", (name,)).fetchall()
        return [{"id": r["id"], "text": r["text"], "done": bool(r["done"])} for r in rows]

    def list_check(self, item_id: int, done: bool) -> bool:
        with self._lock, self._conn:
            return self._conn.execute("UPDATE list_items SET done = ? WHERE id = ?", (int(done), item_id)).rowcount > 0

    def list_clear_done(self, name: str) -> int:
        with self._lock, self._conn:
            return self._conn.execute("DELETE FROM list_items WHERE list = ? AND done = 1", (name,)).rowcount

    def list_create(self, name: str, now: int) -> bool:
        """Crea una lista vacía; False si ya existía."""
        with self._lock, self._conn:
            return self._conn.execute(
                "INSERT OR IGNORE INTO lists (name, created_at) VALUES (?, ?)", (name, now)
            ).rowcount > 0

    def list_delete(self, name: str) -> bool:
        """Elimina la lista con todo lo que tenga."""
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM list_items WHERE list = ?", (name,))
            return self._conn.execute("DELETE FROM lists WHERE name = ?", (name,)).rowcount > 0

    def list_names(self) -> list[tuple[str, int]]:
        """Todas las listas, también las vacías, con cuántos elementos tienen."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT l.name, COUNT(i.id) n FROM lists l LEFT JOIN list_items i ON i.list = l.name"
                " GROUP BY l.name ORDER BY l.created_at, l.name"
            ).fetchall()
        return [(r["name"], r["n"]) for r in rows]

    def list_edit(self, item_id: int, text: str) -> str | None:
        """Cambia el texto de un elemento: "ok", "duplicate" si ya hay otro igual en su lista, o None si no existe."""
        with self._lock, self._conn:
            row = self._conn.execute("SELECT list FROM list_items WHERE id = ?", (item_id,)).fetchone()
            if row is None:
                return None
            if self._conn.execute(
                "SELECT 1 FROM list_items WHERE list = ? AND lower(text) = lower(?) AND id != ?", (row["list"], text, item_id)
            ).fetchone():
                return "duplicate"
            self._conn.execute("UPDATE list_items SET text = ? WHERE id = ?", (text, item_id))
            return "ok"

    def list_remove(self, item_id: int) -> bool:
        with self._lock, self._conn:
            return self._conn.execute("DELETE FROM list_items WHERE id = ?", (item_id,)).rowcount > 0

    def list_clear(self, name: str) -> int:
        with self._lock, self._conn:
            return self._conn.execute("DELETE FROM list_items WHERE list = ?", (name,)).rowcount

    # --- Fechas que se repiten cada año: cumpleaños y aniversarios ---

    def add_date(self, kind: str, name: str, month: int, day: int, year: int | None, now: int) -> int:
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM dates WHERE kind = ? AND lower(name) = lower(?)", (kind, name))
            cursor = self._conn.execute(
                "INSERT INTO dates (kind, name, month, day, year, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (kind, name, month, day, year, now),
            )
            return int(cursor.lastrowid)

    def list_dates(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM dates ORDER BY month, day, id").fetchall()
        return [dict(row) for row in rows]

    def dates_on(self, month: int, day: int) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM dates WHERE month = ? AND day = ? ORDER BY id", (month, day)).fetchall()
        return [dict(row) for row in rows]

    def get_date(self, date_id: int) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM dates WHERE id = ?", (date_id,)).fetchone()
        return dict(row) if row else None

    def update_date(self, date_id: int, kind: str, name: str, month: int, day: int, year: int | None) -> str | None:
        """Corrige una fecha: "ok", "duplicate" si ya hay otra igual (mismo tipo y nombre), o None si no existe."""
        with self._lock, self._conn:
            if self._conn.execute("SELECT 1 FROM dates WHERE id = ?", (date_id,)).fetchone() is None:
                return None
            others = self._conn.execute("SELECT name FROM dates WHERE id != ? AND kind = ?", (date_id, kind)).fetchall()
            if any(row["name"].casefold() == name.casefold() for row in others):
                return "duplicate"
            self._conn.execute(
                "UPDATE dates SET kind = ?, name = ?, month = ?, day = ?, year = ? WHERE id = ?",
                (kind, name, month, day, year, date_id),
            )
            return "ok"

    def delete_date(self, date_id: int) -> bool:
        with self._lock, self._conn:
            return self._conn.execute("DELETE FROM dates WHERE id = ?", (date_id,)).rowcount > 0

    # --- Hábitos: cosas de todos los días, con su racha ---

    def add_habit(self, title: str, remind_at: str | None, now: int) -> int:
        with self._lock, self._conn:
            existing = self._conn.execute("SELECT id FROM habits WHERE lower(title) = lower(?)", (title,)).fetchone()
            if existing:
                self._conn.execute("UPDATE habits SET remind_at = ? WHERE id = ?", (remind_at, existing["id"]))
                return int(existing["id"])
            cursor = self._conn.execute(
                "INSERT INTO habits (title, remind_at, created_at) VALUES (?, ?, ?)", (title, remind_at, now)
            )
            return int(cursor.lastrowid)

    def habits(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute("SELECT id, title, remind_at FROM habits ORDER BY id").fetchall()
        return [dict(row) for row in rows]

    def update_habit(self, habit_id: int, title: str, remind_at: str | None) -> str | None:
        """Cambia nombre y hora: "ok", "duplicate" si ya hay otro con ese nombre, o None si no existe."""
        with self._lock, self._conn:
            if self._conn.execute("SELECT 1 FROM habits WHERE id = ?", (habit_id,)).fetchone() is None:
                return None
            others = self._conn.execute("SELECT title FROM habits WHERE id != ?", (habit_id,)).fetchall()
            if any(row["title"].casefold() == title.casefold() for row in others):
                return "duplicate"
            self._conn.execute("UPDATE habits SET title = ?, remind_at = ? WHERE id = ?", (title, remind_at, habit_id))
            return "ok"

    def delete_habit(self, habit_id: int) -> bool:
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM habit_log WHERE habit_id = ?", (habit_id,))
            return self._conn.execute("DELETE FROM habits WHERE id = ?", (habit_id,)).rowcount > 0

    def mark_habit(self, habit_id: int, day: str) -> bool:
        """Anota el hábito como cumplido ese día (AAAA-MM-DD); False si ya lo estaba."""
        with self._lock, self._conn:
            return self._conn.execute(
                "INSERT OR IGNORE INTO habit_log (habit_id, day) VALUES (?, ?)", (habit_id, day)
            ).rowcount > 0

    def unmark_habit(self, habit_id: int, day: str) -> bool:
        """Quita la marca de ese día; False si no estaba marcado."""
        with self._lock, self._conn:
            return self._conn.execute(
                "DELETE FROM habit_log WHERE habit_id = ? AND day = ?", (habit_id, day)
            ).rowcount > 0

    def habit_days(self, habit_id: int) -> set[str]:
        with self._lock:
            rows = self._conn.execute("SELECT day FROM habit_log WHERE habit_id = ?", (habit_id,)).fetchall()
        return {r["day"] for r in rows}

    # --- Sesiones de la página: se guarda la huella de la llave, nunca la llave ---

    def session_add(self, hashed: str, now: int, expires_at: int, label: str, ip: str, approved: bool) -> int:
        with self._lock, self._conn:
            cursor = self._conn.execute(
                "INSERT INTO sessions (token_hash, created_at, last_seen, expires_at, label, ip, approved)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (hashed, now, now, expires_at, label[:80], ip[:45], int(approved)),
            )
            return int(cursor.lastrowid)

    def session_find(self, hashed: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM sessions WHERE token_hash = ?", (hashed,)).fetchone()
        return dict(row) if row else None

    def session_get(self, session_id: int) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        return dict(row) if row else None

    def session_update(self, session_id: int, **fields: Any) -> None:
        allowed = {"last_seen", "expires_at", "approved", "revoked_at"}
        if set(fields) - allowed:
            raise ValueError("campo de sesión no editable")
        assignments = ", ".join(f"{name} = ?" for name in fields)
        with self._lock, self._conn:
            self._conn.execute(f"UPDATE sessions SET {assignments} WHERE id = ?", (*fields.values(), session_id))

    def sessions_open(self, now: int) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM sessions WHERE revoked_at IS NULL AND approved = 1 AND expires_at > ?"
                " ORDER BY last_seen DESC, id DESC",
                (now,),
            ).fetchall()
        return [dict(row) for row in rows]

    # --- Recibos: gastos leídos de fotos ---

    RECEIPT_FIELDS = ("merchant", "day", "total", "currency", "category", "warranty_until", "items", "photo")

    def add_receipt(self, now: int, **fields: Any) -> int:
        columns = [name for name in self.RECEIPT_FIELDS if name in fields]
        with self._lock, self._conn:
            cursor = self._conn.execute(
                f"INSERT INTO receipts ({', '.join(columns)}, created_at) VALUES ({', '.join('?' for _ in columns)}, ?)",
                (*(fields[name] for name in columns), now),
            )
            return int(cursor.lastrowid)

    def get_receipt(self, receipt_id: int) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM receipts WHERE id = ?", (receipt_id,)).fetchone()
        return dict(row) if row else None

    def receipts_between(self, first_day: str, last_day: str) -> list[dict[str, Any]]:
        """Recibos con fecha entre los dos días (AAAA-MM-DD, incluidos), del más reciente al más viejo."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM receipts WHERE day BETWEEN ? AND ? ORDER BY day DESC, id DESC", (first_day, last_day)
            ).fetchall()
        return [dict(row) for row in rows]

    def receipts_with_warranty(self, from_day: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM receipts WHERE warranty_until >= ? ORDER BY warranty_until, id", (from_day,)
            ).fetchall()
        return [dict(row) for row in rows]

    def find_receipt(self, merchant: str, day: str, total: float) -> int | None:
        """Un recibo igual ya guardado (mismo comercio, día y total), para no contarlo dos veces."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, merchant FROM receipts WHERE day = ? AND abs(total - ?) < 0.005", (day, total)
            ).fetchall()
        return next((int(row["id"]) for row in rows if row["merchant"].casefold() == merchant.casefold()), None)

    def update_receipt(self, receipt_id: int, **fields: Any) -> bool:
        columns = [name for name in self.RECEIPT_FIELDS if name in fields]
        if not columns:
            return self.get_receipt(receipt_id) is not None
        with self._lock, self._conn:
            return self._conn.execute(
                f"UPDATE receipts SET {', '.join(f'{name} = ?' for name in columns)} WHERE id = ?",
                (*(fields[name] for name in columns), receipt_id),
            ).rowcount > 0

    def delete_receipt(self, receipt_id: int) -> bool:
        with self._lock, self._conn:
            return self._conn.execute("DELETE FROM receipts WHERE id = ?", (receipt_id,)).rowcount > 0

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
