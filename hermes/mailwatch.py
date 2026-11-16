"""Vigila la bandeja principal de Gmail y avisa por Telegram de los correos importantes.

Reglas de seguridad:
- El correo es texto de terceros: solo se le pasa al modelo local para clasificarlo, y de su
  respuesta solo se usan campos acotados (importante, resumen, tarea sugerida, fecha).
- Nada se crea solo: una tarea sugerida nace únicamente cuando el dueño pulsa el botón.
- Los avisos nunca llevan enlaces y siempre muestran la dirección real del remitente.
"""
from __future__ import annotations

import logging
import re
import threading
from datetime import datetime
from typing import Any, Callable

from .config import Config
from .gmail import DEFAULT_ACCOUNT, Email, GmailAuthError, GmailError
from .llm import LLMError
from .store import MailNote, Store

log = logging.getLogger(__name__)

SINCE_KEY = "mail_since"
AUTH_ALERT_KEY = "mail_auth_alert"
MAX_PER_TICK = 6  # Cada correo ocupa unos segundos del modelo local, que también atiende la voz.
AUTH_RETRY_SECONDS = 1800
OPEN_HOURS = 48
_URL = re.compile(r"(?i)\b(?:https?://|www\.)\S+")

AUTH_ALERT = (
    "📧 Perdí el permiso para leer tu correo {account} (caducó o lo retiraste).\n"
    "Para renovarlo, en tu computadora abre una terminal en la carpeta de Hermes y ejecuta:\n"
    "python -m hermes gmail-auth {account}"
)


def clean(value: Any, limit: int) -> str:
    """Texto del modelo listo para mostrar: sin enlaces, en una línea y con tope de largo."""
    if not isinstance(value, str):
        return ""
    text = re.sub(r"\s+", " ", _URL.sub("", value)).strip(" .,;:-")
    return text[:limit].rstrip()


def resolve_due(data: dict[str, Any], now: datetime, default_time: Any) -> int | None:
    """Fecha sugerida por el modelo, solo si es válida y futura."""
    try:
        day = datetime.strptime(str(data.get("due_date") or ""), "%Y-%m-%d").date()
    except ValueError:
        return None
    try:
        moment = datetime.strptime(str(data.get("due_time") or ""), "%H:%M").time()
    except ValueError:
        moment = default_time
    due = datetime.combine(day, moment, now.tzinfo)
    return int(due.timestamp()) if due > now else None


def mail_buttons(note: MailNote) -> list[list[tuple[str, str]]]:
    if note.task_title:
        return [[("➕ Crear tarea", f"mailtask:{note.id}"), ("Ignorar", f"mailskip:{note.id}")]]
    return [[("✓ Visto", f"mailskip:{note.id}")]]


class MailWatcher:
    def __init__(
        self,
        store: Store,
        gmail: Any,
        llm: Any,
        config: Config,
        send: Callable[..., Any],
        describe: Callable[[MailNote], str],
        now: Callable[[], datetime] | None = None,
        account: str = DEFAULT_ACCOUNT,
    ):
        self.store, self.gmail, self.llm, self.config, self.send, self.describe = store, gmail, llm, config, send, describe
        self._now = now or (lambda: datetime.now().astimezone())
        self._auth_retry_at = 0.0
        self.account = account
        # La cuenta personal conserva las claves originales; las demás llevan su nombre.
        suffix = "" if account == DEFAULT_ACCOUNT else f":{account}"
        self._since_key, self._alert_key, self._id_prefix = SINCE_KEY + suffix, AUTH_ALERT_KEY + suffix, suffix[1:] + suffix[:1]

    def tick(self) -> None:
        now = self._now()
        if now.timestamp() < self._auth_retry_at:
            return
        try:
            self._notify_pending(now)
            self._read_new(now)
        except GmailAuthError as exc:
            log.warning("Correo %s: hace falta volver a autorizar (%s)", self.account, exc)
            self._auth_retry_at = now.timestamp() + AUTH_RETRY_SECONDS
            if self.store.kv_get(self._alert_key) != "1":
                try:
                    self.send(AUTH_ALERT.format(account=self.account), [])
                    self.store.kv_set(self._alert_key, "1")
                except Exception as send_exc:
                    log.warning("Correo: no pude avisar de la autorización: %s", send_exc)
        except GmailError as exc:
            log.warning("Correo %s: no pude revisar la bandeja: %s", self.account, exc)

    def _read_new(self, now: datetime) -> None:
        raw_since = self.store.kv_get(self._since_key)
        if raw_since is None:
            # Primera vez: empieza desde ahora para no avisar de todo el correo viejo.
            self.store.kv_set(self._since_key, str(int(now.timestamp())))
            log.info("Correo %s: vigilancia iniciada", self.account)
            return
        since = int(raw_since)
        ids = [i for i in self.gmail.list_ids(since - 60) if not self.store.email_known(self._id_prefix + i)]
        if self.store.kv_get(self._alert_key) == "1":
            self.store.kv_set(self._alert_key, "0")
        for message_id in ids[:MAX_PER_TICK]:
            email = self.gmail.get(message_id)
            try:
                data = self.llm.classify_email(email.sender, email.subject, email.body, now, self.config.categories)
            except LLMError as exc:
                log.warning("Correo: el modelo no pudo clasificar; reintento luego: %s", exc)
                return
            note = self._save(email, data, now)
            since = max(since, email.ts)
            self.store.kv_set(self._since_key, str(since))
            if note.important:
                self._notify(note, now)

    def _save(self, email: Email, data: dict[str, Any], now: datetime) -> MailNote:
        important = data.get("important") is True
        title = clean(data.get("task_title"), 120) if important else ""
        category = str(data.get("category") or "").strip().lower()
        if category not in self.config.categories:
            # Una cuenta llamada como una categoría («trabajo») sugiere esa categoría.
            suggested = self.account != DEFAULT_ACCOUNT and self.account in self.config.categories
            category = self.account if suggested else ""
        return self.store.add_email(
            account=self.account,
            gmail_id=self._id_prefix + email.id,
            ts=email.ts,
            sender=email.sender,
            subject=email.subject,
            summary=clean(data.get("summary"), 240),
            important=important,
            task_title=title or None,
            task_category=category or None,
            task_due_at=resolve_due(data, now, self.config.default_task_time) if title else None,
        )

    def _notify_pending(self, now: datetime) -> None:
        for note in self.store.unnotified_emails(self.account):
            self._notify(note, now)

    def _notify(self, note: MailNote, now: datetime) -> None:
        try:
            self.send(self.describe(note), mail_buttons(note))
        except Exception as exc:  # Se reintenta en el siguiente ciclo.
            log.warning("Correo: no pude enviar el aviso %s: %s", note.id, exc)
            return
        self.store.mark_email(note.id, notified_at=int(now.timestamp()))

def run_watchers(watchers: list[MailWatcher], stop: threading.Event, interval: float) -> None:
    """Revisa las cuentas una tras otra: el modelo local atiende un correo a la vez."""
    while not stop.is_set():
        for watcher in watchers:
            try:
                watcher.tick()
            except Exception:
                log.exception("Error en la vigilancia del correo %s", watcher.account)
        stop.wait(interval)
