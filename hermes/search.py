"""«¿Qué sabes de…?»: busca una persona o un tema en todo lo que Hermes guarda.

Tareas (también las terminadas), notas, correos, gastos, pagos, fechas, listas, enlaces guardados y el
calendario de hoy. Se busca aquí, sin modelo: lo que sale de tus correos nunca va a otro lado.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from typing import Any, Callable

from .extras import MONTH_NAMES, plain

MAX_PER_SECTION = 5
EMAIL_DAYS = 90
STOPWORDS = {"de", "del", "la", "las", "el", "los", "un", "una", "y", "o", "en", "con", "por", "para", "mi", "mis", "lo", "que", "sobre"}
ASK = re.compile(
    r"^(?:y\s+)?(?:que\s+(?:sabes|tienes|tengo|hay|sabemos)|dime\s+(?:todo\s+)?lo\s+que\s+(?:sabes|tienes|hay))"
    r"\s+(?:de|sobre|acerca\s+de)\s+(?:el\s+|la\s+|los\s+|las\s+)?(?P<what>.+)$"
)


def _terms(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9ñ@._-]+", plain(text)) if len(w) >= 2 and w not in STOPWORDS]


def _matches(text: str, terms: list[str]) -> bool:
    low = plain(text or "")
    return all(term in low for term in terms)


def _day(ts: int | None, tz: Any) -> str:
    if not ts:
        return ""
    moment = datetime.fromtimestamp(ts, tz)
    return f"{moment.day} {MONTH_NAMES[moment.month - 1][:3]}"


def _who(sender: str) -> str:
    """«Ana López <ana@x.com>» -> «Ana López»."""
    return re.sub(r"\s*<[^>]*>", "", sender).strip() or sender


def _iso_day(iso: str) -> str:
    year, month, day = (int(part) for part in iso[:10].split("-"))
    return f"{day} {MONTH_NAMES[month - 1][:3]}"


class Everything:
    def __init__(self, store: Any, config: Any, now: Callable[[], datetime], reply: Callable[..., Any],
                 agenda: Callable[[datetime], list[Any]] | None = None):
        self.store, self.config, self._now, self.R = store, config, now, reply
        self.agenda = agenda

    @property
    def enabled(self) -> bool:
        return getattr(self.config, "search_enabled", True)

    def handle(self, text: str, reference: datetime) -> Any:
        if not self.enabled:
            return None
        norm = " ".join(text.strip().strip(" .!?¡¿…").split())
        match = ASK.match(plain(norm))  # plain() conserva el largo: el tema se toma del texto original, con sus tildes.
        if not match:
            return None
        return self.find(norm[match.start("what"):match.end("what")])

    def command(self, argument: str) -> Any:
        if not self.enabled:
            return self.R("La búsqueda en todo está apagada. La enciendes en Ajustes → Funciones.")
        if not argument.strip():
            return self.R("Dime qué buscar, por ejemplo: /buscar Carlos o «¿qué sabes del contrato?».")
        return self.find(argument.strip())

    def sections(self, what: str) -> list[tuple[str, list[str]]]:
        terms = _terms(what)
        if not terms:
            return []
        now = self._now()
        tz = now.tzinfo
        found: list[tuple[str, list[str]]] = []

        def add(title: str, lines: list[str]) -> None:
            if lines:
                extra = f" (y {len(lines) - MAX_PER_SECTION} más)" if len(lines) > MAX_PER_SECTION else ""
                found.append((title + extra, lines[:MAX_PER_SECTION]))

        pending = [t for t in self.store.pending_tasks() if _matches(t.title, terms)]
        add("📌 Tareas pendientes", [f"{t.title}" + (f" · {_day(t.overdue_from, tz)}" if t.overdue_from else "") for t in pending])
        done = [t for t in self.store.finished_tasks(1000) if _matches(t.title, terms)]
        add("✅ Tareas terminadas", [f"{t.title} · {'hecha' if t.status == 'done' else 'cancelada'} el {_day(t.completed_at, tz)}"
                                    for t in done])
        notes = [text for _, text in self.store.list_facts(1000) if _matches(text, terms)]
        add("🧠 Notas", notes)
        since = int((now - timedelta(days=EMAIL_DAYS)).timestamp())
        emails = [m for m in self.store.recent_emails(since, 1000) if _matches(f"{m.sender} {m.subject} {m.summary}", terms)]
        add("✉️ Correos", [f"{_day(m.ts, tz)}, {_who(m.sender)}: «{m.subject}»" + (f", {m.summary}" if m.summary else "")
                          for m in emails])
        if getattr(self.config, "receipts_enabled", True):
            receipts = [r for r in self.store.receipts_between("2000-01-01", "2100-01-01")
                        if _matches(f"{r['merchant']} {r['category']} {r['items']}", terms)]
            add("🧾 Gastos", [f"{_iso_day(r['day'])}, {r['merchant']}: {r['total']:,.2f} {r['currency']}" for r in receipts])
        if getattr(self.config, "bills_enabled", True):
            bills = [b for b in self.store.bills() if _matches(b["name"], terms)]
            add("💳 Pagos", [f"{b['name']}: vence el {_iso_day(b['next_due'])}" for b in bills])
        dates = [d for d in self.store.list_dates() if _matches(f"{d['name']} {d['kind']}", terms)]
        add("🎂 Fechas", [f"{d['kind'].capitalize()} de {d['name']}: {d['day']} de {MONTH_NAMES[d['month'] - 1]}" if d["name"]
                         else f"Aniversario: {d['day']} de {MONTH_NAMES[d['month'] - 1]}" for d in dates])
        items = []
        for name, _ in self.store.list_names():
            items += [f"{name}: {i['text']}" + (" ✓" if i["done"] else "") for i in self.store.list_entries(name)
                      if _matches(f"{name} {i['text']}", terms)]
        add("📋 Listas", items)
        if getattr(self.config, "links_enabled", True) and hasattr(self.store, "links"):
            links = [l for l in self.store.links() if _matches(f"{l['title']} {l['summary']} {l['url']}", terms)]
            add("📚 Enlaces guardados", [f"{l['title'] or l['url']}" + (" (leído)" if l["read_at"] else "") for l in links])
        if self.agenda is not None:
            try:
                events = [e for e in self.agenda(now) if _matches(f"{e.title} {json.dumps(getattr(e, 'attendees', ()))}", terms)]
            except Exception:
                events = []
            add("📅 Hoy en tu calendario", [e.label() for e in events])
        return found

    def find(self, what: str) -> Any:
        what = " ".join(what.split())[:80]
        sections = self.sections(what)
        if not sections:
            return self.R(f"No encontré nada de «{what}» en tus tareas, notas, correos, gastos, pagos, fechas ni listas.")
        parts = [f"🔎 Lo que sé de «{what}»:"]
        for title, lines in sections:
            parts.append(f"\n{title}:")
            parts += [f"• {line}" for line in lines]
        return self.R("\n".join(parts))
