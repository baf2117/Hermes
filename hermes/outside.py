"""Tres ventanas hacia fuera, todas apagadas hasta que el dueño las configura en .env:

- Clima (HERMES_WEATHER=latitud,longitud): una línea en el resumen de la mañana, solo si hay algo que avisar.
- Calendario de Google, de solo lectura: la agenda del día en el resumen y un aviso antes de cada evento.
- Vigilante externo (HERMES_HEARTBEAT_URL): Hermes avisa cada pocos minutos que sigue vivo; si deja de
  hacerlo (la computadora se apagó o se suspendió), ese servicio le avisa al dueño.

Lo que llega de fuera son datos: los títulos de los eventos se limpian y nunca pasan por el modelo.
"""
from __future__ import annotations

import json
import logging
import threading
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from .gmail import DEFAULT_ACCOUNT, GmailAuthError, GmailClient, GmailError, valid_account
from .mailwatch import clean
from .store import Store

log = logging.getLogger(__name__)

TIMEOUT = 10.0
Fetch = Callable[[str], bytes]


def fetch_url(url: str) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "hermes"}), timeout=TIMEOUT) as response:
        return response.read(200_000)


# --- Clima ---

WEATHER_API = "https://api.open-meteo.com/v1/forecast"
RAIN_PERCENT = 50
HOT_DEGREES = 32
COLD_DEGREES = 8
# Códigos de tiempo de Open-Meteo (WMO) -> cómo se ve el día. Los de lluvia y tormenta se avisan aparte.
SKY = (
    (0, "☀️", "despejado"), (2, "🌤", "con algunas nubes"), (3, "☁️", "nublado"), (48, "🌫", "con neblina"),
    (67, "🌦", "con llovizna"), (77, "🌨", "con nieve"), (82, "🌦", "con chubascos"), (99, "⛈", "con tormentas"),
)


def _sky(code: int | None) -> tuple[str, str]:
    if code is None:
        return "🌡", ""
    for top, mark, words in SKY:
        if code <= top:
            return mark, words
    return "🌡", ""


class Weather:
    """Pronóstico de hoy de Open-Meteo (sin cuenta ni clave). Solo se envían las coordenadas configuradas."""

    def __init__(self, location: tuple[float, float], fetch: Fetch = fetch_url):
        self.location, self._fetch = location, fetch

    def line(self) -> str:
        """Cómo estará hoy, todos los días. Si llueve, hace mucho calor o mucho frío, eso va primero."""
        query = urllib.parse.urlencode(
            {
                "latitude": self.location[0], "longitude": self.location[1], "timezone": "auto", "forecast_days": 1,
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code",
            }
        )
        try:
            daily = json.loads(self._fetch(f"{WEATHER_API}?{query}").decode("utf-8"))["daily"]
            high, low = round(float(daily["temperature_2m_max"][0])), round(float(daily["temperature_2m_min"][0]))
            rain = int(daily["precipitation_probability_max"][0] or 0)
            raw_code = (daily.get("weather_code") or [None])[0]
            code = None if raw_code is None else int(raw_code)
        except (OSError, ValueError, KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"pronóstico no disponible: {exc}") from exc
        if rain >= RAIN_PERCENT:
            return f"🌧 Hoy es probable que llueva ({rain} %). Entre {low} y {high} °C."
        if high >= HOT_DEGREES:
            return f"🥵 Hoy hará calor: hasta {high} °C (mínima de {low} °C)."
        if low <= COLD_DEGREES:
            return f"🥶 Hoy hará frío: mínima de {low} °C (máxima de {high} °C)."
        mark, words = _sky(code)
        chance = f", {rain} % de lluvia" if rain else ""
        return f"{mark} Hoy{' ' + words if words else ''}: entre {low} y {high} °C{chance}."


# --- Calendario ---

CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar.readonly"
CALENDAR_API = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
CALENDAR_REFRESH_SECONDS = 300
CALENDAR_RETRY_SECONDS = 1800
NOTIFIED_KEY = "calendar_notified"
MAX_EVENTS = 12


def calendar_token_path(folder: Path, account: str) -> Path:
    """La llave del calendario va aparte de la del correo: cada permiso se da y se quita por separado."""
    return folder / ("google-calendar-token.json" if account == DEFAULT_ACCOUNT else f"google-calendar-token-{account}.json")


def find_calendars(folder: Path) -> list[tuple[str, Path]]:
    found = []
    for path in sorted(folder.glob("google-calendar-token*.json")):
        name = path.stem.removeprefix("google-calendar-token").lstrip("-") or DEFAULT_ACCOUNT
        if valid_account(name):
            found.append((name, path))
    return found


@dataclass(frozen=True)
class Event:
    id: str
    title: str
    start: datetime | None  # None: dura todo el día.
    account: str = DEFAULT_ACCOUNT

    def label(self) -> str:
        tag = "" if self.account == DEFAULT_ACCOUNT else f"[{self.account}] "
        return f"{tag}{self.start:%H:%M} {self.title}" if self.start else f"{tag}Todo el día: {self.title}"


