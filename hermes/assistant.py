"""Lógica de Hermes: convierte mensajes en acciones validadas sobre las tareas."""
from __future__ import annotations

import json
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable
from urllib.parse import urlsplit

from .config import Config
from .llm import DAY_NAMES, LLMError
from .store import STOPWORDS, Store, Task
from .websearch import SearchError

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
    "/urgente 3: marca la tarea 3 como urgente\n"
    "/sub 3 empacar libros: agrega un paso a la tarea 3\n"
    "/repetir 3 30: repite el aviso de la tarea 3 cada 30 min hasta que esté hecha (0 lo detiene)\n"
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
UPCOMING_HINT = re.compile(
    r"\b(cu[áa]ndo|pr[óo]xim[oa]s?|siguientes?|calendario|agenda|horarios?|fechas?|juega|juegan)\b", re.IGNORECASE
)
LIVE_INFO_HINT = re.compile(
    r"\b(juega|juegan|partidos?|marcador|clima|pron[óo]stico|noticias|d[óo]lar)\b", re.IGNORECASE
)
BULK_CANCEL_KEY = "bulk_cancel_request"
BULK_CANCEL_SECONDS = 300
BULK_CANCEL_REQUEST = re.compile(r"\b(cancel\w*|borr\w*|elimin\w*|quit\w*)\b.*\b(pendientes|tareas|todas|todos|todo)\b")
CONFIRM_YES = re.compile(r"si|si,? (cancelalas?|borralas?|confirmo|dale|por favor)|confirmo|dale|hazlo|adelante")
CONFIRM_NO = re.compile(r"no|no,? (gracias|las cancelas?)|mejor no|dejalo|dejalas")
_LOW_URGENCY = re.compile(r"\b(no (es|era|está) urgente|sin prisa|no corre prisa|prioridad baja|baja prioridad)\b")
_HIGH_URGENCY = re.compile(r"\b(urgente|prioridad alta|alta prioridad|muy importante)\b")
_TASK_WORDS = frozenset(
    "tarea tareas pendiente pendientes urgente urgencia prioridad importante cambia cambiala cambiar ponla "
    "ponle poner marca marcala tiene tienen debe deben como".split()
)


def _plain(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text.lower()) if unicodedata.category(c) != "Mn")


MIN_REPEAT_MINUTES = 5
MAX_REPEAT_MINUTES = 24 * 60
_NUMBERS = {"un": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "diez": 10, "quince": 15, "veinte": 20}
_REPEAT_EVERY = re.compile(
    r"\bcada\s+(?:(media)\s+hora|(\d+|un|una|dos|tres|cuatro|cinco|diez|quince|veinte)?\s*(minutos?|min|horas?)\b)"
)
_STOP_REPEATING = re.compile(
    r"\b(deja de (repetir|insistir)\w*|no (me |te )?(lo |la |los |las )?(repitas|insistas)|sin repetir|no lo repitas mas)\b"
)


MAX_SUBTASKS = 15


