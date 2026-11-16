"""Recordatorios y resumen diario. No usa el modelo: es código determinista."""
from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import Any, Callable

from .assistant import Assistant, buttons_for, review_buttons
from .config import Config
from .store import Store

log = logging.getLogger(__name__)

SUMMARY_KEY = "last_summary_date"
EVENING_KEY = "last_evening_date"
WEEKLY_KEY = "last_weekly_date"
HABIT_KEY = "habit_reminded:"
SUNDAY = 6


class Scheduler:
    def __init__(
        self,
        store: Store,
        assistant: Assistant,
        config: Config,
        send: Callable[..., Any],
        now: Callable[[], datetime] | None = None,
    ):
        self.store = store
        self.assistant = assistant
        self.config = config
        self.send = send
        self._now = now or (lambda: datetime.now().astimezone())
        self.extra_ticks: list[Callable[[datetime], None]] = []  # Avisos de otras fuentes, como el calendario.

    def tick(self) -> None:
        if self.assistant.extras.quiet_until(self._now()) is not None:
            return  # «No me molestes»: nada se pierde, todo sale cuando termine el silencio.
        self._send_due_reminders()
        self._send_deadline_warnings()
        self._send_deadlines()
        self._send_repeats()
        self._send_habits()
        self._send_summary_if_needed()
        self._send_evening_if_needed()
        self._send_weekly_if_needed()
        for extra in self.extra_ticks:
            extra(self._now())

    def in_quiet_hours(self, now: datetime) -> bool:
        start, end = self.config.repeat_quiet_start, self.config.repeat_quiet_end
        moment = now.time()
        if start <= end:
            return start <= moment < end
        return moment >= start or moment < end  # El horario cruza la medianoche.

    def _send_repeats(self) -> None:
        now = self._now()
        if self.in_quiet_hours(now):
            return
        for task in self.store.due_repeats(int(now.timestamp())):
            try:
                self.send(self.assistant.reminder_text(task, now, repeated=True), buttons_for(task))
            except Exception as exc:
                log.warning("No se pudo repetir el recordatorio %s: %s", task.id, exc)
                return
            self.store.update_task(task.id, int(now.timestamp()), notified_at=int(now.timestamp()))

    def _send_due_reminders(self) -> None:
        now = self._now()
        for task in self.store.due_unnotified(int(now.timestamp())):
            try:
                self.send(self.assistant.reminder_text(task, now), buttons_for(task))
            except Exception as exc:  # Se reintenta en el siguiente ciclo.
                log.warning("No se pudo enviar el recordatorio %s: %s", task.id, exc)
                return
            self.store.update_task(task.id, int(now.timestamp()), notified_at=int(now.timestamp()))

    def _send_deadlines(self) -> None:
        now = self._now()
        for task in self.store.due_deadlines(int(now.timestamp())):
            try:
                self.send(self.assistant.deadline_text(task), buttons_for(task))
            except Exception as exc:  # Se reintenta en el siguiente ciclo.
                log.warning("No se pudo avisar el vencimiento de %s: %s", task.id, exc)
                return
            self.store.update_task(task.id, int(now.timestamp()), deadline_notified_at=int(now.timestamp()))

    def _send_deadline_warnings(self) -> None:
        """Avisa un día antes y una hora antes del vencimiento; antes solo avisaba cuando ya había vencido."""
        now = self._now()
        now_ts = int(now.timestamp())
        for task in self.store.deadline_warnings(now_ts):
            stage = 2 if task.deadline_at - now_ts <= 3600 else 1  # type: ignore[operator]
            if stage <= task.deadline_warned:
                continue
            try:
                self.send(self.assistant.deadline_warning_text(task, now), buttons_for(task))
            except Exception as exc:
                log.warning("No se pudo avisar que %s está por vencer: %s", task.id, exc)
                return
            self.store.update_task(task.id, now_ts, deadline_warned=stage)

    def _send_habits(self) -> None:
        now = self._now()
        today = now.date().isoformat()
        for habit, done, run in self.assistant.extras.habit_status(now.date()):
            key = f"{HABIT_KEY}{habit['id']}"
            if done or not habit["remind_at"] or f"{now:%H:%M}" < habit["remind_at"] or self.store.kv_get(key) == today:
                continue
            streak = f" Llevas {run} {'día' if run == 1 else 'días'} seguidos." if run else ""
            try:
                self.send(f"🔁 Hábito de hoy: {habit['title']}.{streak}", [[("✅ Hecho hoy", f"habit:{habit['id']}")]])
            except Exception as exc:
                log.warning("No se pudo recordar el hábito %s: %s", habit["id"], exc)
                return
            self.store.kv_set(key, today)

    def _send_evening_if_needed(self) -> None:
        now = self._now()
        today = now.date().isoformat()
        at = self.config.evening_time
        if at is None or now.time() < at or self.store.kv_get(EVENING_KEY) == today:
            return
        try:
            self.send(self.assistant.build_evening(), [])
        except Exception as exc:
            log.warning("No se pudo enviar el cierre del día: %s", exc)
            return
        self.store.kv_set(EVENING_KEY, today)

    def _send_weekly_if_needed(self) -> None:
        now = self._now()
        today = now.date().isoformat()
        at = self.config.weekly_time
        if at is None or now.weekday() != SUNDAY or now.time() < at or self.store.kv_get(WEEKLY_KEY) == today:
            return
        text, stale = self.assistant.build_weekly()
        try:
            self.send(text, [])
            for task in stale:
                self.send(self.assistant.stale_text(task), review_buttons(task.id))
        except Exception as exc:
            log.warning("No se pudo enviar la revisión de la semana: %s", exc)
            return
        self.store.kv_set(WEEKLY_KEY, today)

    def _send_summary_if_needed(self) -> None:
        now = self._now()
        today = now.date().isoformat()
        if now.time() < self.config.summary_time or self.store.kv_get(SUMMARY_KEY) == today:
            return
        try:
            self.send(self.assistant.build_summary(), [])
        except Exception as exc:
            log.warning("No se pudo enviar el resumen diario: %s", exc)
            return
        self.store.kv_set(SUMMARY_KEY, today)

    def run_forever(self, stop: threading.Event, interval: float = 15.0) -> None:
        while not stop.is_set():
            try:
                self.tick()
            except Exception:
                log.exception("Error en el ciclo de recordatorios")
            stop.wait(interval)
