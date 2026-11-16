"""La pestaña «Apuntes» de la página: listas, notas, hábitos, fechas señaladas y lo que se espera de otros.

Igual que con las tareas, la página manda valores exactos y aquí se valida cada uno; no interviene el modelo.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from .assistant import Assistant
from .extras import MAX_ITEM, MONTH_NAMES, Extras, days_word, streak

MAX_NOTE = 500
MAX_LISTS = 30


class ApunteError(ValueError):
    """Solicitud inválida; el mensaje se muestra tal cual en la página."""


def _text(value: Any, limit: int, problem: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ApunteError(problem)
    cleaned = " ".join(value.split())
    if any(ord(char) < 32 for char in cleaned):
        raise ApunteError(problem)
    return cleaned[:limit]


def _number(value: Any, problem: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ApunteError(problem)
    return value


class ExtrasEditor:
    def __init__(self, assistant: Assistant):
        self.assistant = assistant
        self.store = assistant.store
        self.extras: Extras = assistant.extras

    def _now(self) -> datetime:
        return self.assistant._now()

    # --- Lo que la página muestra ---

    def snapshot(self) -> dict[str, Any]:
        now = self._now()
        quiet = self.extras.quiet_until(now)
        return {
            "now": int(now.timestamp()),
            "lists": [
                {"name": name, "items": self.store.list_entries(name)}
                for name, _ in self.store.list_names()
            ],
            "notes": [{"id": fact_id, "text": text} for fact_id, text in self.store.list_facts(200)],
            "habits": [
                {"id": habit["id"], "title": habit["title"], "remind_at": habit["remind_at"], "done": done, "streak": run}
                for habit, done, run in self.extras.habit_status(now.date())
            ],
            "dates": [
                {
                    "id": entry["id"], "day": entry["day"], "month": entry["month"], "year": entry["year"],
                    "label": self.extras._date_label(entry),
                }
                for entry in self.store.list_dates()
            ],
            "waiting": [
                {"id": task.id, "title": task.title, "due_at": task.due_at}
                for task in self.store.pending_tasks() if task.kind == "waiting"
            ],
            "quiet_until": quiet,
        }

    # --- Cambios ---

    def apply(self, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ApunteError("Solicitud inválida.")
        handler = {
            "list_create": self._list_create,
            "list_delete": self._list_delete,
            "list_add": self._list_add,
            "list_edit": self._list_edit,
            "list_remove": self._list_remove,
            "list_check": self._list_check,
            "list_clear_done": self._list_clear_done,
            "habit_undo": self._habit_undo,
            "list_clear": self._list_clear,
            "note_add": self._note_add,
            "note_edit": self._note_edit,
            "note_delete": self._note_delete,
            "habit_add": self._habit_add,
            "habit_done": self._habit_done,
            "habit_delete": self._habit_delete,
            "date_add": self._date_add,
            "date_delete": self._date_delete,
            "quiet_off": lambda p: self.extras._quiet_off().text,
        }.get(payload.get("action"))  # type: ignore[arg-type]
        if handler is None:
            raise ApunteError("Acción desconocida.")
        return {"ok": True, "message": handler(payload)}

    def _list_create(self, payload: dict[str, Any]) -> str:
        name = self.extras._list_name(_text(payload.get("list"), 40, "Escribe el nombre de la lista."))
        if not name:
            raise ApunteError("Escribe el nombre de la lista.")
        names = [existing for existing, _ in self.store.list_names()]
        if name in names:
            raise ApunteError(f"Ya tienes una lista de {name}.")
        if len(names) >= MAX_LISTS:
            raise ApunteError("Ya tienes muchas listas. Elimina alguna antes de crear otra.")
        self.store.list_create(name, int(self._now().timestamp()))
        return f"Creé la lista de {name}."

    def _list_delete(self, payload: dict[str, Any]) -> str:
        name = self.extras._list_name(_text(payload.get("list"), 40, "Falta la lista."))
        if not self.store.list_delete(name):
            raise ApunteError("Esa lista ya no existía. Recarga la página.")
        return f"Eliminé la lista de {name}."

    def _list_add(self, payload: dict[str, Any]) -> str:
        name = self.extras._list_name(_text(payload.get("list"), 40, "Escribe el nombre de la lista."))
        item = _text(payload.get("text"), MAX_ITEM, "Escribe qué agregar.")
        if not name:
            raise ApunteError("Escribe el nombre de la lista.")
        names = [existing for existing, _ in self.store.list_names()]
        if name not in names and len(names) >= MAX_LISTS:
            raise ApunteError("Ya tienes muchas listas. Vacía alguna antes de crear otra.")
        if not self.store.list_add(name, item, int(self._now().timestamp())):
            raise ApunteError(f"«{item}» ya estaba en la lista de {name}.")
        return f"Agregué «{item}» a la lista de {name}."

    def _list_edit(self, payload: dict[str, Any]) -> str:
        item = _text(payload.get("text"), MAX_ITEM, "El elemento no puede quedar vacío.")
        result = self.store.list_edit(_number(payload.get("id"), "Falta el elemento."), item)
        if result is None:
            raise ApunteError("Ese elemento ya no estaba. Recarga la página.")
        if result == "duplicate":
            raise ApunteError(f"«{item}» ya está en esa lista.")
        return "Guardado."

    def _list_remove(self, payload: dict[str, Any]) -> str:
        if not self.store.list_remove(_number(payload.get("id"), "Falta el elemento.")):
            raise ApunteError("Ese elemento ya no estaba. Recarga la página.")
        return "Listo, lo quité."

    def _list_check(self, payload: dict[str, Any]) -> str:
        done = payload.get("done")
        if not isinstance(done, bool):
            raise ApunteError("Solicitud inválida.")
        if not self.store.list_check(_number(payload.get("id"), "Falta el elemento."), done):
            raise ApunteError("Ese elemento ya no estaba. Recarga la página.")
        return "Marcado." if done else "Desmarcado."

    def _list_clear_done(self, payload: dict[str, Any]) -> str:
        name = self.extras._list_name(_text(payload.get("list"), 40, "Falta la lista."))
        count = self.store.list_clear_done(name)
        if not count:
            raise ApunteError("No hay elementos marcados en esa lista.")
        return f"Quité {count} {'elemento marcado' if count == 1 else 'elementos marcados'}."

    def _habit_undo(self, payload: dict[str, Any]) -> str:
        habit_id = _number(payload.get("id"), "Falta el hábito.")
        habit = next((h for h in self.store.habits() if h["id"] == habit_id), None)
        if habit is None:
            raise ApunteError("Ese hábito ya no existe. Recarga la página.")
        today = self._now().date()
        if not self.store.unmark_habit(habit_id, today.isoformat()):
            raise ApunteError("Ese hábito no estaba marcado hoy.")
        run = streak(self.store.habit_days(habit_id), today)
        return f"Desmarqué «{habit['title']}» de hoy. Racha: {days_word(run)}."

    def _list_clear(self, payload: dict[str, Any]) -> str:
        name = self.extras._list_name(_text(payload.get("list"), 40, "Falta la lista."))
        return f"Vacié la lista de {name}." if self.store.list_clear(name) else "Esa lista ya estaba vacía."

    def _note_add(self, payload: dict[str, Any]) -> str:
        note = _text(payload.get("text"), MAX_NOTE, "Escribe la nota.")
        self.store.add_fact(note[:1].upper() + note[1:], int(self._now().timestamp()))
        return "Nota guardada."

    def _note_edit(self, payload: dict[str, Any]) -> str:
        note = _text(payload.get("text"), MAX_NOTE, "La nota no puede quedar vacía.")
        result = self.store.edit_fact(_number(payload.get("id"), "Falta la nota."), note[:1].upper() + note[1:])
        if result is None:
            raise ApunteError("Esa nota ya no estaba. Recarga la página.")
        if result == "duplicate":
            raise ApunteError("Ya tienes otra nota igual.")
        return "Nota guardada."

    def _note_delete(self, payload: dict[str, Any]) -> str:
        if not self.store.delete_fact(_number(payload.get("id"), "Falta la nota.")):
            raise ApunteError("Esa nota ya no estaba. Recarga la página.")
        return "Nota borrada."

    def _habit_add(self, payload: dict[str, Any]) -> str:
        title = _text(payload.get("title"), 100, "Escribe el hábito.")
        raw_time = payload.get("time")
        at = None
        if raw_time:
            try:
                moment = datetime.strptime(raw_time, "%H:%M")
            except (TypeError, ValueError):
                raise ApunteError("Escribe la hora como 08:00, o déjala vacía.") from None
            at = (moment.hour, moment.minute)
        return self.extras._habit_new(title, at).text

    def _habit_done(self, payload: dict[str, Any]) -> str:
        habit_id = _number(payload.get("id"), "Falta el hábito.")
        return self.extras.button("habit", habit_id).text

    def _habit_delete(self, payload: dict[str, Any]) -> str:
        if not self.store.delete_habit(_number(payload.get("id"), "Falta el hábito.")):
            raise ApunteError("Ese hábito ya no estaba. Recarga la página.")
        return "Hábito quitado."

    def _date_add(self, payload: dict[str, Any]) -> str:
        kind = payload.get("kind")
        if kind not in ("cumpleaños", "aniversario"):
            raise ApunteError("Elige cumpleaños o aniversario.")
        day, month = payload.get("day"), payload.get("month")
        if isinstance(day, bool) or isinstance(month, bool) or not isinstance(day, int) or not isinstance(month, int) or not 1 <= month <= 12:
            raise ApunteError("Esa fecha no existe.")
        year = payload.get("year")
        if year is not None and (isinstance(year, bool) or not isinstance(year, int) or not 1900 <= year <= self._now().year):
            raise ApunteError("El año no es válido; puedes dejarlo vacío.")
        name = payload.get("name") or ""
        if kind == "cumpleaños" or name:
            name = _text(name, 80, "Escribe de quién es el cumpleaños.")
            if not all(char.isalnum() or char in " .'-" for char in name):
                raise ApunteError("El nombre solo puede llevar letras, números y espacios.")
        when = f"{day} de {MONTH_NAMES[month - 1]}" + (f" de {year}" if year else "")
        if kind == "cumpleaños":
            phrase = f"el cumpleaños de {name} es el {when}"
        else:
            phrase = f"mi aniversario con {name} es el {when}" if name else f"mi aniversario es el {when}"
        reply = self.extras.handle(phrase, self._now())
        if reply is None:
            raise ApunteError("No pude guardar esa fecha. Revisa el nombre y el día.")
        if "no existe" in reply.text:
            raise ApunteError("Esa fecha no existe.")
        return reply.text

    def _date_delete(self, payload: dict[str, Any]) -> str:
        if not self.store.delete_date(_number(payload.get("id"), "Falta la fecha.")):
            raise ApunteError("Esa fecha ya no estaba. Recarga la página.")
        return "Fecha borrada."
