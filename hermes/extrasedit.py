"""La pestaña «Apuntes» de la página: listas, notas, hábitos, fechas señaladas y lo que se espera de otros.

Igual que con las tareas, la página manda valores exactos y aquí se valida cada uno; no interviene el modelo.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any

from .assistant import Assistant
from .extras import MAX_ITEM, MONTH_NAMES, Extras, best_streak, date_fact, days_word, next_occurrence, streak

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
            "habits": [self._habit_view(habit, done, run, now.date()) for habit, done, run in self.extras.habit_status(now.date())],
            "dates": self._dates_view(now.date()),
            "waiting": [
                {"id": task.id, "title": task.title, "due_at": task.due_at}
                for task in self.store.pending_tasks() if task.kind == "waiting"
            ],
            "quiet_until": quiet,
        }

    def _dates_view(self, today: date) -> list[dict[str, Any]]:
        """Las fechas en el orden en que van a llegar, con cuántos días faltan y cuántos años se cumplen."""
        views = []
        for entry in self.store.list_dates():
            upcoming = next_occurrence(entry["month"], entry["day"], today)
            views.append({
                "id": entry["id"], "kind": entry["kind"], "name": entry["name"],
                "day": entry["day"], "month": entry["month"], "year": entry["year"],
                "label": self.extras._date_label(entry),
                "next": upcoming.isoformat(), "in_days": (upcoming - today).days,
                "turns": upcoming.year - entry["year"] if entry["year"] and upcoming.year > entry["year"] else None,
            })
        return sorted(views, key=lambda view: (view["in_days"], view["id"]))

    def _habit_view(self, habit: dict[str, Any], done: bool, run: int, today: date) -> dict[str, Any]:
        days = self.store.habit_days(habit["id"])
        week = [today - timedelta(days=offset) for offset in range(6, -1, -1)]  # Los últimos 7 días, hasta hoy.
        return {
            "id": habit["id"], "title": habit["title"], "remind_at": habit["remind_at"], "done": done, "streak": run,
            "best": best_streak(days), "total": len(days),
            "week": [{"day": d.isoformat(), "done": d.isoformat() in days} for d in week],
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
            "habit_edit": self._habit_edit,
            "date_add": self._date_add,
            "date_delete": self._date_delete,
            "date_edit": self._date_edit,
            "waiting_add": self._waiting_add,
            "waiting_edit": self._waiting_edit,
            "waiting_delete": self._waiting_delete,
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

    @staticmethod
    def _habit_time(raw: Any) -> tuple[int, int] | None:
        if not raw:
            return None
        try:
            moment = datetime.strptime(raw, "%H:%M")
        except (TypeError, ValueError):
            raise ApunteError("Escribe la hora como 08:00, o déjala vacía.") from None
        return moment.hour, moment.minute

    def _habit_add(self, payload: dict[str, Any]) -> str:
        title = _text(payload.get("title"), 100, "Escribe el hábito.")
        return self.extras._habit_new(title, self._habit_time(payload.get("time"))).text

    def _habit_edit(self, payload: dict[str, Any]) -> str:
        habit_id = _number(payload.get("id"), "Falta el hábito.")
        title = _text(payload.get("title"), 100, "El hábito no puede quedar sin nombre.")
        at = self._habit_time(payload.get("time"))
        result = self.store.update_habit(habit_id, title[:1].upper() + title[1:], f"{at[0]:02d}:{at[1]:02d}" if at else None)
        if result is None:
            raise ApunteError("Ese hábito ya no existe. Recarga la página.")
        if result == "duplicate":
            raise ApunteError("Ya tienes otro hábito con ese nombre.")
        return "Hábito guardado."

    def _habit_done(self, payload: dict[str, Any]) -> str:
        habit_id = _number(payload.get("id"), "Falta el hábito.")
        return self.extras.button("habit", habit_id).text

    def _habit_delete(self, payload: dict[str, Any]) -> str:
        if not self.store.delete_habit(_number(payload.get("id"), "Falta el hábito.")):
            raise ApunteError("Ese hábito ya no estaba. Recarga la página.")
        return "Hábito quitado."

    def _date_fields(self, payload: dict[str, Any]) -> tuple[str, str, int, int, int | None]:
        """Valida tipo, nombre, día, mes y año (opcional) de una fecha, igual al crearla que al corregirla."""
        kind = payload.get("kind")
        if kind not in ("cumpleaños", "aniversario"):
            raise ApunteError("Elige cumpleaños o aniversario.")
        day, month = payload.get("day"), payload.get("month")
        if isinstance(day, bool) or isinstance(month, bool) or not isinstance(day, int) or not isinstance(month, int) or not 1 <= month <= 12:
            raise ApunteError("Esa fecha no existe.")
        try:
            date(2000, month, day)  # 2000 es bisiesto: admite el 29 de febrero.
        except ValueError:
            raise ApunteError("Esa fecha no existe.") from None
        year = payload.get("year")
        if year is not None and (isinstance(year, bool) or not isinstance(year, int) or not 1900 <= year <= self._now().year):
            raise ApunteError("El año no es válido; puedes dejarlo vacío.")
        if year is not None:
            try:
                date(year, month, day)
            except ValueError:
                raise ApunteError(f"El {day} de {MONTH_NAMES[month - 1]} no existió en {year}.") from None
        name = payload.get("name") or ""
        if kind == "cumpleaños" or name:
            name = _text(name, 80, "Escribe de quién es el cumpleaños.")
            if not all(char.isalnum() or char in " .'-" for char in name):
                raise ApunteError("El nombre solo puede llevar letras, números y espacios.")
        return kind, name, day, month, year

    def _date_add(self, payload: dict[str, Any]) -> str:
        kind, name, day, month, year = self._date_fields(payload)
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

    # --- Seguimientos: lo que se espera de otras personas ---

    def _waiting_task(self, payload: dict[str, Any]) -> Any:
        task = self.store.get_task(_number(payload.get("id"), "Falta el seguimiento."))
        if task is None or task.kind != "waiting" or task.status != "pending":
            raise ApunteError("Ese seguimiento ya no está abierto. Recarga la página.")
        return task

    def _ask_on(self, raw: Any) -> int:
        """«AAAA-MM-DD» -> el momento de preguntar ese día, a la hora por defecto de las tareas."""
        now = self._now()
        try:
            day = datetime.strptime(raw, "%Y-%m-%d").date()
        except (TypeError, ValueError):
            raise ApunteError("Elige el día en que quieres que te pregunte.") from None
        if day < now.date():
            raise ApunteError("Ese día ya pasó. Elige hoy o un día más adelante.")
        moment = datetime.combine(day, self.assistant.config.default_task_time, now.tzinfo)
        return int(max(moment, now).timestamp())  # Si es hoy y la hora ya pasó, pregunta enseguida.

    def _waiting_add(self, payload: dict[str, Any]) -> str:
        what = _text(payload.get("text"), 180, "Escribe qué estás esperando.")
        what = re.sub(r"^(?:estoy |sigo )?esperando\s+", "", what, flags=re.IGNORECASE) or what
        days = payload.get("days", 3)
        if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 60:
            raise ApunteError("Los días para preguntar van de 1 a 60.")
        return self.extras._waiting(what, str(days), what, self._now()).text.split("\n")[0]

    def _waiting_edit(self, payload: dict[str, Any]) -> str:
        task = self._waiting_task(payload)
        changes: dict[str, Any] = {}
        if "text" in payload:
            title = _text(payload.get("text"), 200, "El seguimiento no puede quedar vacío.")
            if title != task.title:
                changes["title"] = title
        if "date" in payload:
            due_at = self._ask_on(payload.get("date"))
            if task.due_at is None or datetime.fromtimestamp(task.due_at, self._now().tzinfo).date() != datetime.fromtimestamp(
                due_at, self._now().tzinfo
            ).date():
                changes.update(due_at=due_at, notified_at=None)  # Fecha nueva: se vuelve a preguntar.
        if not changes:
            return "Sin cambios."
        self.store.update_task(task.id, int(self._now().timestamp()), **changes)
        return "Seguimiento guardado."

    def _waiting_delete(self, payload: dict[str, Any]) -> str:
        task = self._waiting_task(payload)
        self.store.delete_task(task.id, int(self._now().timestamp()))
        return f"Borré el seguimiento «{task.title}»."

    def _date_note(self, entry: dict[str, Any]) -> int | None:
        """La nota que se guardó junto con la fecha, si sigue tal cual."""
        wanted = date_fact(entry["kind"], entry["name"], entry["day"], entry["month"]).casefold()
        return next((fact_id for fact_id, text in self.store.list_facts(1000) if text.casefold() == wanted), None)

    def _date_edit(self, payload: dict[str, Any]) -> str:
        date_id = _number(payload.get("id"), "Falta la fecha.")
        old = self.store.get_date(date_id)
        if old is None:
            raise ApunteError("Esa fecha ya no estaba. Recarga la página.")
        kind, name, day, month, year = self._date_fields(payload)
        if (kind, name, day, month, year) == (old["kind"], old["name"], old["day"], old["month"], old["year"]):
            return "Sin cambios."
        note = self._date_note(old)
        result = self.store.update_date(date_id, kind, name, month, day, year)
        if result is None:
            raise ApunteError("Esa fecha ya no estaba. Recarga la página.")
        if result == "duplicate":
            raise ApunteError("Ya tienes esa fecha anotada.")
        fact = date_fact(kind, name, day, month)
        if note is None or self.store.edit_fact(note, fact) == "duplicate":
            self.store.add_fact(fact, int(self._now().timestamp()))  # add_fact no repite una nota que ya existe.
        return "Fecha guardada."

    def _date_delete(self, payload: dict[str, Any]) -> str:
        date_id = _number(payload.get("id"), "Falta la fecha.")
        entry = self.store.get_date(date_id)
        note = self._date_note(entry) if entry else None
        if not self.store.delete_date(date_id):
            raise ApunteError("Esa fecha ya no estaba. Recarga la página.")
        if note is not None:
            self.store.delete_fact(note)  # Sin la fecha, la nota que la acompañaba ya no aplica.
        return "Fecha borrada."