def clean_subtasks(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    steps = [str(item).strip()[:200] for item in value if isinstance(item, str) and item.strip()]
    return list(dict.fromkeys(steps))[:MAX_SUBTASKS]


def format_interval(minutes: int | None) -> str:
    if not minutes:
        return ""
    if minutes % 60 == 0:
        hours = minutes // 60
        return "cada hora" if hours == 1 else f"cada {hours} h"
    return f"cada {minutes} min"


def clean_repeat(value: Any) -> int | None:
    """Minutos entre repeticiones; 0 significa dejar de repetir; None si no se pidió nada."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return 0 if value == 0 else min(max(value, MIN_REPEAT_MINUTES), MAX_REPEAT_MINUTES)


def repeat_in_text(text: str) -> int | None:
    plain = _plain(text)
    if _STOP_REPEATING.search(plain):
        return 0
    match = _REPEAT_EVERY.search(plain)
    if not match:
        return None
    if match.group(1):
        return 30
    amount = match.group(2) or "1"
    number = int(amount) if amount.isdigit() else _NUMBERS[amount]
    return clean_repeat(number * (60 if match.group(3).startswith("hora") else 1))


def requested_urgency(text: str) -> str | None:
    plain = _plain(text)
    if _LOW_URGENCY.search(plain):
        return "baja"
    return "alta" if _HIGH_URGENCY.search(plain) else None


def significant_words(text: str) -> set[str]:
    return {w for w in re.findall(r"\w{4,}", _plain(text)) if w not in STOPWORDS and w not in _TASK_WORDS}


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
    def __init__(
        self,
        store: Store,
        llm: Any,
        config: Config,
        now: Callable[[], datetime] | None = None,
        search: Any = None,
    ):
        self.store = store
        self.llm = llm
        self.config = config
        self.search = search
        self._now = now or (lambda: datetime.now().astimezone())

    # --- Presentación ---

    def format_due(self, due_at: int | None) -> str:
        if due_at is None:
            return "sin fecha"
        moment = datetime.fromtimestamp(due_at, self._now().tzinfo)
        return f"{DAY_NAMES[moment.weekday()]} {moment.day} {MONTHS[moment.month - 1]}, {moment:%H:%M}"

    def format_task(self, task: Task) -> str:
        repeat = f" · 🔁 {format_interval(task.repeat_minutes)}" if task.repeat_minutes else ""
        return (
            f"{URGENCY_MARK[task.urgency]} #{task.id} {task.title}\n"
            f"     {task.category} · {self.format_due(task.due_at)}{repeat}"
        )

    def reminder_text(self, task: Task, now: datetime, repeated: bool = False) -> str:
        prefix = "🔁 Sigue pendiente:" if repeated else "⏰"
        text = f"{prefix} {URGENCY_MARK[task.urgency]} {task.title}\n{task.category} · urgencia {task.urgency}"
        if repeated:
            text += f"\nTe lo repito {format_interval(task.repeat_minutes)} hasta que lo marques como hecho."
        elif task.due_at is not None and now.timestamp() - task.due_at > 120:
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

    def _with_subtasks(self, task: Task, pending: list[Task] | None = None) -> str:
        children = [t for t in pending if t.parent_id == task.id] if pending is not None else self.store.subtasks(task.id, "pending")
        lines = [self.format_task(task)] + [f"     ↳ {self.format_task(child)}" for child in children]
        return "\n".join(lines)

    def _list_text(self) -> str:
        pending = self.store.pending_tasks()
        if not pending:
            return "No tienes tareas pendientes."
        pending_ids = {t.id for t in pending}
        roots = [t for t in pending if t.parent_id is None or t.parent_id not in pending_ids]
        return "Pendientes:\n" + "\n".join(self._with_subtasks(t, pending) for t in roots)

    def _confirmation(self, task: Task, prefix: str) -> Reply:
        text = f"{prefix}\n{self._with_subtasks(task)}\n\nSi algo está mal, dímelo y lo corrijo."
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
        repeat = clean_repeat(data.get("repeat_minutes")) or repeat_in_text(source) or None
        if repeat and due_at is None and not problem:
            due_at = int(reference.timestamp())  # "Repíteme X cada hora" sin hora: empieza ya.
        task = self.store.add_task(title, category, urgency, due_at, source, now_ts, repeat)
        for step in clean_subtasks(data.get("subtasks")):
            self.store.add_task(step, category, "media", None, source, now_ts, parent_id=task.id)
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
        repeat = clean_repeat(data.get("repeat_minutes"))
        if repeat is None:
            repeat = repeat_in_text(data.get("_source", ""))
        if repeat == 0:
            changes["repeat_minutes"] = None
        elif repeat:
            changes["repeat_minutes"] = repeat
            if task.due_at is None and "due_at" not in changes:
                changes.update(due_at=int(reference.timestamp()), notified_at=None)
        if not changes:
            return Reply("No entendí qué quieres cambiar. Por ejemplo: «ponla para el lunes a las 10».")
        updated = self.store.update_task(task.id, int(self._now().timestamp()), **changes)
        self._remember_last(updated)  # type: ignore[arg-type]
        return self._confirmation(updated, "Corregida:")  # type: ignore[arg-type]

    def _finish(self, task_id: Any, status: str) -> Reply:
        task = self._pending_by_id(task_id)
        if task is None:
            return Reply("No identifiqué esa tarea. Revisa /tareas y dime el número.")
        now_ts = int(self._now().timestamp())
        self.store.set_status(task.id, status, now_ts)
        lines = [f"{'✅ Hecho' if status == 'done' else '🗑 Cancelada'}: {task.title}"]
        children = self.store.subtasks(task.id, "pending")
        for child in children:  # Terminar o cancelar la principal arrastra a sus subtareas.
            self.store.set_status(child.id, status, now_ts)
        if children:
            verb = "completé" if status == "done" else "cancelé"
            lines.append(f"También {verb} sus {len(children)} subtareas pendientes.")
        if task.parent_id is not None and (parent := self._pending_by_id(task.parent_id)):
            if not self.store.subtasks(parent.id, "pending"):
                if any(child.status == "done" for child in self.store.subtasks(parent.id)):
                    self.store.set_status(parent.id, "done", now_ts)
                    lines.append(f"🎉 Con eso terminaste «{parent.title}».")
            else:
                left = len(self.store.subtasks(parent.id, "pending"))
                lines.append(f"Quedan {left} de «{parent.title}».")
        return Reply("\n".join(lines))

    def _add_subtasks(self, data: dict[str, Any], text: str) -> Reply:
        parent = self._pending_by_id(data.get("task_id")) or self._task_named_in(text) or self._last_task()
        if parent is None:
            return Reply("No sé a qué tarea agregar los pasos. Revisa /tareas y usa /sub con su número.")
        if parent.parent_id is not None:  # Un solo nivel: los pasos de un paso van a la principal.
            parent = self._pending_by_id(parent.parent_id) or parent
        steps = clean_subtasks(data.get("subtasks")) or clean_subtasks([data.get("title")])
        if not steps:
            return Reply("No entendí qué pasos agregar. Por ejemplo: «agrega a la mudanza: empacar libros».")
        now_ts = int(self._now().timestamp())
        for step in steps:
            self.store.add_task(step, parent.category, "media", None, text, now_ts, parent_id=parent.id)
        self._remember_last(parent)
        return self._confirmation(parent, f"Agregué {len(steps)} {'paso' if len(steps) == 1 else 'pasos'}:")

    def _remember(self, data: dict[str, Any], text: str) -> Reply:
        fact = str(data.get("title") or text).strip()[:500]
        fact_id = self.store.add_fact(fact, int(self._now().timestamp()))
        return Reply(f"🧠 Lo recordaré: {fact}", [[("🗑 Olvidar", f"forget:{fact_id}")]])

    def _web_search(self, data: dict[str, Any], text: str, reference: datetime) -> Reply:
        if self.search is None:
            return Reply("Todavía no tengo acceso a internet configurado.")
        query = str(data.get("title") or text).strip()[:300]
        upcoming_from = reference.date() if UPCOMING_HINT.search(f"{text} {query}") else None
        try:
            results = self.search.search(query, upcoming_from)
        except SearchError as exc:
            log.warning("La búsqueda falló: %s", exc)
            return Reply("No pude buscar en internet en este momento. Inténtalo otra vez en un rato.")
        if not results:
            return Reply("No encontré resultados sobre eso.")
        answer = self.llm.answer_from_web(text, query, results, reference)
        domains = dict.fromkeys(
            (urlsplit(r.url).hostname or "").removeprefix("www.") for r in results[:2]
        )
        sources = ", ".join(d for d in domains if d)
        return Reply(f"{answer}\n\nFuente: {sources}" if sources else answer)

    # --- Cancelar varias tareas: siempre con confirmación y decidido por código ---

    def _request_bulk_cancel(self, now: datetime) -> Reply:
        pending = self.store.pending_tasks()
        if not pending:
            return Reply("No tienes tareas pendientes.")
        self.store.kv_set(
            BULK_CANCEL_KEY,
            json.dumps({"ids": [t.id for t in pending], "expires": int(now.timestamp()) + BULK_CANCEL_SECONDS}),
        )
        question = "¿Cancelo esta tarea?" if len(pending) == 1 else f"¿Cancelo estas {len(pending)} tareas?"
        listing = "\n".join(self.format_task(t) for t in pending)
        return Reply(
            f"{question}\n{listing}\n\nResponde «sí» para confirmar.",
            [[("✅ Sí, cancelar", "bulk:yes"), ("✖ No", "bulk:no")]],
        )

    def _take_bulk_cancel(self, now: datetime) -> list[int] | None:
        """Devuelve y consume la solicitud pendiente, si sigue vigente."""
        raw = self.store.kv_get(BULK_CANCEL_KEY)
        if not raw:
            return None
        self.store.kv_set(BULK_CANCEL_KEY, "")
        request = json.loads(raw)
        return request["ids"] if int(now.timestamp()) <= request["expires"] else None

    def _confirm_bulk_cancel(self, ids: list[int], now: datetime) -> Reply:
        cancelled = [task for task_id in ids if (task := self._pending_by_id(task_id))]
        for task in cancelled:
            self.store.set_status(task.id, "cancelled", int(now.timestamp()))
        if not cancelled:
            return Reply("Esas tareas ya no estaban pendientes.")
        return Reply("🗑 Cancelada: " + cancelled[0].title if len(cancelled) == 1 else f"🗑 Cancelé {len(cancelled)} tareas.")

    def _bulk_cancel_flow(self, text: str, now: datetime) -> Reply | None:
        ids = self._take_bulk_cancel(now)
        plain = "".join(c for c in unicodedata.normalize("NFD", text.lower()) if unicodedata.category(c) != "Mn")
        plain = plain.strip(" ¡!¿?.,…")
        if ids is not None:
            if CONFIRM_YES.fullmatch(plain):
                return self._confirm_bulk_cancel(ids, now)
            if CONFIRM_NO.fullmatch(plain):
                return Reply("Listo, no cancelé nada.")
        return self._request_bulk_cancel(now) if BULK_CANCEL_REQUEST.search(plain) else None

    def _task_named_in(self, text: str, candidates: list[Task] | None = None) -> Task | None:
        """La tarea pendiente cuyo título comparte más palabras con el mensaje, si hay una sola."""
        words = significant_words(text)
        tasks = self.store.pending_tasks() if candidates is None else candidates
        scored = sorted(
            ((len(words & significant_words(task.title)), task) for task in tasks),
            key=lambda pair: pair[0],
            reverse=True,
        )
        if not scored or scored[0][0] == 0 or (len(scored) > 1 and scored[1][0] == scored[0][0]):
            return None
        return scored[0][1]

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
        if intent != "create_task" and repeat_in_text(text) == 0:
            # "Ya no me repitas X" no es cancelar X: el modelo los confundía.
            task = self._pending_by_id(data.get("task_id")) or self._task_named_in(text) or self._last_task()
            if task is None:
                return Reply("No sé de qué tarea quitar la repetición. Usa /repetir con su número y 0.")
            return self._edit({"task_id": task.id, "repeat_minutes": 0}, reference)
        if intent == "create_task":
            return self._create(data, text, reference)
        if intent == "edit_task":
            return self._edit({**data, "_source": text}, reference)
        if intent == "add_subtasks":
            return self._add_subtasks(data, text)
        if intent == "remember_fact":
            return self._remember(data, text)
        if intent == "web_search":
            return self._web_search(data, text, reference)
        if intent == "complete_task":
            task_id = data.get("task_id")
            if (task := self._pending_by_id(task_id)) and (steps := self.store.subtasks(task.id, "pending")):
                # Si la frase nombra un paso, se completa ese paso y no toda la tarea con sus pasos.
                if step := self._task_named_in(text, steps):
                    task_id = step.id
            return self._finish(task_id, "done")
        if intent == "cancel_task":
            return self._finish(data.get("task_id"), "cancelled")
        if intent == "list_tasks":
            return Reply(self._list_text())
        if (urgency := requested_urgency(text)) and (task := self._task_named_in(text)):
            # El modelo a veces toma "ponla urgente" como conversación; si nombra una tarea, se edita.
            return self._edit({"task_id": task.id, "urgency": urgency}, reference)
        if self.search is not None and LIVE_INFO_HINT.search(text):
            # El modelo a veces trata esto como conversación y contesta que no lo sabe.
            facts = "; ".join(fact for _, fact in self.store.search_facts(text, 3))
            return self._web_search({"title": f"{text} ({facts})" if facts else text}, text, reference)
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
        if command == "/sub":
            number, _, step = argument.strip().partition(" ")
            if not number.isdigit() or not step.strip():
                return Reply("Uso: /sub 3 empacar libros (agrega un paso a la tarea 3).")
            if self._pending_by_id(int(number)) is None:
                return Reply("No identifiqué esa tarea. Revisa /tareas y dime el número.")
            return self._add_subtasks({"task_id": int(number), "subtasks": [step]}, text)
        if command == "/repetir":
            parts = argument.split()
            if len(parts) != 2 or not all(p.isdigit() for p in parts):
                return Reply("Uso: /repetir 3 30 (tarea 3, cada 30 minutos). Con 0 deja de repetirse.")
            if self._pending_by_id(int(parts[0])) is None:
                return Reply("No identifiqué esa tarea. Revisa /tareas y dime el número.")
            return self._edit({"task_id": int(parts[0]), "repeat_minutes": int(parts[1])}, self._now())
        if command == "/urgente":
            if not argument.strip().isdigit():
                return Reply("Dime el número de la tarea, por ejemplo: /urgente 3")
            if self._pending_by_id(int(argument)) is None:
                return Reply("No identifiqué esa tarea. Revisa /tareas y dime el número.")
            return self._edit({"task_id": int(argument), "urgency": "alta"}, self._now())
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
        elif (bulk := self._bulk_cancel_flow(text, now)) is not None:
            reply = bulk
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
        if data in ("bulk:yes", "bulk:no"):
            now = self._now()
            ids = self._take_bulk_cancel(now)
            if ids is None:
                return Reply("Esa solicitud ya venció. Pídemelo otra vez si quieres.")
            return self._confirm_bulk_cancel(ids, now) if data == "bulk:yes" else Reply("Listo, no cancelé nada.")
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
