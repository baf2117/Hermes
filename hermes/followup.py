"""Correos que esperan respuesta: lo que te toca contestar y lo que te deben contestar.

Solo lectura y solo encabezados: quién, a quién, asunto y fecha de cada mensaje de la conversación. Nunca
se lee el texto ni se manda nada, y nada de esto pasa por un modelo.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, time, timedelta
from email.utils import parseaddr
from typing import Any, Callable

from .extras import plain
from .gmail import DEFAULT_ACCOUNT, GmailAuthError, GmailError
from .scheduler import SUMMARY_KEY

log = logging.getLogger(__name__)

LOOKBACK_DAYS = 14
MAX_THREADS = 25  # Por cuenta y por revisión: pocas llamadas a Google.
REPEAT_DAYS = 7  # Una misma conversación se vuelve a mencionar a la semana si sigue igual.
SENT_KEY = "followup_sent"
SEEN_KEY = "followup_seen"
HIDDEN_KEY = "followup_hidden"
SHOWN_KEY = "followup_shown"
AUTOMATIC = re.compile(r"no-?reply|noreply|notifica|notification|mailer-daemon|newsletter|bounce", re.IGNORECASE)
ASK = re.compile(
    r"^(?:que\s+|cuales\s+)?correos\s+(?:tengo\s+)?(?:pendientes|sin\s+(?:contestar|responder|respuesta))"
    r"|^(?:a\s+quien\s+le\s+debo|quien\s+me\s+debe)\s+(?:una\s+)?respuesta$"
)


def _name(raw: str) -> str:
    name, address = parseaddr(raw)
    return name.strip() or address.strip() or raw


def _ago(ts: int, now: datetime) -> str:
    days = (now.date() - datetime.fromtimestamp(ts, now.tzinfo).date()).days
    return "hoy" if days <= 0 else "ayer" if days == 1 else f"hace {days} días"


class MailFollowup:
    def __init__(
        self,
        clients: list[tuple[str, Any]],
        store: Any,
        config: Any,
        now: Callable[[], datetime],
        reply: Callable[..., Any],
    ):
        self.clients, self.store, self.config, self._now, self.R = clients, store, config, now, reply
        self.send: Callable[[str, list], None] | None = None
        self._me: dict[str, str] = {}

    @property
    def enabled(self) -> bool:
        return getattr(self.config, "followup_enabled", True)

    def _address(self, account: str, client: Any) -> str:
        if account not in self._me:
            self._me[account] = client.address().lower()
        return self._me[account]

    # --- Revisión ---

    def scan(self, now: datetime) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """(te toca contestar, te deben contestar), del más viejo al más nuevo."""
        days = getattr(self.config, "followup_days", 3)
        since = int((now - timedelta(days=LOOKBACK_DAYS)).timestamp())
        limit = int((now - timedelta(days=days)).timestamp())
        hidden = set(self._load(HIDDEN_KEY))
        owe, waiting = [], []
        for account, client in self.clients:
            try:
                me = self._address(account, client)
                owe += self._owe(account, client, since, limit, hidden)
                waiting += self._waiting(account, client, me, since, limit, hidden)
            except GmailAuthError as exc:
                log.warning("Correos pendientes %s: hace falta volver a autorizar (%s)", account, exc)
            except GmailError as exc:
                log.warning("Correos pendientes %s: no pude revisar: %s", account, exc)
        return sorted(owe, key=lambda i: i["ts"]), sorted(waiting, key=lambda i: i["ts"])

    def _owe(self, account: str, client: Any, since: int, limit: int, hidden: set[str]) -> list[dict[str, Any]]:
        """Correos importantes que llegaron hace días y en cuya conversación no has escrito después."""
        prefix = "" if account == DEFAULT_ACCOUNT else f"{account}:"
        found, threads = [], set()
        for note in self.store.recent_emails(since):
            if note.account != account or not note.important or note.handled or note.ts > limit:
                continue
            if prefix and not note.gmail_id.startswith(prefix):
                continue
            thread = client.thread_of(note.gmail_id[len(prefix):])
            key = f"{account}:{thread}"
            if key in hidden or key in threads or len(threads) >= MAX_THREADS:
                continue
            threads.add(key)
            messages = client.thread(thread)
            if not messages or messages[-1].sent or any(m.sent and m.ts > note.ts for m in messages):
                continue  # Ya contestaste.
            found.append({"key": key, "account": account, "who": _name(note.sender), "subject": note.subject, "ts": note.ts})
        return found

    def _waiting(self, account: str, client: Any, me: str, since: int, limit: int, hidden: set[str]) -> list[dict[str, Any]]:
        """Conversaciones que empezaste, donde lo último lo escribiste tú hace días y nadie ha contestado."""
        found = []
        for thread in client.sent_threads(since)[:MAX_THREADS]:
            key = f"{account}:{thread}"
            if key in hidden:
                continue
            messages = client.thread(thread)
            # Solo conversaciones que empezaste tú: contestarle a alguien («gracias») no siempre espera respuesta.
            if not messages or not messages[0].sent or not messages[-1].sent or messages[-1].ts > limit:
                continue
            others = [raw for raw in messages[-1].to if parseaddr(raw)[1].lower() not in ("", me)]
            if not others or all(AUTOMATIC.search(raw) for raw in others):
                continue  # Notas para ti mismo o respuestas a avisos automáticos.
            found.append({"key": key, "account": account, "who": _name(others[0]) + (" y otros" if len(others) > 1 else ""),
                          "subject": messages[0].subject, "ts": messages[-1].ts})
        return found

    # --- Mensaje ---

    def _text(self, owe: list[dict[str, Any]], waiting: list[dict[str, Any]], now: datetime) -> str:
        def line(item: dict[str, Any]) -> str:
            tag = "" if item["account"] == DEFAULT_ACCOUNT else f"[{item['account']}] "
            return f"• {tag}{item['who']}, «{item['subject']}» ({_ago(item['ts'], now)})"

        parts = ["📬 Correos que esperan respuesta:"]
        if owe:
            parts += ["Te toca contestar:", *map(line, owe)]
        if waiting:
            parts += ["Te deben respuesta:", *map(line, waiting)]
        return "\n".join(parts)

    def report(self, now: datetime | None = None) -> Any:
        now = now or self._now()
        if not self.enabled:
            return self.R("Correos que esperan respuesta está apagado. Lo enciendes en Ajustes → Funciones.")
        if not self.clients:
            return self.R("No tengo tu correo conectado.")
        owe, waiting = self.scan(now)
        if not owe and not waiting:
            days = getattr(self.config, "followup_days", 3)
            return self.R(f"📬 Nada pendiente: no hay correos importantes sin contestar ni tuyos sin respuesta de más de {days} días.")
        return self._offer(owe, waiting, now)

    def _offer(self, owe: list[dict[str, Any]], waiting: list[dict[str, Any]], now: datetime) -> Any:
        day = int(now.strftime("%Y%m%d"))
        self.store.kv_set(SHOWN_KEY, json.dumps({"day": day, "keys": [i["key"] for i in owe + waiting]}))
        return self.R(self._text(owe, waiting, now), [[("🔕 Ya no me los muestres", f"fuhide:{day}")]])

    def hide(self, day: int) -> Any:
        try:
            shown = json.loads(self.store.kv_get(SHOWN_KEY) or "{}")
        except ValueError:
            shown = {}
        if shown.get("day") != day:
            return self.R("Esa lista ya cambió. Pídeme la nueva con /correos.")
        hidden = self._load(HIDDEN_KEY)
        hidden += [key for key in shown.get("keys", []) if key not in hidden]
        self.store.kv_set(HIDDEN_KEY, json.dumps(hidden[-500:]))
        return self.R("Listo, esos ya no te los vuelvo a mencionar.")

    def _load(self, key: str) -> Any:
        try:
            return json.loads(self.store.kv_get(key) or ("[]" if key == HIDDEN_KEY else "{}"))
        except ValueError:
            return [] if key == HIDDEN_KEY else {}

    # --- Una vez al día, después del resumen de la mañana ---

    def tick(self, now: datetime) -> None:
        today = now.date().isoformat()
        if not self.enabled or self.send is None or not self.clients or self.store.kv_get(SENT_KEY) == today:
            return
        if self.store.kv_get(SUMMARY_KEY) != today or now.time() >= time(21, 0):
            return
        self.store.kv_set(SENT_KEY, today)
        owe, waiting = self.scan(now)
        seen = self._load(SEEN_KEY)
        recent = (now - timedelta(days=REPEAT_DAYS)).date().isoformat()
        fresh = lambda items: [i for i in items if seen.get(i["key"], "") < recent]  # noqa: E731
        owe, waiting = fresh(owe), fresh(waiting)
        if not owe and not waiting:
            return
        for item in owe + waiting:
            seen[item["key"]] = today
        self.store.kv_set(SEEN_KEY, json.dumps({k: v for k, v in seen.items() if v >= recent}))
        reply = self._offer(owe, waiting, now)
        self.send(reply.text, reply.buttons)

    def handle(self, text: str, reference: datetime) -> Any:
        if not ASK.match(plain(text).strip().strip(" .!?¡¿…")):
            return None
        return self.report()
