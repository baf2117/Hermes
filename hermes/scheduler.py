"""Recordatorios y resumen diario. No usa el modelo: es código determinista."""
from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import Any, Callable

from .assistant import Assistant, reminder_buttons
from .config import Config
from .store import Store

log = logging.getLogger(__name__)

SUMMARY_KEY = "last_summary_date"


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

    def tick(self) -> None:
        self._send_due_reminders()
        self._send_deadlines()
        self._send_repeats()
        self._send_summary_if_needed()

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
                self.send(self.assistant.reminder_text(task, now, repeated=True), reminder_buttons(task.id))
            except Exception as exc:
                log.warning("No se pudo repetir el recordatorio %s: %s", task.id, exc)
                return
            self.store.update_task(task.id, int(now.timestamp()), notified_at=int(now.timestamp()))

    def _send_due_reminders(self) -> None:
        now = self._now()
        for task in self.store.due_unnotified(int(now.timestamp())):
            try:
                self.send(self.assistant.reminder_text(task, now), reminder_buttons(task.id))
            except Exception as exc:  # Se reintenta en el siguiente ciclo.
                log.warning("No se pudo enviar el recordatorio %s: %s", task.id, exc)
                return
            self.store.update_task(task.id, int(now.timestamp()), notified_at=int(now.timestamp()))

    def _send_deadlines(self) -> None:
        now = self._now()
        for task in self.store.due_deadlines(int(now.timestamp())):
            try:
                self.send(self.assistant.deadline_text(task), reminder_buttons(task.id))
            except Exception as exc:  # Se reintenta en el siguiente ciclo.
                log.warning("No se pudo avisar el vencimiento de %s: %s", task.id, exc)
                return
            self.store.update_task(task.id, int(now.timestamp()), deadline_notified_at=int(now.timestamp()))

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
