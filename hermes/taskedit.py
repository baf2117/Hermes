"""Cambios a las tareas desde la página local.

La página manda valores exactos (no texto libre), así que aquí no interviene el modelo: cada campo se
valida y las reglas de subtareas son las mismas que en Telegram.
"""
from __future__ import annotations

from typing import Any

from .assistant import URGENCIES, Assistant, clean_repeat
from .store import Task

MAX_TITLE = 200
# Fechas razonables: del año 2000 al 2100. Evita valores absurdos que romperían los avisos.
MIN_TIMESTAMP, MAX_TIMESTAMP = 946_684_800, 4_102_444_800


class EditError(ValueError):
    """Solicitud inválida; el mensaje se muestra tal cual en la página."""


def _task_id(payload: dict[str, Any]) -> int:
    value = payload.get("id")
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise EditError("Falta el número de la tarea.")
    return value


def _title(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EditError("El título no puede quedar vacío.")
    return " ".join(value.split())[:MAX_TITLE]


class TaskEditor:
    def __init__(self, assistant: Assistant):
        self.assistant = assistant
        self.store = assistant.store

    def _now(self) -> int:
        return int(self.assistant._now().timestamp())

    def _pending(self, payload: dict[str, Any]) -> Task:
        task = self.store.get_task(_task_id(payload))
        if task is None or task.status != "pending":
            raise EditError("Esa tarea ya no está pendiente. Recarga la página.")
        return task

    def apply(self, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise EditError("Solicitud inválida.")
        action = payload.get("action")
        handler = {
            "edit": self._edit,
            "done": lambda p: self._finish(p, "done"),
            "cancel": lambda p: self._finish(p, "cancelled"),
            "add_step": self._add_step,
            "reopen": self._reopen,
        }.get(action)  # type: ignore[arg-type]
        if handler is None:
            raise EditError("Acción desconocida.")
        return {"ok": True, "message": handler(payload)}

    def _edit(self, payload: dict[str, Any]) -> str:
        task = self._pending(payload)
        changes: dict[str, Any] = {}
        if "title" in payload:
            changes["title"] = _title(payload["title"])
        if "category" in payload:
            category = self.assistant._clean_category(payload["category"])
            if category is None:
                raise EditError("Esa categoría no existe.")
            changes["category"] = category
        if "urgency" in payload:
            if payload["urgency"] not in URGENCIES:
                raise EditError("Urgencia inválida.")
            changes["urgency"] = payload["urgency"]
        due_at = task.due_at
        if "due_at" in payload:
            due_at = payload["due_at"]
            if due_at is not None and (
                isinstance(due_at, bool) or not isinstance(due_at, int) or not MIN_TIMESTAMP <= due_at <= MAX_TIMESTAMP
            ):
                raise EditError("Fecha inválida.")
            if due_at != task.due_at:
                changes.update(due_at=due_at, notified_at=None)  # Fecha nueva: se vuelve a avisar.
        if "repeat_minutes" in payload:
            raw = payload["repeat_minutes"]
            repeat = None if raw is None else clean_repeat(raw)
            if raw is not None and repeat is None:
                raise EditError("Intervalo de repetición inválido.")
            changes["repeat_minutes"] = repeat or None
            if repeat and due_at is None:
                # Igual que por Telegram: repetir sin fecha empieza a avisar desde ahora.
                changes.update(due_at=self._now(), notified_at=None)
        if not changes:
            return "Sin cambios."
        now = self._now()
        self.store.update_task(task.id, now, **changes)
        if "category" in changes:
            for step in self.store.subtasks(task.id, "pending"):  # Los pasos siguen a su tarea.
                self.store.update_task(step.id, now, category=changes["category"])
        return f"Guardé «{changes.get('title', task.title)}»."

    def _finish(self, payload: dict[str, Any], status: str) -> str:
        return self.assistant._finish(self._pending(payload).id, status).text

    def _add_step(self, payload: dict[str, Any]) -> str:
        parent = self._pending(payload)
        title = _title(payload.get("title"))
        return self.assistant._add_subtasks({"task_id": parent.id, "subtasks": [title]}, title).text

    def _reopen(self, payload: dict[str, Any]) -> str:
        task = self.store.get_task(_task_id(payload))
        if task is None or task.status == "pending":
            raise EditError("Esa tarea ya está pendiente.")
        now = self._now()
        self.store.reopen(task.id, now)
        if task.parent_id is not None:
            parent = self.store.get_task(task.parent_id)
            if parent is not None and parent.status != "pending":
                self.store.reopen(parent.id, now)  # Un paso pendiente reabre la tarea que se completó sola.
        return f"«{task.title}» volvió a pendientes."
