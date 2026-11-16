"""Preparación antes de una reunión: lo que Hermes ya sabe de esa gente y de ese tema.

Se arma en esta computadora, sin modelo: compara los invitados y las palabras del título del evento con los
correos guardados (remitente, asunto y el resumen que ya tenía), las tareas pendientes y las notas. Nada de
esto sale de aquí; el título del evento tampoco va a ningún modelo.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from .extras import plain

LOOKBACK_DAYS = 14
MAX_EMAILS = 3
MAX_TASKS = 3
MAX_NOTES = 2
# Palabras de un título que no dicen de qué trata la reunión.
STOPWORDS = {
    "reunion", "reuniones", "llamada", "junta", "meeting", "call", "sync", "semanal", "diaria", "mensual", "revision",
    "sesion", "cita", "para", "sobre", "equipo", "team", "weekly", "daily", "zoom", "meet", "teams", "google", "with",
    "the", "and", "con", "del", "los", "las", "una", "uno", "por", "que", "entre", "seguimiento", "follow", "catch",
    "almuerzo", "desayuno", "cafe", "hoy", "manana", "virtual", "presencial", "online", "invitacion", "evento",
}


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9ñ]+", plain(text)) if len(w) >= 4 and w not in STOPWORDS and not w.isdigit()}


def _has_word(text: str, words: set[str]) -> bool:
    return bool(words & set(re.findall(r"[a-z0-9ñ]+", plain(text))))


def _ago(ts: int, now: datetime) -> str:
    days = (now.date() - datetime.fromtimestamp(ts, now.tzinfo).date()).days
    return "hoy" if days <= 0 else "ayer" if days == 1 else f"hace {days} días"


class Briefing:
    def __init__(self, store: Any, config: Any = None):
        self.store, self.config = store, config

    def lines(self, event: Any, now: datetime) -> list[str]:
        if not getattr(self.config, "briefing_enabled", True):
            return []
        attendees = [(email.lower(), name) for email, name in getattr(event, "attendees", ())]
        names = {first for _, name in attendees if (first := plain(name).split()[0] if name.strip() else "") and len(first) >= 3}
        topic = _words(event.title)
        lines: list[str] = []

        # Correos de los invitados, y si no hay, correos cuyo asunto trata del tema.
        since = int(now.timestamp()) - LOOKBACK_DAYS * 86400
        emails = self.store.recent_emails(since)
        found, seen = [], set()
        for email, name in attendees:
            mine = [m for m in emails if email and email in m.sender.lower()]
            if mine and mine[0].id not in seen:
                found.append(mine[0])
                seen.add(mine[0].id)
        if len(found) < MAX_EMAILS and topic:
            for m in emails:
                if m.id not in seen and _has_word(m.subject, topic):
                    found.append(m)
                    seen.add(m.id)
        for m in found[:MAX_EMAILS]:
            sender = re.sub(r"\s*<[^>]*>", "", m.sender).strip() or m.sender
            detail = f": {m.summary}" if m.summary else ""
            lines.append(f"✉️ {sender} te escribió {_ago(m.ts, now)}, «{m.subject}»{detail}")

        # Tareas pendientes que mencionan a los invitados o el tema.
        wanted = topic | names
        if wanted:
            tasks = [t for t in self.store.pending_tasks() if _has_word(t.title, wanted)]
            lines += [f"📌 Pendiente: {t.title}" for t in tasks[:MAX_TASKS]]
            notes = [text for _, text in self.store.list_facts(500) if _has_word(text, wanted)]
            lines += [f"🧠 {text}" for text in notes[:MAX_NOTES]]
        return lines
