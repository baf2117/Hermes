"""Planear mi día: un orden con horas para las tareas que urgen, en los huecos libres del calendario.

Se calcula aquí, sin modelo. Después del resumen de la mañana Hermes propone el plan; si lo aceptas, cada
tarea queda con esa hora y te avisa a su tiempo. Si no, todo queda como estaba.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, time, timedelta
from typing import Any, Callable

from .extras import plain
from .scheduler import SUMMARY_KEY

SLOT_MINUTES = 45  # Lo que se le aparta a cada tarea.
GAP_MINUTES = 15  # Respiro entre una tarea y la siguiente, y antes de cada evento.
EVENT_MINUTES = 60  # Duración supuesta de un evento sin hora de fin.
MAX_TASKS = 6
SENT_KEY = "day_plan_sent"
PLAN_KEY = "day_plan"
ASK = re.compile(r"^(?:planea|planifica|organiza|acomoda|arma)(?:me)?\s+(?:mi\s+|el\s+)?dia(?:\s+de\s+hoy)?$|^que\s+hago\s+hoy$")


def _round_up(moment: datetime) -> datetime:
    """Al siguiente cuarto de hora."""
    moment = moment.replace(second=0, microsecond=0)
    extra = (-moment.minute) % 15
    return moment + timedelta(minutes=extra)


class DayPlan:
    def __init__(
        self,
        store: Any,
        config: Any,
        now: Callable[[], datetime],
        reply: Callable[..., Any],
        events: Callable[[datetime], list[Any]] | None = None,
    ):
        self.store, self.config, self._now, self.R = store, config, now, reply
        self.events = events  # Los eventos de hoy del calendario, si está conectado.
        self.send: Callable[[str, list], None] | None = None

    @property
    def enabled(self) -> bool:
        return getattr(self.config, "day_plan_enabled", True)

    # --- Propuesta ---

    def _candidates(self, now: datetime) -> list[tuple[Any, str]]:
        """Tareas que urgen hoy, de la más apremiante a la menos, con el motivo."""
        today, stamp = now.date(), now.timestamp()
        end_of_today = datetime.combine(today + timedelta(days=1), time(0), now.tzinfo).timestamp()
        end_of_tomorrow = end_of_today + 86400
        ranked = []
        for task in self.store.pending_tasks():
            if task.kind != "task" or task.parent_id is not None:
                continue
            if task.due_at is not None and stamp <= task.due_at < end_of_today and task.deadline_at is None:
                continue  # Ya tiene hora hoy: se respeta como está.
            if task.overdue_from is not None and task.overdue_from < stamp:
                ranked.append((0, task.overdue_from, task, "atrasada"))
            elif task.deadline_at is not None and task.deadline_at < end_of_today:
                ranked.append((1, task.deadline_at, task, "vence hoy"))
            elif task.deadline_at is not None and task.deadline_at < end_of_tomorrow:
                ranked.append((2, task.deadline_at, task, "vence mañana"))
            elif task.urgency == "alta" and task.due_at is None and task.deadline_at is None:
                ranked.append((3, task.id, task, "urgente"))
        ranked.sort(key=lambda item: (item[0], item[1]))
        return [(task, why) for _, _, task, why in ranked[:MAX_TASKS]]

    def _busy(self, now: datetime) -> list[tuple[datetime, datetime, str]]:
        """Lo que ya ocupa el día: eventos con hora y tareas que ya tienen hora hoy."""
        blocks = []
        for event in (self.events(now) if self.events else []):
            if event.start is None:
                continue
            end = event.end or event.start + timedelta(minutes=EVENT_MINUTES)
            blocks.append((event.start, end, f"{event.start:%H:%M} {event.title}"))
        end_of_today = datetime.combine(now.date() + timedelta(days=1), time(0), now.tzinfo)
        for task in self.store.pending_tasks():
            if task.due_at is not None and now.timestamp() <= task.due_at < end_of_today.timestamp():
                start = datetime.fromtimestamp(task.due_at, now.tzinfo)
                blocks.append((start, start + timedelta(minutes=30), f"{start:%H:%M} {task.title}"))
        return sorted(blocks)

    def propose(self, now: datetime) -> tuple[str, list[tuple[int, int]]] | None:
        tasks = self._candidates(now)
        if not tasks:
            return None
        day_start = datetime.combine(now.date(), self.config.work_start, now.tzinfo)
        day_end = datetime.combine(now.date(), self.config.work_end, now.tzinfo)
        busy = self._busy(now)
        cursor = max(_round_up(now), day_start)
        slots, lines, left = [], [], []
        for task, why in tasks:
            while True:
                finish = cursor + timedelta(minutes=SLOT_MINUTES)
                clash = next((b for b in busy if cursor < b[1] + timedelta(minutes=GAP_MINUTES)
                              and b[0] < finish + timedelta(minutes=GAP_MINUTES)), None)
                if clash is None:
                    break
                cursor = _round_up(clash[1] + timedelta(minutes=GAP_MINUTES))
            if finish > day_end:
                left.append(task.title)
                continue
            slots.append((task.id, int(cursor.timestamp())))
            lines.append(f"• {cursor:%H:%M} {task.title} ({why})")
            cursor = _round_up(finish + timedelta(minutes=GAP_MINUTES))
        if not slots:
            text = (f"🗓 Hoy ya no queda tiempo libre en tu horario ({self.config.work_start:%H:%M}–{self.config.work_end:%H:%M}) "
                    f"para lo que urge: {', '.join(left)}.")
            return text, []
        parts = ["🗓 Te propongo este orden para hoy:", *lines]
        fixed = [label for start, _, label in busy if start.date() == now.date() and start >= now]
        if fixed:
            parts.append("Ya tenías: " + "; ".join(fixed[:5]) + ".")
        if left:
            parts.append("No cupieron: " + ", ".join(left) + ".")
        parts.append("¿Te las acomodo a esas horas? Te aviso de cada una a su tiempo.")
        return "\n".join(parts), slots

    def offer(self, now: datetime) -> Any:
        proposal = self.propose(now)
        if proposal is None:
            return self.R("Hoy no tienes tareas atrasadas, que venzan pronto o urgentes sin fecha. Nada que acomodar. 🙌")
        text, slots = proposal
        if not slots:
            return self.R(text)
        day = int(now.strftime("%Y%m%d"))
        self.store.kv_set(PLAN_KEY, json.dumps({"day": day, "slots": slots}))
        return self.R(text, [[("✅ Acomódalas", f"planok:{day}"), ("🚫 No, gracias", f"planno:{day}")]])

    # --- Mañana: sale después del resumen ---

    def tick(self, now: datetime) -> None:
        today = now.date().isoformat()
        if not self.enabled or self.send is None or self.store.kv_get(SENT_KEY) == today:
            return
        if self.store.kv_get(SUMMARY_KEY) != today or now.time() >= self.config.work_end:
            return
        self.store.kv_set(SENT_KEY, today)  # Una vez al día, haya o no algo que proponer.
        proposal = self.propose(now)
        if proposal is None or not proposal[1]:
            return
        reply = self.offer(now)
        self.send(reply.text, reply.buttons)

    # --- Respuestas ---

    def accept(self, day: int) -> Any:
        try:
            plan = json.loads(self.store.kv_get(PLAN_KEY) or "{}")
        except ValueError:
            plan = {}
        if plan.get("day") != day or day != int(self._now().strftime("%Y%m%d")):
            return self.R("Ese plan ya venció. Pídeme otro con /plan.")
        moved = 0
        for task_id, stamp in plan.get("slots", []):
            task = self.store.get_task(task_id)
            if task is None or task.status != "pending":
                continue
            # Solo cambia cuándo te avisa; el vencimiento original se respeta, aunque ya haya pasado.
            self.store.update_task(task_id, int(self._now().timestamp()), due_at=stamp, notified_at=None)
            moved += 1
        self.store.kv_set(PLAN_KEY, "{}")
        return self.R(f"Listo: acomodé {moved} {'tarea' if moved == 1 else 'tareas'}. Te aviso de cada una a su hora.")

    def decline(self, day: int) -> Any:
        self.store.kv_set(PLAN_KEY, "{}")
        return self.R("Va, las dejo como estaban.")

    def handle(self, text: str, reference: datetime) -> Any:
        if not ASK.match(plain(text).strip().strip(" .!?¡¿…")):
            return None
        return self.command("")

    def command(self, _: str) -> Any:
        if not self.enabled:
            return self.R("Planear mi día está apagado. Lo enciendes en Ajustes → Funciones.")
        return self.offer(self._now())
