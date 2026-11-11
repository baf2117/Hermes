"""Lógica de Hermes: convierte mensajes en acciones validadas sobre las tareas."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable

from .config import Config
from .llm import DAY_NAMES, LLMError
from .store import Store, Task

log = logging.getLogger(__name__)

MONTHS = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic")
URGENCY_MARK = {"alta": "🔴", "media": "🟡", "baja": "🟢"}
URGENCIES = ("baja", "media", "alta")
LAST_TASK_KEY = "last_task_id"
HISTORY_TURNS = 6

HELP_TEXT = (
    "Escríbeme lo que necesitas recordar, por ejemplo:\n"
    "«recuérdame pagar la luz el viernes a las 9»\n\n"
    "Comandos:\n"
    "/tareas: todas las pendientes\n"
    "/hoy: resumen de hoy\n"
    "/hecho 3: marca la tarea 3 como hecha\n"
    "/borrar 3: cancela la tarea 3\n"
    "/memoria: lo que recuerdo de ti\n"
    "/olvidar 2: borra el dato 2 de mi memoria\n"
    "/ayuda: este mensaje\n\n"
    "También puedes mandarme notas de voz."
)
TIME_HINT = re.compile(
    r"\d|\b(hoy|ma[ñn]ana|pasado|lunes|martes|mi[ée]rcoles|jueves|viernes|s[áa]bado|domingo|semana|mes|"
    r"enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre|"
    r"mediod[íi]a|medianoche|noche|tarde|a las|a la una|horas?|minutos?)\b",
    re.IGNORECASE,
)
MEMORY_FACTS = 6
MEMORY_MESSAGES = 3
FALLBACK_FACTS = 8


@dataclass
class Reply:
    text: str
    buttons: list[list[tuple[str, str]]] = field(default_factory=list)


class DueProblem(Exception):
    pass


def reminder_buttons(task_id: int) -> list[list[tuple[str, str]]]:
    return [[("✅ Hecho", f"done:{task_id}"), ("⏰ +1 h", f"snooze:{task_id}"), ("📅 Mañana", f"tomorrow:{task_id}")]]


class Assistant:
    def __init__(self, store: Store, llm: Any, config: Config, now: Callable[[], datetime] | None = None):
        self.store = store
        self.llm = llm
        self.config = config
        self._now = now or (lambda: datetime.now().astimezone())

    # --- Presentación ---

    def format_due(self, due_at: int | None) -> str:
        if due_at is None:
            return "sin fecha"
        moment = datetime.fromtimestamp(due_at, self._now().tzinfo)
        return f"{DAY_NAMES[moment.weekday()]} {moment.day} {MONTHS[moment.month - 1]}, {moment:%H:%M}"

    def format_task(self, task: Task) -> str:
        return f"{URGENCY_MARK[task.urgency]} #{task.id} {task.title}\n     {task.category} · {self.format_due(task.due_at)}"

    def reminder_text(self, task: Task, now: datetime) -> str:
        text = f"⏰ {URGENCY_MARK[task.urgency]} {task.title}\n{task.category} · urgencia {task.urgency}"
        if task.due_at is not None and now.timestamp() - task.due_at > 120:
            text += f"\nAtrasado: era para {self.format_due(task.due_at)}."
        return text

    def build_summary(self) -> str:
        now = self._now()
        end_of_today = now.replace(hour=23, minute=59, second=59, microsecond=0).timestamp()
        start_of_today = now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        pending = self.store.pending_tasks()
        overdue = [t for t in pending if t.due_at is not None and t.due_at < start_of_today]
        today = [t for t in pending if t.due_at is not None and start_of_today <= t.due_at <= end_of_today]
        undated_high = [t for t in pending if t.due_at is None and t.urgency == "alta"]
        parts = [f"Buen día. Hoy es {DAY_NAMES[now.weekday()]} {now.day} {MONTHS[now.month - 1]}."]
        for label, tasks in (("Atrasadas", overdue), ("Hoy", today), ("Urgentes sin fecha", undated_high)):
            if tasks:
                parts.append(f"\n{label}:\n" + "\n".join(self.format_task(t) for t in tasks))
        if len(parts) == 1:
            parts.append("No tienes tareas para hoy.")
        return "\n".join(parts)

    def _list_text(self) -> str:
        pending = self.store.pending_tasks()
        if not pending:
            return "No tienes tareas pendientes."
        return "Pendientes:\n" + "\n".join(self.format_task(t) for t in pending)

    def _confirmation(self, task: Task, prefix: str) -> Reply:
        text = f"{prefix}\n{self.format_task(task)}\n\nSi algo está mal, dímelo y lo corrijo."
        return Reply(text, [[("🗑 Borrar", f"cancel:{task.id}")]])

    # --- Validación de lo que propone el modelo ---

    def _clean_category(self, value: Any) -> str | None:
        if isinstance(value, str) and value.strip().lower() in self.config.categories:
            return value.strip().lower()
        return None

    @staticmethod
    def _clean_urgency(value: Any) -> str | None:
        return value if value in URGENCIES else None

    def _resolve_due(self, data: dict[str, Any], reference: datetime) -> int | None:
        """Devuelve el instante del aviso, None si no hay fecha, o lanza DueProblem.

        Todo se calcula desde `reference`, la hora en que el usuario envió el mensaje, aunque
        Hermes lo lea más tarde. Un aviso que ya venció al leerlo se envía de inmediato.
        """
        now = reference
        minutes = data.get("relative_minutes")
        if isinstance(minutes, int) and not isinstance(minutes, bool) and minutes > 0:
            return int((now + timedelta(minutes=minutes)).timestamp())

        raw_date, raw_time = data.get("date"), data.get("time")
        if not raw_date and not raw_time:
            return None
        try:
            parsed_time = datetime.strptime(raw_time, "%H:%M").time() if raw_time else None
            parsed_date = datetime.strptime(raw_date, "%Y-%m-%d").date() if raw_date else None
        except (TypeError, ValueError) as exc:
            raise DueProblem("No entendí bien la fecha.") from exc

        if parsed_date is None:
            # Solo dijo la hora: la próxima vez que llegue esa hora.
            due = datetime.combine(now.date(), parsed_time, now.tzinfo)
            if due <= now:
                due += timedelta(days=1)
            return int(due.timestamp())

        if parsed_time is None:
            due = datetime.combine(parsed_date, self.config.default_task_time, now.tzinfo)
            if parsed_date == now.date() and due <= now:
                due = now + timedelta(hours=1)
            return int(due.timestamp())

        due = datetime.combine(parsed_date, parsed_time, now.tzinfo)
        if due <= now:
            raise DueProblem(f"Esa fecha ya pasó ({self.format_due(int(due.timestamp()))}).")
        return int(due.timestamp())

    def _pending_by_id(self, value: Any) -> Task | None:
        if not isinstance(value, int) or isinstance(value, bool):
            return None
        task = self.store.get_task(value)
        return task if task and task.status == "pending" else None

    def _last_task(self) -> Task | None:
        raw = self.store.kv_get(LAST_TASK_KEY)
        return self._pending_by_id(int(raw)) if raw else None

    def _remember_last(self, task: Task) -> None:
        self.store.kv_set(LAST_TASK_KEY, str(task.id))

    # --- Acciones ---

    def _create(self, data: dict[str, Any], source: str, reference: datetime) -> Reply:
        now_ts = int(self._now().timestamp())
        title = str(data.get("title") or source).strip()[:200]
        category = self._clean_category(data.get("category")) or "personal"
        urgency = self._clean_urgency(data.get("urgency")) or "media"
        problem = None
        if data.get("date") and not data.get("time") and not TIME_HINT.search(source):
            # El modelo a veces inventa la fecha de hoy cuando el mensaje no menciona ninguna.
            data = {**data, "date": None}
        try:
            due_at = self._resolve_due(data, reference)
        except DueProblem as exc:
            due_at, problem = None, str(exc)
        task = self.store.add_task(title, category, urgency, due_at, source, now_ts)
        self._remember_last(task)
        if problem:
            return self._confirmation(task, f"Guardada sin aviso. {problem} ¿Para cuándo la dejo?")
        return self._confirmation(task, "Listo, la anoté:")

    def _edit(self, data: dict[str, Any], reference: datetime) -> Reply:
        task = self._pending_by_id(data.get("task_id")) or self._last_task()
        if task is None:
            return Reply("No sé qué tarea quieres cambiar. Revisa /tareas y dime el número.")
        changes: dict[str, Any] = {}
        if data.get("title"):
            changes["title"] = str(data["title"]).strip()[:200]
        if category := self._clean_category(data.get("category")):
            changes["category"] = category
        if urgency := self._clean_urgency(data.get("urgency")):
            changes["urgency"] = urgency
        try:
            due_at = self._resolve_due(data, reference)
        except DueProblem as exc:
            return Reply(f"No la cambié. {exc} ¿Para cuándo la dejo?")
        if due_at is not None:
            changes.update(due_at=due_at, notified_at=None)
        if not changes:
            return Reply("No entendí qué quieres cambiar. Por ejemplo: «ponla para el lunes a las 10».")
        updated = self.store.update_task(task.id, int(self._now().timestamp()), **changes)
        self._remember_last(updated)  # type: ignore[arg-type]
        return self._confirmation(updated, "Corregida:")  # type: ignore[arg-type]

    def _finish(self, task_id: Any, status: str) -> Reply:
        task = self._pending_by_id(task_id)
        if task is None:
            return Reply("No identifiqué esa tarea. Revisa /tareas y dime el número.")
        self.store.set_status(task.id, status, int(self._now().timestamp()))
        return Reply(f"{'✅ Hecho' if status == 'done' else '🗑 Cancelada'}: {task.title}")

    def _remember(self, data: dict[str, Any], text: str) -> Reply:
        fact = str(data.get("title") or text).strip()[:500]
        fact_id = self.store.add_fact(fact, int(self._now().timestamp()))
        return Reply(f"🧠 Lo recordaré: {fact}", [[("🗑 Olvidar", f"forget:{fact_id}")]])

    def _memory_for_chat(self, text: str) -> str:
        """Reúne lo relacionado con la pregunta; el historial reciente ya va aparte."""
        facts = [fact for _, fact in self.store.search_facts(text, MEMORY_FACTS)]
        if not facts:
            facts = [fact for _, fact in self.store.list_facts(FALLBACK_FACTS)]
        parts = [f"- {fact}" for fact in facts]
        tz = self._now().tzinfo
        for ts, said in self.store.search_messages(text, MEMORY_MESSAGES, HISTORY_TURNS):
            moment = datetime.fromtimestamp(ts, tz)
            parts.append(f"- El {moment.day} {MONTHS[moment.month - 1]} el usuario dijo: {said[:200]}")
        return "\n".join(parts)

    def _dispatch(self, data: dict[str, Any], text: str, reference: datetime) -> Reply:
        intent = data["intent"]
        if intent == "create_task":
            return self._create(data, text, reference)
        if intent == "edit_task":
            return self._edit(data, reference)
        if intent == "remember_fact":
            return self._remember(data, text)
        if intent == "complete_task":
            return self._finish(data.get("task_id"), "done")
        if intent == "cancel_task":
            return self._finish(data.get("task_id"), "cancelled")
        if intent == "list_tasks":
            return Reply(self._list_text())
        return Reply(self.llm.reply(text, self.store.recent_messages(HISTORY_TURNS), self._memory_for_chat(text)))

    def _command(self, text: str) -> Reply:
        command, _, argument = text.partition(" ")
        command = command.split("@")[0].lower()
        if command in ("/start", "/ayuda"):
            return Reply("Hola, soy Hermes.\n\n" + HELP_TEXT)
        if command == "/tareas":
            return Reply(self._list_text())
        if command == "/hoy":
            return Reply(self.build_summary())
        if command in ("/hecho", "/borrar"):
            if not argument.strip().isdigit():
                return Reply(f"Dime el número de la tarea, por ejemplo: {command} 3")
            return self._finish(int(argument), "done" if command == "/hecho" else "cancelled")
        if command == "/memoria":
            facts = self.store.list_facts()
            if not facts:
                return Reply("Todavía no me has contado datos para recordar.")
            return Reply("Lo que recuerdo:\n" + "\n".join(f"#{i} {fact}" for i, fact in facts))
        if command == "/olvidar":
            if not argument.strip().isdigit():
                return Reply("Dime el número del dato, por ejemplo: /olvidar 2. Los ves con /memoria.")
            return Reply("Listo, lo olvidé." if self.store.delete_fact(int(argument)) else "No encontré ese dato.")
        return Reply("No conozco ese comando.\n\n" + HELP_TEXT)

    # --- Entradas ---

    def handle_text(self, text: str, sent_at: datetime | None = None) -> Reply:
        text = text.strip()
        now = self._now()
        reference = min(sent_at, now) if sent_at else now
        now_ts = int(reference.timestamp())
        if text.startswith("/"):
            reply = self._command(text)
        else:
            try:
                pending = self.store.pending_tasks()
                facts = [fact for _, fact in self.store.search_facts(text, MEMORY_FACTS)]
                data = self.llm.interpret(
                    text, reference, pending, self._last_task(), self.config.categories, facts
                )
                reply = self._dispatch(data, text, reference)
            except LLMError as exc:
                log.warning("El modelo falló: %s", exc)
                task = self.store.add_task(text[:200], "personal", "media", None, text, now_ts)
                self._remember_last(task)
                reply = Reply(
                    f"El modelo no respondió, así que lo guardé tal cual para no perderlo (#{task.id}, sin fecha)."
                )
        self.store.log_message("user", text, now_ts)
        self.store.log_message("hermes", reply.text, int(self._now().timestamp()))
        return reply

    def handle_button(self, data: str) -> Reply:
        action, _, raw_id = data.partition(":")
        if not raw_id.isdigit():
            return Reply("No entendí ese botón.")
        if action == "forget":
            return Reply("Listo, lo olvidé." if self.store.delete_fact(int(raw_id)) else "Ese dato ya no estaba.")
        task = self._pending_by_id(int(raw_id))
        if task is None:
            return Reply("Esa tarea ya no está pendiente.")
        now = self._now()
        now_ts = int(now.timestamp())
        if action == "done":
            return self._finish(task.id, "done")
        if action == "cancel":
            return self._finish(task.id, "cancelled")
        if action == "snooze":
            due = now + timedelta(hours=1)
        elif action == "tomorrow":
            due = datetime.combine(now.date() + timedelta(days=1), self.config.default_task_time, now.tzinfo)
        else:
            return Reply("No entendí ese botón.")
        self.store.update_task(task.id, now_ts, due_at=int(due.timestamp()), notified_at=None)
        return Reply(f"Pospuesta para {self.format_due(int(due.timestamp()))}: {task.title}")