class CalendarClient(GmailClient):
    """Lee los eventos del calendario principal. Reutiliza la renovación de llaves del cliente de correo."""

    def events(self, start: datetime, end: datetime, account: str = DEFAULT_ACCOUNT) -> list[Event]:
        query = urllib.parse.urlencode(
            {
                "timeMin": start.isoformat(), "timeMax": end.isoformat(), "singleEvents": "true",
                "orderBy": "startTime", "maxResults": MAX_EVENTS,
            }
        )
        request = urllib.request.Request(
            f"{CALENDAR_API}?{query}", headers={"Authorization": f"Bearer {self._access_token()}"}
        )
        events = []
        for item in self._json(request).get("items") or []:
            if not isinstance(item, dict) or item.get("status") == "cancelled":
                continue
            if any(a.get("self") and a.get("responseStatus") == "declined" for a in item.get("attendees") or []):
                continue
            raw = item.get("start") or {}
            try:
                moment = datetime.fromisoformat(raw["dateTime"]).astimezone(start.tzinfo) if "dateTime" in raw else None
            except (TypeError, ValueError):
                continue
            title = clean(item.get("summary"), 80) or "(sin título)"
            events.append(Event(str(item.get("id", ""))[:200], title, moment, account))
        return events


class Agenda:
    def __init__(
        self,
        clients: list[tuple[str, CalendarClient]],
        store: Store,
        remind_minutes: int,
        send: Callable[..., Any],
    ):
        self.clients, self.store, self.remind_minutes, self.send = clients, store, remind_minutes, send
        self._lock = threading.Lock()
        self._cached: list[Event] = []
        self._cached_day = ""
        self._cached_at = 0.0
        self._retry_at = 0.0

    def today(self, now: datetime) -> list[Event]:
        """Eventos de hoy de todas las cuentas. Se consulta a Google como mucho cada cinco minutos."""
        with self._lock:
            stamp, day = now.timestamp(), now.date().isoformat()
            if stamp < self._retry_at:
                return self._cached if self._cached_day == day else []
            if self._cached_day == day and stamp - self._cached_at < CALENDAR_REFRESH_SECONDS:
                return self._cached
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            events: list[Event] = []
            try:
                for name, client in self.clients:
                    events.extend(client.events(start, start + timedelta(days=1), name))
            except GmailAuthError as exc:
                log.warning("Calendario: hace falta volver a autorizar (%s)", exc)
                self._retry_at = stamp + CALENDAR_RETRY_SECONDS
                return []
            except GmailError as exc:
                log.warning("Calendario: no pude leer la agenda: %s", exc)
                self._retry_at = stamp + CALENDAR_REFRESH_SECONDS
                return self._cached if self._cached_day == day else []
            events.sort(key=lambda e: (e.start is not None, e.start.timestamp() if e.start else 0))
            self._cached, self._cached_day, self._cached_at = events, day, stamp
            return events

    def today_lines(self, now: datetime) -> list[str]:
        return [event.label() for event in self.today(now)]

    def tick(self, now: datetime) -> None:
        """Avisa de los eventos que empiezan dentro de `remind_minutes`. Cada evento se avisa una vez."""
        if self.remind_minutes <= 0:
            return
        day = now.date().isoformat()
        try:
            saved = json.loads(self.store.kv_get(NOTIFIED_KEY) or "{}")
        except ValueError:
            saved = {}
        notified = set(saved.get("ids", [])) if saved.get("day") == day else set()
        changed = False
        for event in self.today(now):
            if event.start is None or event.id in notified:
                continue
            minutes = (event.start - now).total_seconds() / 60
            if not 0 <= minutes <= self.remind_minutes:
                continue
            lead = "Ahora" if minutes < 1 else f"En {round(minutes)} min"
            try:
                self.send(f"📅 {lead}: {event.label()}", [])
            except Exception as exc:
                log.warning("Calendario: no pude avisar del evento: %s", exc)
                break
            notified.add(event.id)
            changed = True
        if changed:
            self.store.kv_set(NOTIFIED_KEY, json.dumps({"day": day, "ids": sorted(notified)}))


# --- Vigilante externo ---

HEARTBEAT_SECONDS = 300


def valid_heartbeat(url: str) -> bool:
    parts = urllib.parse.urlsplit(url)
    return parts.scheme == "https" and bool(parts.hostname)


def run_heartbeat(url: str, stop: threading.Event, interval: float = HEARTBEAT_SECONDS, fetch: Fetch = fetch_url) -> None:
    """Toca la dirección del vigilante cada cinco minutos. No envía ningún dato: solo la visita."""
    failing = False
    while not stop.is_set():
        try:
            fetch(url)
            if failing:
                log.info("Vigilante externo: de nuevo en contacto")
            failing = False
        except (OSError, ValueError) as exc:
            if not failing:
                log.warning("Vigilante externo: no pude avisar que sigo vivo (%s)", type(exc).__name__)
            failing = True
        stop.wait(interval)
