"""Página local con las tareas y lo que oye Hermes en vivo. Solo acepta conexiones de esta computadora."""
from __future__ import annotations

import base64
import json
import logging
import secrets
import threading
import time
from collections import deque
from dataclasses import asdict
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Sequence
from urllib.parse import parse_qs, urlsplit

from .remote import ApprovalUnavailable, RemoteAccess, login_page, wait_page

log = logging.getLogger(__name__)

ASSETS = Path(__file__).resolve().parent / "assets"
LOGO_PATH = ASSETS / "logo.webp"
MANIFEST = json.dumps(
    {
        "name": "Hermes",
        "short_name": "Hermes",
        "lang": "es",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#0a0c0f",
        "theme_color": "#0a0c0f",
        "icons": [
            {"src": "/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png"},
        ],
    }
).encode("utf-8")
# Lo que el teléfono pide para instalar la página como app. No dice nada privado: el nombre y el ícono.
PUBLIC_FILES = {"/icon-192.png": "image/png", "/icon-512.png": "image/png"}


def touch_icon() -> str:
    """Ícono de la pantalla de inicio del iPhone, dentro de la propia página.

    El iPhone lo descarga por su cuenta, sin la sesión de Cloudflare Access, que se lo bloquea; dentro
    de la página llega siempre. Si falta el archivo, se usa la dirección normal.
    """
    icon = ASSETS / "icon-192.png"
    if not icon.exists():
        return "/icon-192.png"
    return "data:image/png;base64," + base64.b64encode(icon.read_bytes()).decode("ascii")
MAX_EVENTS = 25
USAGE_REFRESH_SECONDS = 3.0



class VoiceStatus:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state = "inactiva"
        self._level = 0.0
        self._threshold = 0.0
        self._events: deque[dict[str, Any]] = deque(maxlen=MAX_EVENTS)
        self._version = 0
        self._usage_source: Callable[[], dict[str, Any]] | None = None
        self._usage: dict[str, Any] = {}
        self._usage_at = -USAGE_REFRESH_SECONDS
        self._sources: dict[str, Callable[[], dict[str, Any]]] = {}
        self._paused = False
        self._actions: dict[str, Callable[[Any], dict[str, Any]]] = {}
        self.on_pause: Callable[[bool], None] | None = None  # Para recordar la pausa entre reinicios.
        self.settings: Any = None  # Editor de ajustes; None si esta página no los ofrece.
        self.boot = secrets.token_hex(4)  # Cambia en cada arranque: la página lo usa para recargarse.

    @property
    def paused(self) -> bool:
        return self._paused

    def set_paused(self, paused: bool) -> None:
        """Desde la página: con la pausa, el micrófono se cierra hasta que lo vuelvas a activar."""
        with self._lock:
            self._paused = paused
            if paused and self._state == "escuchando":
                self._state = "pausada"
                self._level = 0.0
        log.info("Voz en casa %s desde la página", "en pausa" if paused else "reactivada")
        if self.on_pause is not None:
            try:
                self.on_pause(paused)
            except Exception:
                log.exception("No se pudo guardar la pausa del micrófono")

    def set_usage_source(self, source: Callable[[], dict[str, Any]]) -> None:
        self._usage_source = source

    def set_source(self, name: str, source: Callable[[], dict[str, Any]]) -> None:
        """Datos de una pestaña de la página: tareas, consumo o historial."""
        self._sources[name] = source

    def set_task_source(self, source: Callable[[], dict[str, Any]]) -> None:
        self.set_source("tasks", source)

    def read(self, name: str) -> dict[str, Any]:
        source = self._sources.get(name)
        if source is None:
            return {}
        try:
            return source()
        except Exception:
            log.exception("No se pudieron leer los datos de %s para la página", name)
            return {}

    receipt_photo: Callable[[int], bytes | None] | None = None  # Foto de un recibo, solo para quien ya entró.

    def set_action(self, name: str, action: Callable[[Any], dict[str, Any]]) -> None:
        """Cambios que la página puede pedir, por ejemplo editar tareas."""
        self._actions[name] = action

    def has_action(self, name: str) -> bool:
        return name in self._actions

    def act(self, name: str, payload: Any) -> tuple[int, dict[str, Any]]:
        try:
            return 200, self._actions[name](payload)
        except ValueError as exc:  # Datos inválidos: el mensaje es para el usuario.
            return 400, {"error": str(exc) or "Solicitud inválida."}
        except Exception:
            log.exception("Falló la acción %s pedida desde la página", name)
            return 500, {"error": "Ocurrió un error. Revisa el registro de Hermes."}

    def tasks(self) -> dict[str, Any]:
        return self.read("tasks")

    def _current_usage(self) -> dict[str, Any]:
        # La página pregunta cinco veces por segundo; la base de datos no necesita tanto.
        if self._usage_source is not None and time.monotonic() - self._usage_at >= USAGE_REFRESH_SECONDS:
            self._usage_at = time.monotonic()
            try:
                self._usage = self._usage_source()
            except Exception:
                log.exception("No se pudo leer el consumo de tokens")
        return self._usage

    def set_state(self, state: str) -> None:
        with self._lock:
            self._state = state

    def set_level(self, level: float, threshold: float) -> None:
        with self._lock:
            self._level = level
            self._threshold = threshold

    def add_event(self, outcome: str, heard: str, reply: str, timings: dict[str, float], peak: float, threshold: float) -> None:
        with self._lock:
            self._version += 1
            self._events.appendleft(
                {
                    "at": time.strftime("%H:%M:%S"),
                    "outcome": outcome,
                    "heard": heard,
                    "reply": reply,
                    "timings": {name: round(seconds, 1) for name, seconds in timings.items()},
                    "peak": round(peak),
                    "threshold": round(threshold),
                }
            )

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "state": self._state,
                "paused": self._paused,
                "speak": "speak" in self._actions,
                "boot": self.boot,
                "level": round(self._level),
                "threshold": round(self._threshold),
                "version": self._version,
                "events": list(self._events),
                "tokens": self._current_usage(),
            }


USAGE_DAYS = 14
HISTORY_MESSAGES = 300


def usage_report(store: Any, now: datetime) -> dict[str, Any]:
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = int(day_start.replace(day=1).timestamp())
    first_day = day_start - timedelta(days=USAGE_DAYS - 1)
    summary = store.usage_summary(int(day_start.timestamp()), month_start, recent=20)
    return {
        **summary,
        "days": [(first_day + timedelta(days=i)).date().isoformat() for i in range(USAGE_DAYS)],
        "daily": store.usage_daily(int(first_day.timestamp())),
        "by_purpose": store.usage_by_purpose(month_start),
    }


def history_report(store: Any, status: VoiceStatus) -> dict[str, Any]:
    return {"messages": store.message_history(HISTORY_MESSAGES), "voice": status.snapshot()["events"]}


def tasks_snapshot(store: Any, categories: Sequence[str], now: int, colors: dict[str, str] | None = None) -> dict[str, Any]:
    """Datos de la pestaña Tareas: pendientes, pasos ya hechos de tareas abiertas y lo completado reciente."""
    pending = [asdict(task) for task in store.pending_tasks()]
    done_steps = [
        asdict(step)
        for task in pending
        if task["parent_id"] is None
        for step in store.subtasks(task["id"])
        if step.status == "done"
    ]
    return {
        "now": now,
        "categories": list(categories),
        "colors": dict(colors or {}),
        "pending": pending,
        "done_steps": done_steps,
        "finished": [asdict(task) for task in store.finished_tasks()],
    }


PAGE = """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#0a0c0f">
<meta name="robots" content="noindex">
<title>Hermes</title>
<meta name="hermes-token" content="__CSRF_TOKEN__">
<link rel="manifest" href="/manifest.webmanifest" crossorigin="use-credentials">
<link rel="icon" type="image/png" href="/icon-192.png">
<link rel="apple-touch-icon" href="__TOUCH_ICON__">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black">
<meta name="apple-mobile-web-app-title" content="Hermes">
<style>
:root {
  --bg:#f4f3ef; --card:#ffffff; --ink:#1d1d1b; --muted:#6b6962; --faint:#9a978e; --line:#e4e1d8; --soft:#eeece6;
  --accent:#2f6f5e; --accent-soft:#e3efe9; --warn:#b4532a; --bar:#dcd8cc;
  --u-alta:#c2412d; --u-media:#c58a12; --u-baja:#3f8f5a;
  --c-trabajo:#3567b5; --c-negocios:#7a4fb3; --c-casa:#b36b2a; --c-personal:#2f8a87;
  --c-salud:#c0436b; --c-finanzas:#4b7d2f; --c-reptiles:#6d7a1f; --c-otra:#7b7870;
  --shadow:0 1px 2px rgba(30,30,25,.05), 0 4px 16px rgba(30,30,25,.04);
  --s-claude:#2a78d6; --s-local:#eb6834;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg:#141517; --card:#1e2023; --ink:#ecebe6; --muted:#a3a198; --faint:#7c7a73; --line:#2f3236; --soft:#26292d;
    --accent:#62b8a0; --accent-soft:#1f3a33; --warn:#e58a63; --bar:#363a40;
    --u-alta:#ef7a63; --u-media:#e2b44a; --u-baja:#6cc08a;
    --c-trabajo:#7aa5ec; --c-negocios:#b496e8; --c-casa:#e3a46a; --c-personal:#5fc4c0;
    --c-salud:#ec86a7; --c-finanzas:#93c56f; --c-reptiles:#b8c55a; --c-otra:#a3a198;
    --shadow:none;
    --s-claude:#3987e5; --s-local:#d95926;
  }
}
* { box-sizing:border-box; }
/* Safari del iPhone da a los campos de hora y fecha un ancho propio que ignora width:100% y se sale de la tarjeta. */
input[type="time"], input[type="date"], input[type="datetime-local"] { -webkit-appearance:none; appearance:none; min-width:0; max-width:100%; min-height:42px; }
input::-webkit-date-and-time-value { text-align:left; }
body { margin:0; background:var(--bg); color:var(--ink); font:15px/1.5 "Segoe UI Variable Text","Segoe UI",system-ui,sans-serif; }
header { position:sticky; top:0; z-index:5; background:color-mix(in srgb, var(--bg) 88%, transparent); backdrop-filter:blur(8px); border-bottom:1px solid var(--line); }
header { padding-top:env(safe-area-inset-top); }
.bar { max-width:1040px; margin:0 auto; padding:12px 16px; display:flex; align-items:center; gap:16px; flex-wrap:wrap; }
.brand { font-weight:650; font-size:17px; letter-spacing:.2px; margin-right:auto; display:flex; align-items:center; gap:8px; }
.brand-dot { width:10px; height:10px; border-radius:50%; background:var(--accent); }
.tabs { display:flex; background:var(--soft); border-radius:10px; padding:3px; max-width:100%; overflow-x:auto; scrollbar-width:none; }
.tabs a { white-space:nowrap; }
.tabs a { color:var(--muted); text-decoration:none; padding:6px 14px; border-radius:8px; font-weight:550; font-size:14px; }
.tabs a[aria-current="page"] { background:var(--card); color:var(--ink); box-shadow:var(--shadow); }
.pill { font-size:13px; color:var(--muted); display:flex; align-items:center; gap:6px; }
.pill i { width:8px; height:8px; border-radius:50%; background:var(--faint); display:inline-block; }
.pill.on i { background:var(--accent); }
main { max-width:1040px; margin:0 auto; padding:20px 16px 56px; }
.view[hidden] { display:none; }
h2 { font-size:22px; margin:4px 0 2px; font-weight:650; }
.subtitle { color:var(--muted); font-size:13px; margin-bottom:18px; }
section, .card { background:var(--card); border:1px solid var(--line); border-radius:14px; box-shadow:var(--shadow); }
section { padding:18px; margin-bottom:14px; }
.label { color:var(--muted); font-size:13px; margin-bottom:6px; }
.empty { color:var(--muted); }
#offline { display:none; color:var(--warn); margin-bottom:12px; }

/* Tareas */
.stats { display:grid; grid-template-columns:repeat(4, 1fr); gap:12px; margin-bottom:18px; }
.stat { background:var(--card); border:1px solid var(--line); border-radius:14px; padding:14px 16px; box-shadow:var(--shadow); }
.stat b { display:block; font-size:28px; font-weight:650; line-height:1.15; font-variant-numeric:tabular-nums; }
.stat span { color:var(--muted); font-size:13px; }
.stat.alert b { color:var(--u-alta); }
#stats { grid-template-columns:repeat(5, 1fr); }
button.stat { font:inherit; color:inherit; text-align:left; cursor:pointer; width:100%; }
button.stat:hover { border-color:var(--faint); }
button.stat:focus-visible { outline:2px solid var(--accent); outline-offset:2px; }
button.stat[aria-pressed="true"] { border-color:var(--accent); box-shadow:0 0 0 1px var(--accent); }
.tag.ok { background:color-mix(in srgb, var(--u-baja) 16%, transparent); color:var(--u-baja); font-weight:600; }
.fin-actions { display:flex; gap:18px; margin-top:8px; }
.fin-actions .undo { padding:4px 0; font-size:13px; }
.undo.danger-link { color:var(--warn); }
.fin-mark { color:var(--muted); width:18px; flex:none; }
.steps li .meta { margin:0 0 0 auto; font-size:12px; }
@media (max-width:640px) { #stats { grid-template-columns:repeat(2, 1fr); } #stats .stat:last-child { grid-column:1 / -1; } }
.filters { display:flex; flex-wrap:wrap; gap:8px; margin-bottom:16px; }
.filters button { font:inherit; font-size:13px; border:1px solid var(--line); background:var(--card); color:var(--ink); border-radius:999px; padding:5px 12px; cursor:pointer; display:flex; align-items:center; gap:7px; }
.filters button[aria-pressed="true"] { background:var(--ink); color:var(--bg); border-color:var(--ink); }
.filters button em { font-style:normal; color:var(--faint); font-variant-numeric:tabular-nums; }
.filters button[aria-pressed="true"] em { color:inherit; opacity:.7; }
.dot { width:9px; height:9px; border-radius:50%; flex:none; background:var(--cat, var(--c-otra)); }
.groups { display:grid; grid-template-columns:repeat(auto-fill, minmax(min(100%, 460px), 1fr)); gap:14px; align-items:start; }
.group { overflow:hidden; }
.group-head { display:flex; align-items:center; gap:9px; padding:12px 16px; border-bottom:1px solid var(--line); font-weight:600; }
.group-head .name { text-transform:capitalize; }
button.group-head { width:100%; font:inherit; font-weight:600; color:inherit; background:none; border:0; border-bottom:1px solid var(--line); text-align:left; cursor:pointer; }
button.group-head:focus-visible { outline:2px solid var(--accent); outline-offset:-2px; }
.group-head .chev { width:8px; height:8px; border:solid var(--muted); border-width:0 2px 2px 0; transform:rotate(45deg); margin:0 4px 3px 4px; transition:transform .15s; flex:none; }
.group.closed .group-head { border-bottom:0; }
.group.closed .chev { transform:rotate(-45deg); margin-bottom:0; }
.group-head em { margin-left:auto; font-style:normal; font-weight:500; color:var(--muted); font-size:13px; }
.task { display:flex; gap:12px; padding:12px 16px; border-top:1px solid var(--line); }
.task:first-of-type { border-top:0; }
.urg { width:4px; border-radius:4px; flex:none; background:var(--u-media); }
.urg.alta { background:var(--u-alta); } .urg.baja { background:var(--u-baja); }
.task-main { flex:1; min-width:0; }
.task-title { font-weight:550; overflow-wrap:anywhere; }
.meta { display:flex; flex-wrap:wrap; gap:6px 10px; margin-top:4px; color:var(--muted); font-size:13px; align-items:center; }
.tag { border-radius:6px; padding:1px 7px; background:var(--soft); color:var(--muted); font-size:12px; }
.tag.alta { background:color-mix(in srgb, var(--u-alta) 14%, transparent); color:var(--u-alta); font-weight:600; }
.due.overdue { color:var(--u-alta); font-weight:600; }
.due.today { color:var(--accent); font-weight:600; }
.progress { display:flex; align-items:center; gap:10px; margin-top:10px; font-size:12px; color:var(--muted); }
.track { flex:1; height:6px; background:var(--soft); border-radius:6px; overflow:hidden; }
.track div { height:100%; background:var(--accent); border-radius:6px; }
.steps { list-style:none; margin:8px 0 0; padding:0; }
.steps li { display:flex; align-items:baseline; gap:8px; padding:3px 0; font-size:14px; }
.check { width:14px; height:14px; border:1.5px solid var(--faint); border-radius:50%; flex:none; position:relative; top:2px; }
.steps li.done { color:var(--faint); text-decoration:line-through; }
.steps li.done .check { background:var(--accent); border-color:var(--accent); }
.steps .meta { margin:0 0 0 auto; }
details.finished { margin-top:18px; }
details.finished summary { cursor:pointer; color:var(--muted); font-size:14px; padding:6px 0; }
.finished-list { padding:4px 16px; }
.finished-list div { display:flex; gap:10px; padding:8px 0; border-top:1px solid var(--line); font-size:14px; }
.finished-list div:first-child { border-top:0; }
.finished-list span:first-child { color:var(--muted); width:22px; }
.finished-list span.when { margin-left:auto; color:var(--faint); font-size:13px; white-space:nowrap; }
/* Edición */
.tick { width:20px; height:20px; border-radius:50%; border:1.5px solid var(--faint); background:transparent; flex:none; cursor:pointer; padding:0; display:grid; place-items:center; color:transparent; font-size:12px; line-height:1; margin-top:1px; }
.tick:hover { border-color:var(--accent); color:var(--accent); }
.tick[aria-pressed="true"] { background:var(--accent); border-color:var(--accent); color:#14110a; }
.tick:focus-visible, .linkish:focus-visible, .icon-btn:focus-visible { outline:2px solid var(--accent); outline-offset:2px; }
.steps .tick { width:16px; height:16px; font-size:10px; position:relative; top:2px; }
.task-main.clickable { cursor:pointer; }
.task-main.clickable:hover .task-title { color:var(--accent); }
.linkish { font:inherit; color:inherit; background:none; border:0; padding:0; text-align:left; cursor:pointer; overflow-wrap:anywhere; }
.linkish:disabled { cursor:default; }
.task-title.linkish { font-weight:550; }
.undo { font:inherit; font-size:12px; color:var(--accent); background:none; border:0; cursor:pointer; padding:0 0 0 8px; white-space:nowrap; }
dialog#editor { background:var(--card); color:var(--ink); border:1px solid var(--line); border-radius:16px; padding:0; width:min(560px, calc(100vw - 24px)); max-height:calc(100vh - 24px); overflow:auto; box-shadow:0 24px 60px rgba(0,0,0,.5); }
dialog#editor::backdrop { background:rgba(0,0,0,.62); backdrop-filter:blur(2px); }
#ed-form { padding:18px 20px 20px; display:flex; flex-direction:column; gap:14px; }
.ed-head { display:flex; align-items:flex-start; gap:12px; }
.ed-head h3 { margin:0; font-size:18px; font-weight:650; }
.ed-head .linkish { color:var(--muted); font-size:13px; }
.ed-head .linkish:not(:disabled):hover { color:var(--accent); }
.icon-btn { margin-left:auto; font:inherit; background:none; border:0; color:var(--muted); cursor:pointer; border-radius:8px; padding:2px 8px; font-size:15px; }
.icon-btn:hover { color:var(--ink); background:var(--soft); }
.field { display:flex; flex-direction:column; gap:5px; border:0; padding:0; margin:0; min-width:0; }
.field > span, .field legend, .field-label { color:var(--muted); font-size:13px; padding:0; }
.field input, .field select, .add-step input { font:inherit; color:var(--ink); background:var(--bg); border:1px solid var(--line); border-radius:10px; padding:8px 11px; width:100%; min-width:0; }
.field input:focus, .field select:focus, .add-step input:focus { outline:none; border-color:var(--accent); }
.row2 { display:grid; grid-template-columns:1fr 1fr; gap:12px; }
.seg-ctl { display:grid; grid-template-columns:repeat(3, 1fr); background:var(--bg); border:1px solid var(--line); border-radius:10px; padding:3px; gap:3px; }
.seg-ctl label { position:relative; }
.seg-ctl input { position:absolute; opacity:0; inset:0; margin:0; cursor:pointer; }
.seg-ctl span { display:flex; align-items:center; justify-content:center; gap:6px; padding:6px 4px; border-radius:7px; font-size:14px; color:var(--muted); }
.seg-ctl span::before { content:""; width:8px; height:8px; border-radius:50%; background:var(--u, var(--u-media)); }
.seg-ctl input:checked + span { background:var(--soft); color:var(--ink); font-weight:600; }
.seg-ctl input:focus-visible + span { outline:2px solid var(--accent); }
.date-row { display:flex; gap:8px; }
.date-row input { flex:1; color-scheme:dark; }
.ghost { font:inherit; font-size:14px; color:var(--ink); background:transparent; border:1px solid var(--line); border-radius:10px; padding:8px 13px; cursor:pointer; white-space:nowrap; }
.ghost:hover { border-color:var(--faint); }
.primary { margin-left:auto; font:inherit; font-size:14px; font-weight:600; color:#14110a; background:var(--accent); border:1px solid var(--accent); border-radius:10px; padding:8px 18px; cursor:pointer; }
.danger { font:inherit; font-size:14px; color:var(--u-alta); background:transparent; border:1px solid transparent; border-radius:10px; padding:8px 10px; cursor:pointer; margin-right:auto; }
.danger:hover { border-color:color-mix(in srgb, var(--u-alta) 40%, transparent); }
#ed-form button:disabled { opacity:.5; cursor:default; }
.ed-steps { list-style:none; margin:4px 0 8px; padding:0; border:1px solid var(--line); border-radius:10px; }
.ed-steps li { display:flex; align-items:center; gap:10px; padding:7px 10px; border-top:1px solid var(--line); font-size:14px; }
.ed-steps li:first-child { border-top:0; }
.ed-steps li.done .linkish { color:var(--faint); text-decoration:line-through; }
.ed-steps .linkish { flex:1; min-width:0; }
.ed-steps .linkish:not(:disabled):hover { color:var(--accent); }
.ed-steps .icon-btn { margin-left:0; font-size:13px; }
.ed-steps li.empty { color:var(--muted); }
.add-step { display:flex; gap:8px; }
.ed-error { color:var(--u-alta); font-size:13px; }
.ed-error:empty { display:none; }
.ed-actions { display:flex; gap:8px; align-items:center; flex-wrap:wrap; padding-top:4px; }
.toast { position:fixed; left:50%; bottom:22px; transform:translate(-50%, 20px); opacity:0; pointer-events:none; background:var(--card); color:var(--ink); border:1px solid var(--line); box-shadow:0 10px 30px rgba(0,0,0,.45); border-radius:12px; padding:10px 14px; display:flex; align-items:center; gap:12px; font-size:14px; max-width:calc(100vw - 32px); z-index:20; transition:opacity .2s, transform .2s; white-space:pre-line; }
.toast.show { opacity:1; transform:translate(-50%, 0); pointer-events:auto; }
.toast button { font:inherit; font-weight:600; color:var(--accent); background:none; border:0; cursor:pointer; padding:0; white-space:nowrap; }
.toast button[hidden] { display:none; }
@media (max-width:480px) { .row2 { grid-template-columns:1fr; } }
.empty-state { text-align:center; padding:48px 16px; color:var(--muted); }
.empty-state b { display:block; color:var(--ink); font-size:17px; margin-bottom:4px; }

/* En vivo */
.live { max-width:760px; }
#state { font-size:30px; font-weight:650; color:var(--accent); }
#hint { color:var(--muted); margin-top:4px; min-height:1.45em; }
.meter { position:relative; height:22px; background:var(--bar); border-radius:6px; overflow:hidden; }
#fill { position:absolute; inset:0 auto 0 0; width:0; background:var(--accent); transition:width .12s linear; }
#fill.voice { background:var(--warn); }
#mark { position:absolute; top:0; bottom:0; width:2px; background:var(--ink); }
.nums { display:flex; justify-content:space-between; color:var(--muted); font-size:13px; margin-top:6px; font-variant-numeric:tabular-nums; }
.event { padding:12px 0; border-top:1px solid var(--line); }
.event:first-of-type { border-top:0; padding-top:0; }
.top { display:flex; justify-content:space-between; gap:12px; color:var(--muted); font-size:13px; }
.outcome { font-weight:600; color:var(--accent); }
.outcome.bad { color:var(--warn); }
.line { margin-top:4px; overflow-wrap:anywhere; }
.line b { font-weight:600; }
.times { display:flex; flex-wrap:wrap; gap:6px; margin-top:8px; }
.chip { background:var(--bg); border:1px solid var(--line); border-radius:999px; padding:1px 9px; font-size:13px; font-variant-numeric:tabular-nums; }
.chip.total { font-weight:600; }
table { width:100%; border-collapse:collapse; font-size:14px; font-variant-numeric:tabular-nums; }
th, td { text-align:right; padding:6px 0 6px 10px; border-top:1px solid var(--line); white-space:nowrap; }
th { color:var(--muted); font-weight:500; border-top:0; }
th:first-child, td:first-child { text-align:left; padding-left:0; white-space:normal; }
.wide { overflow-x:auto; }
.note { color:var(--muted); font-size:13px; margin-top:10px; }
.sub { color:var(--muted); font-size:13px; margin:16px 0 4px; }
/* Consumo */
.stat small { display:block; color:var(--faint); font-size:12px; margin-top:2px; }
.legend { display:flex; gap:18px; font-size:13px; color:var(--muted); margin-bottom:12px; }
.legend i { width:10px; height:10px; border-radius:3px; display:inline-block; margin-right:6px; vertical-align:-1px; }
.chart { position:relative; height:200px; display:flex; align-items:flex-end; gap:6px; margin-left:44px; border-bottom:1px solid var(--line); }
.gridline { position:absolute; left:0; right:0; border-top:1px dashed var(--line); }
.gridline span { position:absolute; left:-46px; top:-8px; width:40px; text-align:right; font-size:11px; color:var(--faint); font-variant-numeric:tabular-nums; }
.col { flex:1; height:100%; display:flex; align-items:flex-end; justify-content:center; outline:none; position:relative; z-index:1; }
.col:hover, .col:focus-visible { background:color-mix(in srgb, var(--ink) 5%, transparent); border-radius:6px 6px 0 0; }
.stack { width:min(24px, 70%); display:flex; flex-direction:column; gap:2px; }
.seg.claude { background:var(--s-claude); } .seg.local { background:var(--s-local); }
.stack .seg:first-child { border-radius:4px 4px 0 0; }
.xlabels { display:flex; gap:6px; margin:6px 0 0 44px; }
.xlabels span { flex:1; min-width:0; text-align:center; font-size:11px; color:var(--faint); white-space:nowrap; overflow:hidden; }
.col { min-width:0; }
.tooltip { position:absolute; pointer-events:none; background:var(--card); border:1px solid var(--line); box-shadow:0 6px 20px rgba(0,0,0,.14); border-radius:10px; padding:8px 11px; font-size:12px; white-space:nowrap; z-index:4; display:none; }
.tooltip b { display:block; margin-bottom:3px; }
.tooltip div { display:flex; align-items:center; gap:6px; color:var(--muted); }
.tooltip i { width:8px; height:8px; border-radius:2px; display:inline-block; }
.chart-box { position:relative; }
details.table-view summary { cursor:pointer; color:var(--muted); font-size:13px; margin-top:12px; }
.grid2 { display:grid; grid-template-columns:repeat(auto-fit, minmax(min(100%, 420px), 1fr)); gap:14px; }
.grid2 > *, .groups > *, .stats > * { min-width:0; }

/* En vivo: escenario oscuro con el logo */
/* Tema negro con acento dorado, en todas las pestañas */
body.stage {
  color-scheme:dark;
  --bg:#0a0c0f; --card:#14171b; --ink:#eeece6; --muted:#a19f96; --faint:#77756e; --line:#262a30; --soft:#1c2025;
  --accent:#f2c230; --accent-soft:#2a2410; --warn:#e58a63; --bar:#262a30; --shadow:none;
  --u-alta:#ef7a63; --u-media:#e2b44a; --u-baja:#6cc08a;
  --c-trabajo:#7aa5ec; --c-negocios:#b496e8; --c-casa:#e3a46a; --c-personal:#5fc4c0;
  --c-salud:#ec86a7; --c-finanzas:#93c56f; --c-reptiles:#b8c55a; --c-otra:#a3a198;
  --s-claude:#3987e5; --s-local:#d95926;
  background:radial-gradient(circle at 50% 42%, #161a20 0%, #0a0c0f 62%) fixed, #0a0c0f;
}
body.stage .filters button[aria-pressed="true"] { background:var(--accent); color:#14110a; border-color:var(--accent); }
body.stage .stat, body.stage .card, body.stage section { border-color:var(--line); }
body.stage header { background:color-mix(in srgb, #0a0c0f 85%, transparent); }
.stage-wrap { min-height:calc(100vh - 150px); display:flex; flex-direction:column; align-items:center; justify-content:center; text-align:center; gap:18px; }
.orb { --level:0; --glow:.3; --speed:4s; --gold:242,194,48; position:relative; width:min(78vw, 380px); aspect-ratio:1; display:grid; place-items:center; }
.ring { position:absolute; inset:0; border-radius:50%; border:1.5px solid rgba(var(--gold), calc(var(--glow) * .55));
  transform:scale(calc(.6 + var(--i) * .13 + var(--level) * var(--i) * .05));
  box-shadow:0 0 calc(6px + var(--level) * 36px) rgba(var(--gold), calc(var(--glow) * .45)), inset 0 0 calc(4px + var(--level) * 20px) rgba(var(--gold), calc(var(--glow) * .25));
  transition:transform .15s ease-out, border-color .4s, box-shadow .15s ease-out; }
.ripple { position:absolute; inset:0; border-radius:50%; border:2px solid rgba(var(--gold), .7); opacity:0; animation:ripple var(--speed) cubic-bezier(.2,.6,.3,1) infinite; }
.ripple.r2 { animation-delay:calc(var(--speed) / -3); } .ripple.r3 { animation-delay:calc(var(--speed) / -1.5); }
@keyframes ripple { 0% { transform:scale(.5); opacity:calc(var(--glow) * .9); } 100% { transform:scale(1.18); opacity:0; } }
.disc { position:relative; z-index:2; width:44%; aspect-ratio:1; border-radius:50%; background:#fdfdfd; display:grid; place-items:center; overflow:hidden;
  box-shadow:0 0 0 calc(4px + var(--level) * 6px) rgba(var(--gold), calc(.25 + var(--glow) * .5)), 0 0 calc(24px + var(--level) * 90px) rgba(var(--gold), calc(var(--glow) * .7));
  transition:box-shadow .15s ease-out; }
.disc img { width:78%; height:78%; object-fit:contain; transform:translate(-2%, 2%); user-select:none; }
.orb[data-state="inactiva"] { --glow:.06; } .orb[data-state="inactiva"] .ripple { animation:none; }
.orb[data-state="escuchando"] { --glow:.32; --speed:4.2s; }
.orb[data-state="pausada"] { --glow:.04; } .orb[data-state="pausada"] .ripple { animation:none; }
.orb[data-state="pausada"] .disc { filter:grayscale(1) brightness(.55); transition:filter .4s; }
.orb[data-state="pitido"], .orb[data-state="grabando"] { --glow:1; --speed:1.5s; }
.orb[data-state="transcribiendo"], .orb[data-state="pensando"] { --glow:.7; --speed:2.4s; }
.orb[data-state="pensando"] .disc { animation:breathe 1.6s ease-in-out infinite; }
.orb[data-state="hablando"] { --glow:.85; --speed:1.9s; }
@keyframes breathe { 50% { transform:scale(1.035); } }
.stage-wrap #state { color:rgb(242,194,48); font-size:28px; }
.stage-wrap #hint { margin-top:-12px; }
.stage-meter { width:min(78vw, 360px); }
.mic-btn { font:inherit; font-weight:600; font-size:15px; display:inline-flex; align-items:center; gap:9px; padding:10px 22px; border-radius:999px;
  border:1.5px solid var(--accent); background:transparent; color:var(--accent); cursor:pointer; transition:background .2s, color .2s; }
.mic-btn:hover { background:color-mix(in srgb, var(--accent) 12%, transparent); }
.mic-btn:focus-visible { outline:2px solid var(--accent); outline-offset:3px; }
.mic-btn[aria-pressed="true"] { background:var(--accent); color:#14110a; }
.mic-btn:disabled { opacity:.5; cursor:default; }
.mic-btn svg { width:18px; height:18px; flex:none; }
.stage-meter .meter { height:6px; border-radius:6px; }
.stage-meter .nums { font-size:12px; }
@media (prefers-reduced-motion: reduce) {
  .ripple, .orb[data-state="pensando"] .disc { animation:none; }
  .ring, .disc { transition:none; }
}

/* Historial */
.search { width:100%; font:inherit; padding:9px 12px; border-radius:10px; border:1px solid var(--line); background:var(--card); color:var(--ink); margin-bottom:6px; }
.thread { max-width:760px; }
.day { text-align:center; color:var(--faint); font-size:12px; margin:18px 0 8px; }
.day::first-letter { text-transform:uppercase; }
.msg { width:fit-content; max-width:min(620px, 88%); padding:8px 12px; border-radius:14px; margin:5px 0; white-space:pre-wrap; overflow-wrap:anywhere; font-size:14px; }
.msg.user { margin-left:auto; background:var(--accent-soft); border-bottom-right-radius:4px; }
.msg.hermes { background:var(--card); border:1px solid var(--line); border-bottom-left-radius:4px; }
.msg small { display:block; color:var(--faint); font-size:11px; margin-top:3px; }

/* Teléfono y pantallas táctiles */
html { -webkit-text-size-adjust:100%; }
a, button, input, select, summary { -webkit-tap-highlight-color:transparent; touch-action:manipulation; }
.bar, main { padding-left:max(16px, env(safe-area-inset-left)); padding-right:max(16px, env(safe-area-inset-right)); }
main { padding-bottom:calc(56px + env(safe-area-inset-bottom)); }
.toast { bottom:calc(22px + env(safe-area-inset-bottom)); }
@supports (height:100dvh) {
  dialog#editor { max-height:calc(100dvh - 24px); }
  .stage-wrap { min-height:calc(100dvh - 150px); }
}
/* Calendario mensual (Tareas y Fechas) */
.mode { display:inline-flex; background:var(--soft); border-radius:10px; padding:3px; margin:0 0 12px; }
.mode button { font:inherit; font-size:14px; font-weight:550; color:var(--muted); background:none; border:0; border-radius:8px; padding:6px 14px; cursor:pointer; }
.mode button[aria-pressed="true"] { background:var(--card); color:var(--ink); box-shadow:var(--shadow); }
.mode button:focus-visible { outline:2px solid var(--accent); outline-offset:1px; }
.cal { background:var(--card); border:1px solid var(--line); border-radius:14px; padding:12px; margin-bottom:14px; }
.cal-head { display:flex; align-items:center; gap:8px; margin-bottom:8px; }
.cal-head b { flex:1; text-transform:capitalize; font-size:16px; text-align:center; }
.cal-nav { font:inherit; font-size:14px; color:inherit; background:var(--soft); border:1px solid var(--line); border-radius:8px; min-width:38px; height:36px; cursor:pointer; padding:0 10px; }
.cal-nav:hover { border-color:var(--faint); }
.cal-grid { display:grid; grid-template-columns:repeat(7, minmax(0, 1fr)); gap:4px; }
.cal-wd { text-align:center; font-size:12px; color:var(--muted); padding:4px 0; }
.cal-day { font:inherit; color:inherit; background:none; border:1px solid transparent; border-radius:10px; min-height:70px; padding:4px; cursor:pointer;
  display:flex; flex-direction:column; align-items:stretch; gap:2px; text-align:left; overflow:hidden; }
.cal-day:hover { background:var(--soft); }
.cal-day:focus-visible { outline:2px solid var(--accent); outline-offset:-2px; }
.cal-day .n { font-size:13px; font-weight:600; width:24px; height:24px; display:grid; place-items:center; border-radius:50%; flex:none; }
.cal-day.today .n { background:var(--accent); color:#14110a; }
.cal-day.picked { border-color:var(--accent); background:var(--accent-soft); }
.cal-day .m { font-size:11px; line-height:1.3; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; border-radius:4px; padding:0 4px; background:var(--soft); color:var(--muted); }
.cal-day.picked .m { background:var(--card); }
.cal-day .m.alta { background:color-mix(in srgb, var(--u-alta) 18%, transparent); color:var(--u-alta); }
.cal-day .m.late { color:var(--u-alta); }
.cal-day .more { font-size:10px; color:var(--faint); padding-left:4px; }
.cal-day .dots { display:none; gap:3px; justify-content:center; }
.cal-day .dots i { width:5px; height:5px; border-radius:50%; background:var(--accent); }
.cal-day .dots i.alta, .cal-day .dots i.late { background:var(--u-alta); }
.cal-none { padding:14px 16px; color:var(--faint); font-size:14px; }
.cal-picked { margin:-4px 0 12px; font-size:14px; color:var(--muted); }
.cal-picked b { color:var(--ink); }
@media (max-width:640px) {
  .cal { padding:8px; }
  .cal-day { min-height:46px; align-items:center; padding:3px 0; }
  .cal-day .m, .cal-day .more { display:none; }
  .cal-day .dots { display:flex; }
}

/* Apuntes: listas, notas, hábitos, fechas y esperas */
.tabs { overflow-x:auto; scrollbar-width:none; }
.tabs::-webkit-scrollbar { display:none; }
.tabs a { white-space:nowrap; flex:none; }
.subtabs { display:flex; flex-wrap:wrap; gap:8px; margin:0 0 16px; }
.subtabs a { display:inline-flex; align-items:center; gap:6px; padding:7px 14px; border:1px solid var(--line); border-radius:999px;
  color:var(--muted); text-decoration:none; font-size:14px; font-weight:600; white-space:nowrap; }
.subtabs a:hover { color:var(--ink); }
.subtabs a:focus-visible { outline:2px solid var(--accent); outline-offset:2px; }
.subtabs a[aria-current="page"] { background:var(--accent); border-color:var(--accent); color:#14110a; }
.subtabs a span { font-weight:400; font-size:12px; opacity:.8; }
.subtabs a span:empty { display:none; }
.ap-card { background:var(--card); border:1px solid var(--line); border-radius:14px; padding:14px 16px; min-width:0; max-width:760px; }
.ap-card[hidden] { display:none; }
.ap-create { max-width:760px; margin-bottom:16px; }
.ap-create input { background:var(--card); padding:11px 13px; }
.ap-drawers { display:grid; grid-template-columns:repeat(auto-fill, minmax(min(100%, 320px), 1fr)); gap:14px; align-items:start; }
.ap-drawer { background:var(--card); border:1px solid var(--line); border-radius:14px; min-width:0; overflow:hidden; }
.ap-drawer-head { display:flex; align-items:center; gap:10px; width:100%; font:inherit; font-weight:650; font-size:16px; color:inherit; background:none; border:0; padding:14px 16px; cursor:pointer; text-align:left; }
.ap-drawer-head .name { text-transform:capitalize; flex:1; min-width:0; overflow-wrap:anywhere; }
.ap-drawer-head em { font-style:normal; font-weight:500; font-size:13px; color:var(--muted); white-space:nowrap; }
.ap-drawer-head .chev { width:8px; height:8px; border:solid var(--muted); border-width:0 2px 2px 0; transform:rotate(45deg); margin:0 4px 3px; transition:transform .15s; flex:none; }
.ap-drawer.closed .chev { transform:rotate(-45deg); margin-bottom:0; }
.ap-drawer-head:focus-visible { outline:2px solid var(--accent); outline-offset:-2px; }
.ap-drawer-body { padding:0 16px 12px; border-top:1px solid var(--line); }
.ap-drawer-body .ap-row:first-child { border-top:0; }
.ap-add { margin:10px 0 4px; }
dialog#ask { border:1px solid var(--line); border-radius:16px; background:var(--card); color:var(--ink); padding:20px; width:min(400px, calc(100vw - 32px)); box-shadow:0 20px 60px rgba(0,0,0,.5); }
dialog#ask::backdrop { background:rgba(0,0,0,.55); }
dialog#ask p { margin:0 0 18px; font-size:16px; line-height:1.45; overflow-wrap:anywhere; }
.ask-actions { display:flex; justify-content:flex-end; gap:10px; }
.ask-actions button { margin-left:0; }
.ap-row.done .ap-item { text-decoration:line-through; color:var(--faint); }
.ap-item { font:inherit; color:inherit; background:none; border:0; padding:2px 0; text-align:left; cursor:text; border-radius:6px; }
.ap-item:hover { color:var(--accent); }
.ap-item:focus-visible { outline:2px solid var(--accent); outline-offset:2px; }
.ap-editing { gap:8px; }
.ap-editing input { flex:1; min-width:0; font:inherit; font-size:16px; color:inherit; background:var(--bg); border:1px solid var(--accent); border-radius:10px; padding:7px 10px; }
.ap-editing input:focus { outline:none; }
.ap-editing .primary { margin-left:0; padding:7px 12px; flex:none; }
.ap-editing-note { align-items:flex-start; }
.ap-editing-wait { flex-wrap:wrap; }
.ap-editing-wait input[type="text"], .ap-editing-wait input:not([type]) { flex:1 1 100%; }
.ap-editing-wait input[type="date"] { flex:1 1 140px; }
.ap-item small { display:block; color:var(--muted); font-size:13px; text-decoration:none; }
.ap-editing textarea { flex:1; min-width:0; font:inherit; font-size:16px; line-height:1.4; color:inherit; background:var(--bg); border:1px solid var(--accent); border-radius:10px; padding:8px 10px; resize:vertical; }
.ap-editing textarea:focus { outline:none; }
.ap-edit-buttons { display:flex; flex-direction:column; align-items:center; gap:4px; flex:none; }
.ap-drawer-foot { display:flex; justify-content:space-between; gap:12px; margin-top:4px; flex-wrap:wrap; }
.ap-link[hidden] { display:none; }
.ap-link:disabled { opacity:.4; cursor:default; text-decoration:none; }
.ap-link.danger-link { color:var(--warn); }
.ap-empty.card { padding:28px 16px; text-align:center; background:var(--card); border:1px solid var(--line); border-radius:14px; }
/* Hábitos: una tarjeta por hábito, con el botón de hoy, la racha y la semana */
.hb-today { margin:0 0 12px; font-size:14px; color:var(--muted); }
.hb-today:empty { display:none; }
.hb-today b { color:var(--ink); }
.hb-bar { height:6px; border-radius:3px; background:var(--soft); overflow:hidden; margin-top:6px; max-width:420px; }
.hb-bar i { display:block; height:100%; background:var(--accent); border-radius:3px; transition:width .3s; }
.hb-grid { display:grid; grid-template-columns:repeat(auto-fill, minmax(min(100%, 300px), 1fr)); gap:14px; align-items:start; }
.hb-card { background:var(--card); border:1px solid var(--line); border-radius:14px; padding:14px 16px; display:flex; flex-direction:column; gap:12px; min-width:0; }
.hb-card.done { border-color:color-mix(in srgb, var(--accent) 55%, var(--line)); }
.hb-top { display:flex; align-items:center; gap:12px; }
.hb-check { flex:none; width:46px; height:46px; border-radius:50%; border:2px solid var(--faint); background:none; cursor:pointer; position:relative; transition:background .15s, border-color .15s; }
.hb-check:hover { border-color:var(--accent); }
.hb-check:focus-visible { outline:2px solid var(--accent); outline-offset:3px; }
.hb-check.on { background:var(--accent); border-color:var(--accent); }
.hb-check.on::after { content:""; position:absolute; left:16px; top:9px; width:9px; height:18px; border:solid #14110a; border-width:0 3px 3px 0; transform:rotate(45deg); }
.hb-name { flex:1; min-width:0; }
.hb-name .ap-item { font-size:16px; font-weight:650; overflow-wrap:anywhere; }
.hb-name small { display:block; color:var(--muted); font-size:13px; }
.hb-stats { display:flex; gap:16px; flex-wrap:wrap; font-size:13px; color:var(--muted); }
.hb-stats b { color:var(--ink); font-size:15px; }
.hb-stats .fire b { color:var(--accent); }
.hb-week { display:grid; grid-template-columns:repeat(7, 1fr); gap:4px; }
.hb-day { display:flex; flex-direction:column; align-items:center; gap:3px; font-size:11px; color:var(--faint); }
.hb-day i { width:22px; height:22px; border-radius:50%; background:var(--soft); border:1px solid var(--line); }
.hb-day.on i { background:var(--accent); border-color:var(--accent); }
.hb-day.today { color:var(--ink); font-weight:600; }
.hb-edit { display:flex; flex-wrap:wrap; gap:8px; }
.hb-edit input { font:inherit; font-size:16px; color:inherit; background:var(--bg); border:1px solid var(--accent); border-radius:10px; padding:7px 10px; min-width:0; }
.hb-edit input:not([type]) { flex:1 1 100%; }
.hb-edit input[type="time"] { flex:1 1 120px; border-color:var(--line); }
.hb-edit .primary { margin-left:0; }
.hb-foot { display:flex; justify-content:flex-end; }
.ap-card h3 { font-size:16px; margin:0 0 2px; display:flex; align-items:baseline; gap:8px; }
.ap-card h3 span { font-size:13px; font-weight:400; color:var(--muted); }
.ap-card p { color:var(--muted); font-size:13px; margin:0 0 10px; }
.rc-head { display:flex; align-items:center; gap:12px; margin:0 0 12px; }
.rc-head h3 { margin:0; font-size:18px; min-width:120px; text-align:center; }
.rc-nav { font:inherit; font-size:20px; line-height:1; width:36px; height:36px; border-radius:50%; border:1px solid var(--line); background:var(--card); color:inherit; cursor:pointer; }
.rc-nav:disabled { opacity:.35; cursor:default; }
.rc-summary { background:var(--card); border:1px solid var(--line); border-radius:14px; padding:14px 16px; display:flex; flex-direction:column; gap:8px; max-width:760px; }
.rc-total { display:flex; align-items:baseline; gap:10px; flex-wrap:wrap; margin-bottom:4px; }
.rc-total b { font-size:26px; }
.rc-total span { color:var(--muted); font-size:14px; }
.rc-cat { display:grid; grid-template-columns:minmax(80px, 130px) 1fr auto; align-items:center; gap:10px; font-size:14px; }
.rc-cat-amount { color:var(--muted); font-variant-numeric:tabular-nums; }
.rc-bar { height:8px; border-radius:4px; background:var(--soft); overflow:hidden; }
.rc-bar i { display:block; height:100%; border-radius:4px; }
.rc-cat.near .rc-bar i { background:var(--u-media, #e2b44a); }
.rc-cat.over .rc-bar i { background:var(--warn); }
.rc-cat.over .rc-cat-amount { color:var(--warn); font-weight:600; }
.rc-bar i { background:var(--accent); }
.rc-total .ap-link { margin-left:auto; font-size:14px; }
.rc-budgets { border-top:1px solid var(--line); border-bottom:1px solid var(--line); padding:10px 0; margin:2px 0 6px; display:grid; grid-template-columns:repeat(auto-fill, minmax(min(100%, 220px), 1fr)); gap:8px 16px; }
.rc-budgets p { grid-column:1 / -1; margin:0 0 4px; color:var(--muted); font-size:13px; }
.rc-budget-row { display:flex; align-items:center; gap:10px; font-size:14px; }
.rc-budget-row span { flex:1; }
.rc-budget-row input { width:120px; font:inherit; font-size:16px; color:inherit; background:var(--bg); border:1px solid var(--line); border-radius:10px; padding:7px 10px; }
.rc-budget-row input:focus { outline:none; border-color:var(--accent); }
.rc-budget-buttons { grid-column:1 / -1; display:flex; justify-content:flex-end; gap:10px; }
.rc-budget-buttons .primary { margin-left:0; }
.rc-hint { color:var(--muted); font-size:13px; margin:12px 0; max-width:760px; }
#rc-list { max-width:760px; }
.rc-row { display:flex; align-items:center; gap:12px; padding:10px 12px; background:var(--card); border:1px solid var(--line); border-radius:12px; margin-bottom:8px; }
.rc-thumb { flex:none; width:48px; height:48px; border-radius:8px; border:1px solid var(--line); background:var(--soft); padding:0; overflow:hidden; cursor:zoom-in; font-size:22px; color:inherit; }
.rc-thumb:disabled { cursor:default; }
.rc-thumb img { width:100%; height:100%; object-fit:cover; display:block; }
.rc-body { flex:1; min-width:0; }
.rc-body .ap-item { font-weight:600; font-size:15px; overflow-wrap:anywhere; }
.rc-body small { display:block; color:var(--muted); font-size:13px; }
.rc-amount { font-weight:650; font-variant-numeric:tabular-nums; white-space:nowrap; }
.rc-edit { background:var(--card); border:1px solid var(--accent); border-radius:12px; padding:10px; margin-bottom:8px; align-items:center; }
.rc-edit input:not([type]) { flex:1 1 100%; }
.rc-edit input[type="number"] { flex:1 1 110px; }
.rc-edit input[type="date"] { flex:1 1 140px; }
.rc-warranty { display:flex; align-items:center; gap:8px; flex:1 1 100%; color:var(--muted); font-size:14px; }
dialog#rc-photo { border:1px solid var(--line); border-radius:16px; background:var(--card); color:var(--ink); padding:14px; width:min(560px, calc(100vw - 24px)); }
dialog#rc-photo::backdrop { background:rgba(0,0,0,.7); }
#rc-photo-img { display:block; width:100%; max-height:70vh; object-fit:contain; border-radius:10px; background:#000; }
#rc-photo-items ul { margin:10px 0 0; padding-left:20px; font-size:14px; color:var(--muted); }
@media (max-width:640px) { .rc-cat { grid-template-columns:1fr auto; row-gap:4px; } .rc-cat .rc-bar { grid-column:1 / -1; grid-row:2; } .rc-total b { font-size:22px; } }
.dt-group h4 { font-size:12px; font-weight:650; text-transform:uppercase; letter-spacing:.05em; color:var(--muted); margin:16px 0 8px; }
.dt-group:first-child h4 { margin-top:6px; }
.dt-row { display:flex; align-items:center; gap:12px; padding:10px 12px; border:1px solid var(--line); border-radius:12px; margin-bottom:8px; }
.dt-row.soon { border-color:color-mix(in srgb, var(--accent) 45%, var(--line)); }
.dt-row.today { background:var(--accent-soft); border-color:var(--accent); }
.dt-badge { flex:none; width:52px; padding:5px 0; border-radius:10px; background:var(--soft); text-align:center; line-height:1.1; }
.dt-badge b { display:block; font-size:20px; }
.dt-badge span { font-size:11px; text-transform:uppercase; color:var(--muted); letter-spacing:.04em; }
.dt-row.today .dt-badge { background:var(--accent); color:#14110a; }
.dt-row.today .dt-badge span { color:#14110a; }
.dt-body { flex:1; min-width:0; }
.dt-body .ap-item { font-weight:600; font-size:15px; overflow-wrap:anywhere; }
.dt-body small { display:block; color:var(--muted); font-size:13px; }
.dt-body .when { color:var(--ink); font-weight:600; }
.dt-row.today .when, .dt-row.soon .when { color:var(--accent); }
.dt-edit { border:1px solid var(--accent); border-radius:12px; padding:10px; margin-bottom:8px; align-items:center; }
.dt-edit input:not([type]) { flex:1 1 100%; }
.ap-form { display:flex; gap:8px; flex-wrap:wrap; margin:0 0 10px; }
.ap-form input, .ap-form select { flex:1 1 110px; min-width:0; font:inherit; font-size:16px; color:inherit; background:var(--bg); border:1px solid var(--line); border-radius:10px; padding:8px 10px; }
.ap-form input:focus, .ap-form select:focus { outline:none; border-color:var(--accent); }
.ap-form input.narrow { flex:0 1 84px; }
.ap-form input[type="time"] { flex:0 1 120px; }
.ap-form .primary { margin-left:0; flex:none; }
.ap-sub { display:flex; align-items:center; justify-content:space-between; gap:8px; margin:12px 0 2px; font-weight:600; font-size:14px; text-transform:capitalize; }
.ap-row { display:flex; align-items:center; gap:10px; padding:8px 0; border-top:1px solid var(--line); font-size:15px; }
.ap-row .grow { flex:1; min-width:0; overflow-wrap:anywhere; }
.ap-row small { display:block; color:var(--muted); font-size:13px; }
.ap-check { flex:none; width:24px; height:24px; border-radius:50%; border:2px solid var(--faint); background:none; cursor:pointer; padding:0; position:relative; }
.ap-check:hover { border-color:var(--accent); }
.ap-check.on { background:var(--accent); border-color:var(--accent); }
.ap-check.on::after { content:""; position:absolute; left:7px; top:3px; width:5px; height:10px; border:solid #14110a; border-width:0 2px 2px 0; transform:rotate(45deg); }
.ap-x { flex:none; font:inherit; color:var(--faint); background:none; border:0; cursor:pointer; padding:4px 6px; border-radius:6px; }
.ap-x:hover { color:var(--warn); }
.ap-link { font:inherit; font-size:13px; font-weight:400; color:var(--muted); background:none; border:0; cursor:pointer; padding:4px 0; text-decoration:underline; text-transform:none; }
.ap-empty { color:var(--faint); font-size:14px; padding:6px 0; }
@media (pointer:coarse) { .subtabs a { padding:10px 16px; } .ap-x { padding:8px 10px; } .ap-check { width:28px; height:28px; } .ap-check.on::after { left:9px; top:5px; } }

/* Ajustes */
.set-group { background:var(--card); border:1px solid var(--line); border-radius:14px; padding:6px 16px; margin:0 0 16px; }
.set-group h3 { font-size:15px; margin:12px 0 4px; }
.set-row { display:grid; grid-template-columns:minmax(0, 1fr) minmax(0, 260px); gap:6px 16px; align-items:center; padding:12px 0; border-top:1px solid var(--line); }
.set-row:first-of-type { border-top:0; }
.set-row label { font-weight:600; font-size:14px; }
.set-row small { display:block; font-weight:400; color:var(--muted); font-size:13px; margin-top:2px; }
.set-row input[type="text"], .set-row input[type="password"], .set-row input[type="number"], .set-row input[type="time"], .set-row select {
  width:100%; font:inherit; font-size:16px; color:inherit; background:var(--bg); border:1px solid var(--line); border-radius:10px; padding:9px 11px; }
.set-row input:focus, .set-row select:focus { outline:none; border-color:var(--accent); }
.set-row input:disabled, .set-row select:disabled { opacity:.5; }
.set-row input[type="checkbox"] { width:22px; height:22px; accent-color:var(--accent); justify-self:start; }
.set-row.wide { grid-template-columns:1fr; }
.pw { position:relative; display:block; min-width:0; }
.pw input { width:100%; padding-right:46px !important; }
.pw-eye { position:absolute; right:4px; top:50%; transform:translateY(-50%); width:38px; height:38px; display:grid; place-items:center;
  background:none; border:0; border-radius:8px; color:var(--muted, #a19f96); cursor:pointer; padding:0; }
.pw-eye:hover, .pw-eye:focus-visible { color:var(--accent, #f2c230); outline:none; }
.pw-eye:disabled { opacity:.4; cursor:default; }
.pw-eye[aria-pressed="false"] .eye-off { display:none; }
.chips { display:flex; flex-direction:column; gap:10px; min-width:0; }
.chip-list { display:flex; flex-wrap:wrap; gap:8px; }
.chip { display:inline-flex; align-items:center; gap:7px; padding:5px 6px 5px 12px; border:1px solid var(--line); border-radius:999px; background:var(--soft); font-size:14px; font-weight:550; }
.chip { padding-left:6px; }
.chip-color { -webkit-appearance:none; appearance:none; width:24px; height:24px; padding:0; border:2px solid var(--card); border-radius:50%;
  background:none; cursor:pointer; flex:none; overflow:hidden; box-shadow:0 0 0 1px var(--line); }
.chip-color::-webkit-color-swatch-wrapper { padding:0; }
.chip-color::-webkit-color-swatch { border:0; border-radius:50%; }
.chip-color::-moz-color-swatch { border:0; border-radius:50%; }
.chip-color:focus-visible { outline:2px solid var(--accent); outline-offset:2px; }
.chip-color:disabled { cursor:default; }
.chip-x { font:inherit; font-size:12px; color:var(--muted); background:none; border:0; border-radius:50%; width:24px; height:24px; cursor:pointer; display:grid; place-items:center; }
.chip-x:hover:not(:disabled) { color:var(--warn); background:var(--card); }
.chip-x:disabled { opacity:.35; cursor:default; }
.chip-add { display:flex; gap:8px; max-width:420px; }
.chip-add input { flex:1; min-width:0; font:inherit; font-size:16px; color:inherit; background:var(--bg); border:1px solid var(--line); border-radius:10px; padding:9px 11px; }
.chip-add input:focus { outline:none; border-color:var(--accent); }
.chip-add .ghost { flex:none; }
.chip-note { font-size:13px; color:var(--warn); min-height:0; }
.chip-note:empty { display:none; }
@media (pointer:coarse) { .chip-x { width:32px; height:32px; } .chip-color { width:30px; height:30px; } }
.set-tag { display:inline-block; font-size:11px; font-weight:600; color:var(--muted); border:1px solid var(--line); border-radius:999px; padding:1px 8px; margin-left:6px; vertical-align:1px; }
.set-bar { display:flex; align-items:center; gap:12px; flex-wrap:wrap; margin:0 0 18px; }
.set-bar .primary { margin-left:0; }
.set-note { background:var(--accent-soft); border:1px solid var(--accent); border-radius:12px; padding:12px 14px; margin:0 0 16px; display:flex; align-items:center; gap:12px; flex-wrap:wrap; font-size:14px; }
.set-note[hidden] { display:none; }
@media (max-width:640px) { .set-row { grid-template-columns:1fr; } }

/* Escribirle desde la página */
.say { display:flex; gap:8px; margin:0 0 16px; }
.say input { flex:1; min-width:0; font:inherit; font-size:16px; color:inherit; background:var(--card); border:1px solid var(--line); border-radius:10px; padding:10px 12px; }
.say input:focus { outline:none; border-color:var(--accent); }
.say .primary { margin-left:0; }
.say .primary:disabled { opacity:.5; cursor:default; }

/* Hablarle desde la página */
.talk-btn { position:fixed; right:max(18px, env(safe-area-inset-right)); bottom:calc(18px + env(safe-area-inset-bottom)); z-index:15;
  width:60px; height:60px; border-radius:50%; border:0; cursor:pointer; display:grid; place-items:center;
  background:var(--accent); color:#14110a; box-shadow:0 8px 24px rgba(0,0,0,.45); transition:transform .15s, background .15s; }
.talk-btn[hidden] { display:none; }
.talk-btn:active { transform:scale(.94); }
.talk-btn:focus-visible { outline:2px solid var(--ink); outline-offset:3px; }
.talk-btn svg { width:26px; height:26px; }
.talk-btn .i-stop, .talk-btn .i-wait { display:none; }
.talk-btn[data-state="grabando"] { background:var(--u-alta); color:#fff; animation:talk-pulse 1.2s ease-in-out infinite; }
.talk-btn[data-state="grabando"] .i-mic, .talk-btn[data-state="hablando"] .i-mic, .talk-btn[data-state="pensando"] .i-mic { display:none; }
.talk-btn[data-state="grabando"] .i-stop, .talk-btn[data-state="hablando"] .i-stop { display:block; }
.talk-btn[data-state="pensando"] { cursor:default; opacity:.85; }
.talk-btn[data-state="pensando"] .i-wait { display:block; animation:talk-spin 1s linear infinite; }
@keyframes talk-pulse { 50% { box-shadow:0 0 0 12px color-mix(in srgb, var(--u-alta) 25%, transparent); } }
@keyframes talk-spin { to { transform:rotate(360deg); } }
.talk-panel { position:fixed; right:max(18px, env(safe-area-inset-right)); bottom:calc(90px + env(safe-area-inset-bottom)); z-index:15;
  width:min(380px, calc(100vw - 36px)); max-height:min(60vh, 420px); overflow:auto; background:var(--card); color:var(--ink);
  border:1px solid var(--line); border-radius:14px; box-shadow:0 10px 30px rgba(0,0,0,.45); padding:12px 40px 12px 14px; font-size:15px; }
.talk-panel[hidden] { display:none; }
.talk-panel .heard { color:var(--muted); font-size:13px; margin-bottom:6px; }
.talk-panel .heard:empty { display:none; }
.talk-panel .said { white-space:pre-line; overflow-wrap:anywhere; }
.talk-panel.error .said { color:var(--warn); }
.talk-panel .icon-btn { position:absolute; top:4px; right:4px; }
body.can-speak .toast { bottom:calc(92px + env(safe-area-inset-bottom)); }
body.can-speak main { padding-bottom:calc(96px + env(safe-area-inset-bottom)); }
@media (prefers-reduced-motion: reduce) { .talk-btn[data-state="grabando"] { animation:none; } }

@media (pointer:coarse) {
  /* Zonas de toque de al menos 40 px aunque el dibujo sea pequeño. */
  .tick { position:relative; }
  .tick::after { content:""; position:absolute; inset:-11px; }
  .steps .tick::after { inset:-7px -11px; }
  .steps li { padding:6px 0; }
  .filters button { padding:8px 14px; }
  .tabs a { padding:9px 12px; }
  .ghost, .primary, .danger, .mic-btn { min-height:44px; }
  .icon-btn { min-width:40px; min-height:40px; }
  .undo { padding:8px 0 8px 12px; }
  .toast button { padding:8px 4px; }
  details.finished summary, details.table-view summary { padding:10px 0; }
  /* Con menos de 16 px, el teléfono acerca la página al tocar un campo. */
  .field input, .field select, .add-step input, .search { font-size:16px; min-height:44px; }
}
@media (max-width:640px) {
  .bar { gap:10px 12px; padding-top:10px; padding-bottom:10px; }
  .tabs { order:3; width:100%; }
  .tabs a { flex:1; text-align:center; padding-left:6px; padding-right:6px; }
  main { padding-top:16px; }
  h2 { font-size:20px; }
  section { padding:14px; }
  .stats { grid-template-columns:repeat(2, 1fr); gap:10px; }
  .stat { padding:12px 14px; }
  .stat b { font-size:24px; }
  .task, .group-head { padding-left:14px; padding-right:14px; }
  .task { gap:10px; }
  .top { flex-wrap:wrap; }
  .msg { max-width:92%; }
  .xlabels span:nth-child(even):not(:first-child) { visibility:hidden; }
  /* El editor sube desde abajo y ocupa todo el ancho. */
  dialog#editor { width:100vw; max-width:100vw; margin:auto 0 0; border-radius:18px 18px 0 0; border-width:1px 0 0; max-height:92vh; }
  #ed-form { padding:16px 16px calc(16px + env(safe-area-inset-bottom)); }
  .date-row { flex-wrap:wrap; }
  .date-row input { flex:1 1 190px; }
  .ed-actions .ghost { margin-left:auto; }
  .ed-actions .primary { order:3; flex:1 1 100%; margin-left:0; }
}
@media (max-width:640px) { @supports (height:100dvh) { dialog#editor { max-height:92dvh; } } }
</style>
</head>
<body class="stage">
<header>
  <div class="bar">
    <div class="brand"><span class="brand-dot"></span>Hermes</div>
    <nav class="tabs" aria-label="Secciones">
      <a href="#tareas" data-view="tareas">Tareas</a>
      <a href="#apuntes" data-view="apuntes">Apuntes</a>
      <a href="#consumo" data-view="consumo">Consumo</a>
      <a href="#historial" data-view="historial">Historial</a>
      <a href="#vivo" data-view="vivo">En vivo</a>
      <a href="#ajustes" data-view="ajustes">Ajustes</a>
    </nav>
    <div class="pill" id="pill"><i></i><span>Conectando…</span></div>
  </div>
</header>
<main>
<div id="offline">Hermes no responde. Revisa que esté encendido.</div>

<div class="view" id="view-tareas">
  <h2>Tus tareas</h2>
  <div class="subtitle" id="updated">Cargando…</div>
  <form class="say" id="say-form" autocomplete="off">
    <input id="say-input" maxlength="500" enterkeyhint="send" placeholder="Escribe una tarea o una orden…" aria-label="Escribe una tarea o una orden">
    <button type="submit" class="primary" id="say-send">Enviar</button>
  </form>
  <div class="stats" id="stats" role="group" aria-label="Filtrar por estado">
    <button type="button" class="stat" data-state="pendientes" aria-pressed="true"><b id="s-pending">–</b><span id="s-pending-label">Pendientes</span></button>
    <button type="button" class="stat" data-state="urgentes" aria-pressed="false" id="s-urgent-box"><b id="s-urgent">–</b><span>Urgentes</span></button>
    <button type="button" class="stat" data-state="vencidas" aria-pressed="false" id="s-overdue-box"><b id="s-overdue">–</b><span>Vencidas</span></button>
    <button type="button" class="stat" data-state="hoy" aria-pressed="false"><b id="s-today">–</b><span>Para hoy</span></button>
    <button type="button" class="stat" data-state="terminadas" aria-pressed="false"><b id="s-finished">–</b><span>Terminadas</span></button>
  </div>
  <div class="mode" id="task-mode" role="group" aria-label="Cómo ver las tareas">
    <button type="button" data-mode="lista" aria-pressed="true">Lista</button>
    <button type="button" data-mode="calendario" aria-pressed="false">Calendario</button>
  </div>
  <div class="filters" id="filters" role="group" aria-label="Filtrar por categoría"></div>
  <div class="groups" id="groups"></div>
</div>

<div class="view" id="view-vivo" hidden>
  <div class="stage-wrap">
    <div class="orb" id="orb" data-state="inactiva" aria-hidden="true">
      <span class="ripple"></span><span class="ripple r2"></span><span class="ripple r3"></span>
      <span class="ring" style="--i:1"></span><span class="ring" style="--i:2"></span><span class="ring" style="--i:3"></span>
      <div class="disc"><img src="/logo.webp" alt="" width="1254" height="1254"></div>
    </div>
    <div id="state" role="status">Conectando…</div>
    <div id="hint"></div>
    <button class="mic-btn" id="mic-btn" type="button" aria-pressed="false" disabled>
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/><path id="mic-slash" d="M4 4l16 16"/></svg>
      <span id="mic-label">Dejar de escuchar</span>
    </button>
    <div class="stage-meter">
      <div class="meter"><div id="fill"></div><div id="mark"></div></div>
      <div class="nums"><span id="level">Nivel: 0</span><span id="threshold">Mínimo para contar como voz: 0</span></div>
    </div>
  </div>
</div>

<div class="view" id="view-consumo" hidden>
  <h2>Consumo</h2>
  <div class="subtitle">Con tu suscripción, Claude se descuenta de los límites de tu plan: el costo equivalente es solo lo que valdría por API, como referencia. El modelo local es gratis.</div>
  <div class="stats">
    <div class="stat"><b id="u-claude-today">–</b><span>Tokens de Claude hoy</span><small id="u-claude-today-sub"></small></div>
    <div class="stat"><b id="u-claude-month">–</b><span>Tokens de Claude este mes</span><small id="u-claude-month-sub"></small></div>
    <div class="stat"><b id="u-cost">–</b><span>Costo equivalente del mes</span><small>No se cobra con tu plan</small></div>
    <div class="stat"><b id="u-local-month">–</b><span>Tokens locales este mes</span><small id="u-local-month-sub"></small></div>
  </div>
  <section>
    <div class="label">Tokens por día · últimos 14 días</div>
    <div class="legend"><span><i style="background:var(--s-claude)"></i>Claude</span><span><i style="background:var(--s-local)"></i>Modelo local</span></div>
    <div class="chart-box" id="chart-box"></div>
    <details class="table-view"><summary>Ver como tabla</summary><div class="wide" id="daily-table"></div></details>
  </section>
  <div class="grid2">
    <section><div class="label">Este mes por uso</div><div class="wide" id="by-purpose"></div></section>
    <section><div class="label">Últimas llamadas</div><div class="wide" id="recent-calls"></div></section>
  </div>
</div>

<div class="view" id="view-apuntes" hidden>
  <h1 id="ap-title">Apuntes</h1>
  <div class="subtitle">También puedes pedírselo a Hermes con tus palabras.</div>
  <nav class="subtabs" id="ap-tabs" aria-label="Apartados de Apuntes">
    <a href="#apuntes/listas" data-sub="listas">Listas<span id="ap-tab-listas"></span></a>
    <a href="#apuntes/habitos" data-sub="habitos">Hábitos<span id="ap-tab-habitos"></span></a>
    <a href="#apuntes/notas" data-sub="notas">Notas<span id="ap-tab-notas"></span></a>
    <a href="#apuntes/fechas" data-sub="fechas">Fechas<span id="ap-tab-fechas"></span></a>
    <a href="#apuntes/seguimientos" data-sub="seguimientos">Seguimientos<span id="ap-tab-seguimientos"></span></a>
    <a href="#apuntes/gastos" data-sub="gastos">Gastos<span id="ap-tab-gastos"></span></a>
  </nav>
  <div class="set-note" id="ap-quiet" hidden><span id="ap-quiet-text"></span><button type="button" class="primary" id="ap-quiet-off" style="margin-left:0">Quitar el silencio</button></div>
  <div class="ap-grid">
    <section class="ap-page" data-sub="listas" hidden>
      <form class="ap-form ap-create" id="ap-list-form" autocomplete="off">
        <input id="ap-list-name" maxlength="40" placeholder="Nombre de la lista nueva" aria-label="Nombre de la lista nueva">
        <button type="submit" class="primary">+ Crear lista</button>
      </form>
      <div class="ap-drawers" id="ap-lists"></div>
    </section>
    <section class="ap-page" data-sub="habitos" hidden>
      <form class="ap-form ap-create" id="ap-habit-form" autocomplete="off">
        <input id="ap-habit-title" maxlength="100" placeholder="Hábito nuevo (tomar agua, leer…)" aria-label="Hábito nuevo">
        <input id="ap-habit-time" type="time" aria-label="Hora del recordatorio (opcional)" title="Hora del recordatorio (opcional)">
        <button type="submit" class="primary">+ Crear hábito</button>
      </form>
      <div class="hb-today" id="ap-habits-count"></div>
      <div class="hb-grid" id="ap-habits"></div>
    </section>
    <section class="ap-card" data-sub="notas" hidden>
      <h3>Notas <span id="ap-notes-count"></span></h3>
      <p>Lo que Hermes recuerda de ti y usa al conversar. Toca una nota para corregirla.</p>
      <form class="ap-form" id="ap-note-form" autocomplete="off">
        <input id="ap-note-text" maxlength="500" placeholder="Nueva nota" aria-label="Nota">
        <button type="submit" class="primary">Guardar</button>
      </form>
      <div id="ap-notes"></div>
    </section>
    <section class="ap-card" data-sub="fechas" hidden>
      <h3>Fechas <span id="ap-dates-count"></span></h3>
      <p>Hermes avisa un día antes y ese día. Toca un día del calendario para anotar algo en él, o el nombre de una fecha para corregirla. El año es opcional: sirve para saber cuántos cumple.</p>
      <div id="ap-dates-cal"></div>
      <form class="ap-form" id="ap-date-form" autocomplete="off">
        <select id="ap-date-kind" aria-label="Tipo"><option value="cumpleaños">Cumpleaños</option><option value="aniversario">Aniversario</option></select>
        <input id="ap-date-name" maxlength="80" placeholder="De quién" aria-label="De quién">
        <input id="ap-date-day" class="narrow" type="number" min="1" max="31" placeholder="Día" aria-label="Día">
        <select id="ap-date-month" aria-label="Mes"></select>
        <input id="ap-date-year" class="narrow" type="number" min="1900" placeholder="Año" aria-label="Año (opcional)" title="Año (opcional): para saber cuántos cumple">
        <button type="submit" class="primary">+ Agregar</button>
      </form>
      <div id="ap-dates"></div>
    </section>
    <section class="ap-page" data-sub="gastos" hidden>
      <div class="rc-head">
        <button type="button" class="rc-nav" id="rc-prev" aria-label="Mes anterior">‹</button>
        <h3 id="rc-month"></h3>
        <button type="button" class="rc-nav" id="rc-next" aria-label="Mes siguiente">›</button>
      </div>
      <div class="rc-summary" id="rc-summary"></div>
      <p class="rc-hint">Para agregar un gasto, mándale a Hermes por Telegram la foto del recibo. La lee el modelo de tu computadora: la foto no sale de ahí. Toca un comercio para corregirlo y la foto para verla.</p>
      <div id="rc-list"></div>
    </section>
    <section class="ap-card" data-sub="seguimientos" hidden>
      <h3>Seguimientos <span id="ap-waiting-count"></span></h3>
      <p>Lo que quedaron de mandarte o hacer otras personas. Hermes te pregunta a los días si ya llegó. Para agregar uno, dile «estoy esperando que…».</p>
      <form class="ap-form" id="ap-waiting-form" autocomplete="off">
        <input id="ap-waiting-text" maxlength="180" placeholder="Qué esperas (que Juan mande el contrato)" aria-label="Qué estás esperando">
        <input id="ap-waiting-days" class="narrow" type="number" min="1" max="60" value="3" aria-label="En cuántos días te pregunto" title="En cuántos días te pregunto">
        <button type="submit" class="primary">Agregar</button>
      </form>
      <div id="ap-waiting"></div>
    </section>
  </div>
</div>

<div class="view" id="view-ajustes" hidden>
  <h1>Ajustes</h1>
  <div class="subtitle" id="set-subtitle">Lo que cambies se guarda en el archivo de configuración de Hermes.</div>
  <div class="set-note" id="set-restart" hidden>
    <span>Hay cambios que se aplican al reiniciar Hermes.</span>
    <button type="button" class="primary" id="set-restart-btn" style="margin-left:0">Reiniciar Hermes</button>
  </div>
  <section class="set-group" id="set-sessions" hidden>
    <h3>Dispositivos con la página abierta</h3>
    <div id="set-sessions-list"></div>
    <div class="set-bar" style="margin:10px 0 8px">
      <button type="button" class="ghost" id="set-sessions-all" hidden>Cerrar las demás</button>
      <button type="button" class="ghost" id="set-logout" hidden>Cerrar sesión aquí</button>
    </div>
  </section>
  <form id="set-form" autocomplete="off">
    <div id="set-groups"><div class="empty">Cargando…</div></div>
    <div class="set-bar"><button type="submit" class="primary" id="set-save" disabled>Guardar cambios</button><span class="subtitle" id="set-status" style="margin:0"></span></div>
  </form>
</div>

<div class="view" id="view-historial" hidden>
  <h2>Historial</h2>
  <div class="subtitle">Tus conversaciones con Hermes por Telegram y por voz, de la más antigua a la más reciente.</div>
  <div class="grid2">
    <div class="thread">
      <input class="search" id="search" type="search" placeholder="Buscar en el historial…" aria-label="Buscar en el historial">
      <div id="messages"><div class="empty">Cargando…</div></div>
    </div>
    <section style="align-self:start">
      <div class="label">Últimas veces que te escuchó por voz (desde el último arranque)</div>
      <div id="events"><div class="empty">Di “Hermes” para empezar.</div></div>
    </section>
  </div>
</div>
</main>
<dialog id="editor" aria-labelledby="ed-heading">
  <form id="ed-form" novalidate>
    <div class="ed-head">
      <div>
        <h3 id="ed-heading">Editar tarea</h3>
        <button type="button" class="linkish" id="ed-parent"></button>
      </div>
      <button type="button" class="icon-btn" id="ed-close" aria-label="Cerrar sin guardar">✕</button>
    </div>
    <label class="field"><span>Título</span><input id="ed-title" maxlength="200" autocomplete="off"></label>
    <div class="row2">
      <label class="field"><span>Categoría</span><select id="ed-category"></select></label>
      <label class="field"><span>Repetir el aviso</span><select id="ed-repeat"></select></label>
    </div>
    <fieldset class="field">
      <legend>Urgencia</legend>
      <div class="seg-ctl">
        <label><input type="radio" name="ed-urgency" value="baja"><span style="--u:var(--u-baja)">Baja</span></label>
        <label><input type="radio" name="ed-urgency" value="media"><span style="--u:var(--u-media)">Normal</span></label>
        <label><input type="radio" name="ed-urgency" value="alta"><span style="--u:var(--u-alta)">Urgente</span></label>
      </div>
    </fieldset>
    <div class="field">
      <label for="ed-due" class="field-label">Inicio · cuándo te aviso</label>
      <div class="date-row"><input type="datetime-local" id="ed-due"><button type="button" class="ghost" id="ed-nodate">Sin inicio</button></div>
    </div>
    <div class="field">
      <label for="ed-deadline" class="field-label">Vencimiento · fecha límite</label>
      <div class="date-row"><input type="datetime-local" id="ed-deadline"><button type="button" class="ghost" id="ed-nodeadline">Sin vencimiento</button></div>
    </div>
    <div id="ed-steps-box">
      <div class="field-label">Pasos</div>
      <ul class="ed-steps" id="ed-steps"></ul>
      <div class="add-step"><input id="ed-new-step" maxlength="200" placeholder="Agregar un paso…" aria-label="Nuevo paso" autocomplete="off"><button type="button" class="ghost" id="ed-add-step">Agregar</button></div>
    </div>
    <div class="ed-error" id="ed-error" role="alert"></div>
    <div class="ed-actions">
      <button type="button" class="danger" id="ed-delete">Borrar</button>
      <button type="button" class="ghost" id="ed-done">✓ Marcar como hecha</button>
      <button type="submit" class="primary" id="ed-save">Guardar</button>
    </div>
  </form>
</dialog>
<div class="talk-panel" id="talk-panel" role="status" aria-live="polite" hidden>
  <button type="button" class="icon-btn" id="talk-close" aria-label="Cerrar la respuesta">✕</button>
  <div class="heard" id="talk-heard"></div>
  <div class="said" id="talk-said"></div>
</div>
<button class="talk-btn" id="talk-btn" type="button" data-state="lista" aria-label="Hablar con Hermes" hidden>
  <svg class="i-mic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/></svg>
  <svg class="i-stop" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><rect x="7" y="7" width="10" height="10" rx="2"/></svg>
  <svg class="i-wait" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" aria-hidden="true"><path d="M12 3a9 9 0 1 0 9 9"/></svg>
</button>
<dialog id="rc-photo" aria-label="Foto del recibo">
  <img id="rc-photo-img" alt="Foto del recibo">
  <div id="rc-photo-items"></div>
  <div class="ask-actions"><button type="button" class="ghost" id="rc-photo-close">Cerrar</button></div>
</dialog>
<dialog id="ask" aria-labelledby="ask-text">
  <p id="ask-text"></p>
  <div class="ask-actions">
    <button type="button" class="ghost" id="ask-no">Cancelar</button>
    <button type="button" class="danger" id="ask-yes">Borrar</button>
  </div>
</dialog>
<div class="toast" id="toast" role="status" aria-live="polite"><span id="toast-text"></span><button type="button" id="toast-undo" hidden>Deshacer</button></div>
<script>
const $ = id => document.getElementById(id);
function text(tag, cls, value) { const el = document.createElement(tag); if (cls) el.className = cls; el.textContent = value; return el; }
const TOKEN = document.querySelector('meta[name="hermes-token"]').content;
async function send(path, body) {
  const res = await fetch(path, {
    method: "POST", cache: "no-store",
    headers: { "Content-Type": "application/json", "X-Hermes-Token": TOKEN },
    body: JSON.stringify(body)
  });
  if (res.status === 401) { location.href = "/login"; throw new Error("La sesión terminó; entra de nuevo."); }
  if (res.status === 403) { location.reload(); throw new Error("Hermes se reinició; recargando la página…"); }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || "No se pudo guardar.");
  return data;
}
// Pregunta antes de borrar, en una ventana de la propia página (no el aviso genérico del navegador).
function ask(message, label, calm) {
  return new Promise(resolve => {
    const dialog = $("ask"), yes = $("ask-yes");
    $("ask-text").textContent = message;
    yes.textContent = label || "Borrar";
    yes.className = calm ? "primary" : "danger";
    const finish = value => { dialog.onclose = null; if (dialog.open) dialog.close(); resolve(value); };
    yes.onclick = () => finish(true);
    $("ask-no").onclick = () => finish(false);
    dialog.onclose = () => resolve(false);  // Escape.
    dialog.onclick = event => { if (event.target === dialog) finish(false); };  // Toque fuera de la ventana.
    dialog.showModal();
    $("ask-no").focus();
  });
}
let toastTimer = 0;
function toast(message, undoId, undoAction) {
  $("toast-text").textContent = message;
  const undo = $("toast-undo");
  undo.hidden = !undoId;
  undo.onclick = async () => {
    hideToast();
    try { toast((await taskAction({ action: undoAction || "reopen", id: undoId })).message); } catch (e) { toast(e.message); }
  };
  $("toast").classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(hideToast, undoId ? 7000 : 3500);
}
function hideToast() { $("toast").classList.remove("show"); }

/* ---------- Navegación ---------- */
const VIEWS = ["tareas", "apuntes", "consumo", "historial", "vivo", "ajustes"];
function currentView() { const v = location.hash.slice(1).split("/")[0]; return VIEWS.includes(v) ? v : "tareas"; }
// Apuntes tiene un submenú: cada apartado es su propia página (#apuntes/listas, #apuntes/habitos…).
const AP_SUBS = { listas: "Listas", habitos: "Hábitos", notas: "Notas", fechas: "Fechas", seguimientos: "Seguimientos", gastos: "Gastos" };
let lastSub = "listas";
function currentSub() {
  const sub = location.hash.slice(1).split("/")[1];
  if (AP_SUBS[sub]) lastSub = sub;
  return lastSub;
}
function showSub() {
  const sub = currentSub();
  document.querySelectorAll("#view-apuntes section[data-sub]").forEach(page => { page.hidden = page.dataset.sub !== sub; });
  document.querySelectorAll("#ap-tabs a").forEach(a => a.setAttribute("aria-current", a.dataset.sub === sub ? "page" : "false"));
}
function showView() {
  const view = currentView();
  for (const name of VIEWS) $("view-" + name).hidden = name !== view;
  document.querySelectorAll(".tabs a").forEach(a => a.setAttribute("aria-current", a.dataset.view === view ? "page" : "false"));
  if (view === "tareas") loadTasks();
  if (view === "consumo") loadUsage();
  if (view === "historial") loadHistory();
  if (view === "ajustes") { loadSettings(); loadSessions(); }
  if (view === "apuntes") { showSub(); loadApuntes(); }
}
window.addEventListener("hashchange", showView);

/* ---------- Calendario mensual ---------- */
const CAL_MONTHS = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"];
// cal: { year, month (0-11), picked (día del mes o null) }. marks: { día: [{ label, cls }] }. redraw: vuelve a pintar.
function monthGrid(cal, marks, redraw) {
  const today = new Date();
  const box = text("div", "cal", "");
  const head = text("div", "cal-head", "");
  const nav = (label, aria, step) => {
    const b = text("button", "cal-nav", label); b.type = "button"; b.setAttribute("aria-label", aria);
    b.onclick = () => { const d = new Date(cal.year, cal.month + step, 1); cal.year = d.getFullYear(); cal.month = d.getMonth(); cal.picked = null; redraw(); };
    return b;
  };
  const now = text("button", "cal-nav", "Hoy"); now.type = "button";
  now.onclick = () => { cal.year = today.getFullYear(); cal.month = today.getMonth(); cal.picked = today.getDate(); redraw(); };
  head.append(nav("‹", "Mes anterior", -1), text("b", "", CAL_MONTHS[cal.month] + " " + cal.year), now, nav("›", "Mes siguiente", 1));
  const grid = text("div", "cal-grid", "");
  for (const day of ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]) grid.append(text("div", "cal-wd", day));
  const offset = (new Date(cal.year, cal.month, 1).getDay() + 6) % 7;  // La semana empieza en lunes.
  for (let i = 0; i < offset; i++) grid.append(document.createElement("span"));
  const days = new Date(cal.year, cal.month + 1, 0).getDate();
  for (let day = 1; day <= days; day++) {
    const items = marks[day] || [];
    const isToday = day === today.getDate() && cal.month === today.getMonth() && cal.year === today.getFullYear();
    const cell = text("button", "cal-day" + (isToday ? " today" : "") + (day === cal.picked ? " picked" : ""), ""); cell.type = "button";
    cell.setAttribute("aria-label", day + " de " + CAL_MONTHS[cal.month] + (items.length ? ": " + items.map(i => i.label).join(", ") : ""));
    cell.setAttribute("aria-pressed", String(day === cal.picked));
    cell.append(text("span", "n", String(day)));
    items.slice(0, 2).forEach(i => cell.append(text("span", "m " + (i.cls || ""), i.label)));
    if (items.length > 2) cell.append(text("span", "more", "+" + (items.length - 2)));
    if (items.length) {
      const dots = text("span", "dots", "");
      items.slice(0, 4).forEach(i => dots.append(text("i", i.cls || "", "")));
      cell.append(dots);
    }
    cell.onclick = () => { cal.picked = day; redraw(); };
    grid.append(cell);
  }
  box.append(head, grid);
  return box;
}

/* ---------- Tareas ---------- */
const URGENCY = { alta: "Urgente", media: "Normal", baja: "Baja" };
const URGENCY_ORDER = { alta: 0, media: 1, baja: 2 };
const KNOWN = ["trabajo", "negocios", "casa", "personal", "salud", "finanzas", "reptiles"];
let filter = "todas";
let stateFilter = "pendientes";  // El estado elegido arriba: pendientes, urgentes, vencidas, hoy o terminadas.
// Categorías minimizadas: se recuerdan en este navegador.
let collapsed = new Set();
try { collapsed = new Set(JSON.parse(localStorage.getItem("hermes-collapsed") || "[]")); } catch {}
const STATE_EMPTY = {
  pendientes: ["No tienes tareas pendientes", "Escríbele o háblale a Hermes para anotar algo."],
  urgentes: ["Nada urgente", "Ninguna tarea pendiente está marcada como urgente."],
  vencidas: ["Nada vencido", "Vas al día con todo."],
  hoy: ["Nada para hoy", "No hay tareas que empiecen o venzan en lo que queda del día."],
  terminadas: ["Todavía no hay tareas terminadas", "Aquí aparecen las que marques como hechas o canceles."],
};
let lastTasks = null;
// Lista o calendario: se recuerda en este navegador.
let taskMode = "lista";
try { if (localStorage.getItem("hermes-task-mode") === "calendario") taskMode = "calendario"; } catch {}
const taskCal = { year: new Date().getFullYear(), month: new Date().getMonth(), picked: new Date().getDate() };
// El color elegido en Ajustes; si no hay, el de siempre para las conocidas y gris para las demás.
const catColor = c => (lastTasks && lastTasks.colors && lastTasks.colors[c]) || "var(--c-" + (KNOWN.includes(c) ? c : "otra") + ")";
function interval(minutes) {
  if (!minutes) return "";
  if (minutes % 60 === 0) return minutes === 60 ? "cada hora" : "cada " + minutes / 60 + " h";
  return "cada " + minutes + " min";
}
function dayStart(d) { return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime(); }
function due(ts, nowTs) {
  if (!ts) return { label: "Sin fecha", cls: "" };
  const d = new Date(ts * 1000), now = new Date(nowTs * 1000);
  const time = d.toLocaleTimeString("es", { hour: "2-digit", minute: "2-digit" });
  const days = Math.round((dayStart(d) - dayStart(now)) / 86400000);
  const date = d.toLocaleDateString("es", { weekday: "short", day: "numeric", month: "short" });
  if (ts < nowTs) return { label: "Vencida · " + (days === 0 ? "hoy " + time : days === -1 ? "ayer " + time : date), cls: "overdue" };
  if (days === 0) return { label: "Hoy " + time, cls: "today" };
  if (days === 1) return { label: "Mañana " + time, cls: "" };
  if (days < 7) return { label: d.toLocaleDateString("es", { weekday: "long" }) + " " + time, cls: "" };
  return { label: date + " " + time, cls: "" };
}
function moment(ts, nowTs) {
  const d = new Date(ts * 1000), now = new Date(nowTs * 1000);
  const time = d.toLocaleTimeString("es", { hour: "2-digit", minute: "2-digit" });
  const days = Math.round((dayStart(d) - dayStart(now)) / 86400000);
  if (days === 0) return "hoy " + time;
  if (days === 1) return "mañana " + time;
  if (days === -1) return "ayer " + time;
  if (days > 1 && days < 7) return d.toLocaleDateString("es", { weekday: "long" }) + " " + time;
  return d.toLocaleDateString("es", { weekday: "short", day: "numeric", month: "short" }) + " " + time;
}
function deadline(ts, nowTs) {
  const today = dayStart(new Date(ts * 1000)) === dayStart(new Date(nowTs * 1000));
  if (ts < nowTs) return { label: "Venció " + moment(ts, nowTs), cls: "overdue" };
  return { label: "Vence " + moment(ts, nowTs), cls: today ? "today" : "" };
}
const overdueFrom = t => t.deadline_at || t.due_at || null;
const firstDate = t => t.due_at || t.deadline_at || Infinity;
function sortTasks(a, b) {
  const da = firstDate(a), db = firstDate(b);
  return da - db || URGENCY_ORDER[a.urgency] - URGENCY_ORDER[b.urgency] || a.id - b.id;
}
function metaLine(t, nowTs, compact) {
  const meta = text("div", "meta", "");
  if (!compact) meta.append(text("span", "", "#" + t.id));
  if (t.deadline_at) {
    if (t.due_at) meta.append(text("span", "due", "Inicio " + moment(t.due_at, nowTs)));
    const v = deadline(t.deadline_at, nowTs);
    meta.append(text("span", "due " + v.cls, v.label));
  } else {
    const d = due(t.due_at, nowTs);
    meta.append(text("span", "due " + d.cls, d.label));
  }
  if (t.urgency === "alta") meta.append(text("span", "tag alta", "Urgente"));
  else if (!compact && t.urgency === "baja") meta.append(text("span", "tag", "Baja"));
  if (t.repeat_minutes) meta.append(text("span", "tag", "🔁 " + interval(t.repeat_minutes)));
  return meta;
}
function tickButton(t) {
  const done = t.status === "done";
  const b = text("button", "tick", "✓");
  b.type = "button";
  b.setAttribute("aria-pressed", String(done));
  b.setAttribute("aria-label", (done ? "Volver a pendiente: " : "Marcar como hecha: ") + t.title);
  b.title = done ? "Volver a pendiente" : "Marcar como hecha";
  b.onclick = async e => {
    e.stopPropagation();
    b.disabled = true;
    try {
      const r = await taskAction({ action: done ? "reopen" : "done", id: t.id });
      toast(r.message, done ? 0 : t.id);
    } catch (err) { toast(err.message); }
    b.disabled = false;
  };
  return b;
}
function taskRow(t, steps, nowTs) {
  const row = text("div", "task", "");
  row.append(text("span", "urg " + t.urgency, ""), tickButton(t));
  const main = text("div", "task-main clickable", "");
  const title = text("button", "task-title linkish", t.title);
  title.type = "button";
  title.setAttribute("aria-label", "Editar: " + t.title);
  main.addEventListener("click", e => { if (!e.target.closest(".steps button, .tick")) openEditor(t.id); });
  main.append(title, metaLine(t, nowTs, false));
  if (steps.length) {
    const done = steps.filter(s => s.status === "done").length;
    const progress = text("div", "progress", "");
    const track = text("div", "track", "");
    const fill = document.createElement("div");
    fill.style.width = Math.round(100 * done / steps.length) + "%";
    track.append(fill);
    progress.append(track, text("span", "", done + " de " + steps.length + " pasos"));
    const list = text("ul", "steps", "");
    for (const s of steps) {
      const li = text("li", s.status === "done" ? "done" : "", "");
      const name = text("button", "linkish", s.title);
      name.type = "button";
      name.disabled = s.status === "done";
      name.setAttribute("aria-label", "Editar paso: " + s.title);
      name.onclick = e => { e.stopPropagation(); openEditor(s.id); };
      li.append(tickButton(s), name);
      if (s.status !== "done") li.append(metaLine(s, nowTs, true));
      list.append(li);
    }
    main.append(progress, list);
  }
  row.append(main);
  return row;
}
function stamp(ts) {
  const d = new Date(ts * 1000);
  return d.toLocaleDateString("es", { weekday: "short", day: "numeric", month: "short", year: "numeric" }) + ", " +
    d.toLocaleTimeString("es", { hour: "2-digit", minute: "2-digit" });
}
function finishedRow(t, steps) {
  const done = t.status === "done";
  const row = text("div", "task", "");
  row.append(text("span", "urg " + t.urgency, ""));
  const main = text("div", "task-main", "");
  main.append(text("div", "task-title", t.title));
  const meta = text("div", "meta", "");
  meta.append(text("span", "", "#" + t.id), text("span", "tag" + (done ? " ok" : ""), done ? "✓ Hecha" : "✕ Cancelada"));
  if (t.completed_at) meta.append(text("span", "", (done ? "Terminada " : "Cancelada ") + stamp(t.completed_at)));
  if (done && t.deadline_at && t.completed_at) {
    const late = t.completed_at > t.deadline_at;
    meta.append(text("span", "tag" + (late ? " alta" : ""), late ? "Con retraso" : "A tiempo"));
  }
  const info = text("div", "meta", "");
  info.append(text("span", "", "Urgencia " + t.urgency));
  info.append(text("span", "", t.due_at ? "Inicio " + stamp(t.due_at) : "Sin fecha de inicio"));
  if (t.deadline_at) info.append(text("span", "", "Vencía " + stamp(t.deadline_at)));
  if (t.repeat_minutes) info.append(text("span", "tag", "🔁 " + interval(t.repeat_minutes)));
  main.append(meta, info);
  if (steps.length) {
    const list = text("ul", "steps", "");
    for (const s of steps) {
      const li = text("li", s.status === "done" ? "done" : "", "");
      li.append(text("span", "fin-mark", s.status === "done" ? "✓" : "✕"), text("span", "", s.title));
      if (s.completed_at) li.append(text("span", "meta", stamp(s.completed_at)));
      list.append(li);
    }
    main.append(list);
  }
  const actions = text("div", "fin-actions", "");
  const back = text("button", "undo", "Volver a pendientes"); back.type = "button";
  back.onclick = async () => {
    back.disabled = true;
    try { toast((await taskAction({ action: "reopen", id: t.id })).message); } catch (e) { toast(e.message); back.disabled = false; }
  };
  const remove = text("button", "undo danger-link", "Borrar"); remove.type = "button";
  remove.onclick = async () => {
    if (!await ask("¿Borrar «" + t.title + "»? Dejará de aparecer en la página.")) return;
    remove.disabled = true;
    try { toast((await taskAction({ action: "delete", id: t.id })).message, t.id, "restore"); } catch (e) { toast(e.message); remove.disabled = false; }
  };
  actions.append(back, remove);
  main.append(actions);
  row.append(main);
  return row;
}
function renderTaskCalendar(tasks, ended, stepsOf, finished, nowTs) {
  const groups = $("groups");
  const entries = [];  // Cada fecha de cada tarea: su inicio, su vencimiento y las de sus pasos pendientes.
  for (const t of tasks) {
    if (ended) { if (t.completed_at) entries.push({ t, ts: t.completed_at }); continue; }
    if (t.due_at) entries.push({ t, ts: t.due_at });
    if (t.deadline_at) entries.push({ t, ts: t.deadline_at, label: "Vence: " + t.title });
    for (const step of stepsOf(t.id)) {
      if (step.status !== "pending") continue;
      if (step.due_at) entries.push({ t, ts: step.due_at, label: step.title });
      if (step.deadline_at) entries.push({ t, ts: step.deadline_at, label: "Vence: " + step.title });
    }
  }
  entries.sort((a, b) => a.ts - b.ts);
  const marks = {}, picked = [];
  for (const e of entries) {
    const d = new Date(e.ts * 1000);
    if (d.getFullYear() !== taskCal.year || d.getMonth() !== taskCal.month) continue;
    const cls = (e.t.urgency === "alta" ? "alta" : "") + (!ended && e.ts < nowTs ? " late" : "");
    (marks[d.getDate()] = marks[d.getDate()] || []).push({ label: e.label || e.t.title, cls: cls.trim() });
    if (d.getDate() === taskCal.picked) picked.push(e.t);
  }
  groups.append(monthGrid(taskCal, marks, () => renderTasks(lastTasks)));
  const group = (title, list) => {
    const card = text("div", "card group", "");
    const head = text("div", "group-head", "");
    head.append(text("span", "name", title), text("em", "", list.length + (list.length === 1 ? " tarea" : " tareas")));
    card.append(head);
    if (!list.length) card.append(text("div", "cal-none", ended ? "No terminaste nada este día." : "Nada para este día."));
    list.forEach(t => card.append(ended ? finishedRow(t, finished.filter(x => x.parent_id === t.id).sort((a, b) => a.id - b.id)) : taskRow(t, stepsOf(t.id), nowTs)));
    groups.append(card);
  };
  if (taskCal.picked) {
    const date = new Date(taskCal.year, taskCal.month, taskCal.picked);
    group(date.toLocaleDateString("es", { weekday: "long", day: "numeric", month: "long" }), [...new Set(picked)]);
  }
  if (!ended) {
    const dated = t => t.due_at || t.deadline_at || stepsOf(t.id).some(x => x.status === "pending" && (x.due_at || x.deadline_at));
    const undated = tasks.filter(t => !dated(t)).sort(sortTasks);
    if (undated.length) group("Sin fecha", undated);
  }
}
function renderTasks(data) {
  const nowTs = data.now;
  const pending = data.pending || [];
  const ids = new Set(pending.map(t => t.id));
  const stepsOf = id => [...pending, ...(data.done_steps || [])].filter(t => t.parent_id === id).sort((a, b) => a.id - b.id);
  const roots = pending.filter(t => t.parent_id === null || !ids.has(t.parent_id));
  const finished = data.finished || [];
  const finishedIds = new Set(finished.map(t => t.id));
  // Un paso terminado de una tarea que sigue abierta se ve dentro de ella, no como tarea aparte.
  const finishedRoots = finished.filter(t => t.parent_id === null || (!finishedIds.has(t.parent_id) && !ids.has(t.parent_id)));
  const todayEnd = dayStart(new Date(nowTs * 1000)) / 1000 + 86400;
  const inToday = ts => ts && ts >= nowTs && ts < todayEnd;
  const isOverdue = t => !!overdueFrom(t) && overdueFrom(t) < nowTs;
  const MATCH = {
    pendientes: () => true,
    urgentes: t => t.urgency === "alta",
    vencidas: isOverdue,
    hoy: t => !isOverdue(t) && (inToday(t.due_at) || inToday(t.deadline_at)),
  };
  // Una tarea entra en un estado si ella o alguno de sus pasos pendientes lo cumple.
  const rootsIn = state => roots.filter(r => [r, ...stepsOf(r.id).filter(s => s.status === "pending")].some(MATCH[state]));
  $("s-pending").textContent = roots.length;
  const steps = pending.length - roots.length;
  $("s-pending-label").textContent = steps ? "Pendientes · " + steps + (steps === 1 ? " paso" : " pasos") : "Pendientes";
  $("s-urgent").textContent = rootsIn("urgentes").length;
  const overdue = rootsIn("vencidas").length;
  $("s-overdue").textContent = overdue;
  $("s-overdue-box").classList.toggle("alert", overdue > 0);
  $("s-today").textContent = rootsIn("hoy").length;
  $("s-finished").textContent = finishedRoots.length;
  document.querySelectorAll("#stats .stat").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.state === stateFilter)));
  $("updated").textContent = "Actualizado " + new Date(nowTs * 1000).toLocaleTimeString("es", { hour: "2-digit", minute: "2-digit" });

  const ended = stateFilter === "terminadas";
  const shown = ended ? finishedRoots : rootsIn(stateFilter);
  const categories = [...new Set([...(data.categories || []), ...shown.map(t => t.category)])];
  const counts = Object.fromEntries(categories.map(c => [c, shown.filter(t => t.category === c).length]));
  if (filter !== "todas" && !counts[filter]) filter = "todas";
  const filters = $("filters"); filters.replaceChildren();
  const chip = (value, label, count) => {
    const b = document.createElement("button");
    b.type = "button"; b.setAttribute("aria-pressed", String(filter === value));
    if (value !== "todas") { const dot = text("span", "dot", ""); dot.style.setProperty("--cat", catColor(value)); b.append(dot); }
    b.append(text("span", "", label), text("em", "", String(count)));
    b.onclick = () => { filter = value; renderTasks(lastTasks); };
    filters.append(b);
  };
  chip("todas", "Todas", shown.length);
  categories.filter(c => counts[c]).forEach(c => chip(c, c.charAt(0).toUpperCase() + c.slice(1), counts[c]));

  const groups = $("groups"); groups.replaceChildren();
  document.querySelectorAll("#task-mode button").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.mode === taskMode)));
  if (taskMode === "calendario") {
    renderTaskCalendar(shown.filter(t => filter === "todas" || t.category === filter), ended, stepsOf, finished, nowTs);
    return;
  }
  const visible = categories.filter(c => counts[c] && (filter === "todas" || filter === c));
  if (!visible.length) {
    const empty = text("div", "empty-state card", "");
    empty.append(text("b", "", STATE_EMPTY[stateFilter][0]), text("span", "", STATE_EMPTY[stateFilter][1]));
    groups.append(empty);
  }
  for (const c of visible) {
    const card = text("div", "card group", "");
    const closed = collapsed.has(c);
    const head = text("button", "group-head", "");
    head.type = "button";
    head.setAttribute("aria-expanded", String(!closed));
    head.setAttribute("aria-label", (closed ? "Mostrar" : "Minimizar") + " las tareas de " + c);
    head.onclick = () => {
      if (collapsed.has(c)) collapsed.delete(c); else collapsed.add(c);
      try { localStorage.setItem("hermes-collapsed", JSON.stringify([...collapsed])); } catch {}
      renderTasks(lastTasks);
    };
    const dot = text("span", "dot", ""); dot.style.setProperty("--cat", catColor(c));
    head.append(dot, text("span", "name", c), text("em", "", counts[c] + (counts[c] === 1 ? " tarea" : " tareas")), text("span", "chev", ""));
    card.append(head);
    if (closed) { card.classList.add("closed"); groups.append(card); continue; }
    const rows = shown.filter(t => t.category === c);
    if (ended) rows.forEach(t => card.append(finishedRow(t, finished.filter(s => s.parent_id === t.id).sort((a, b) => a.id - b.id))));
    else rows.sort(sortTasks).forEach(t => card.append(taskRow(t, stepsOf(t.id), nowTs)));
    groups.append(card);
  }
}
document.querySelectorAll("#task-mode button").forEach(button => {
  button.addEventListener("click", () => {
    taskMode = button.dataset.mode;
    try { localStorage.setItem("hermes-task-mode", taskMode); } catch {}
    if (lastTasks) renderTasks(lastTasks);
  });
});
document.querySelectorAll("#stats .stat").forEach(button => {
  button.addEventListener("click", () => {
    const state = button.dataset.state;
    stateFilter = stateFilter === state ? "pendientes" : state;  // Tocar otra vez el mismo estado quita el filtro.
    filter = "todas";
    if (lastTasks) renderTasks(lastTasks);
  });
});
let tasksSerialized = "";
async function loadTasks(force) {
  if (force) tasksSerialized = "";
  try {
    const res = await fetch("/tasks", { cache: "no-store" });
    const data = await res.json();
    const serialized = JSON.stringify({ ...data, now: Math.floor(data.now / 60) });
    if (serialized !== tasksSerialized || !lastTasks) { tasksSerialized = serialized; lastTasks = data; renderTasks(data); }
  } catch { $("offline").style.display = "block"; }
}
setInterval(() => { if (currentView() === "tareas") loadTasks(); }, 5000);

/* ---------- Editor de tareas ---------- */
const REPEATS = [[0, "No se repite"], [15, "Cada 15 min"], [30, "Cada 30 min"], [60, "Cada hora"], [120, "Cada 2 h"],
  [180, "Cada 3 h"], [240, "Cada 4 h"], [360, "Cada 6 h"], [720, "Cada 12 h"], [1440, "Una vez al día"]];
let editing = null;
const capitalize = s => s.charAt(0).toUpperCase() + s.slice(1);
const pad = n => String(n).padStart(2, "0");
function toLocalInput(ts) {
  if (!ts) return "";
  const d = new Date(ts * 1000);
  return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()) + "T" + pad(d.getHours()) + ":" + pad(d.getMinutes());
}
function findPending(id) { return lastTasks ? (lastTasks.pending || []).find(t => t.id === id) : null; }
function stepsFor(id) {
  return [...(lastTasks.pending || []), ...(lastTasks.done_steps || [])].filter(t => t.parent_id === id).sort((a, b) => a.id - b.id);
}
async function taskAction(body) {
  const result = await send("/tasks", body);
  await loadTasks(true);
  if ($("editor").open) {
    if (findPending(editing)) renderEditorSteps(); else closeEditor();
  }
  return result;
}
function fillSelect(select, options, value) {
  select.replaceChildren();
  for (const [v, label] of options) { const o = text("option", "", label); o.value = String(v); select.append(o); }
  select.value = String(value);
}
function openEditor(id) {
  const t = findPending(id);
  if (!t) return;
  editing = id;
  const parent = t.parent_id !== null ? findPending(t.parent_id) : null;
  $("ed-heading").textContent = parent ? "Editar paso" : "Editar tarea";
  const back = $("ed-parent");
  back.textContent = parent ? "← Paso de «" + parent.title + "»" : "Tarea #" + t.id;
  back.disabled = !parent;
  back.onclick = parent ? () => openEditor(parent.id) : null;
  $("ed-title").value = t.title;
  const categories = [...new Set([...(lastTasks.categories || []), t.category])];
  fillSelect($("ed-category"), categories.map(c => [c, capitalize(c)]), t.category);
  const repeats = REPEATS.slice();
  if (t.repeat_minutes && !repeats.some(([m]) => m === t.repeat_minutes)) repeats.push([t.repeat_minutes, "Cada " + t.repeat_minutes + " min"]);
  fillSelect($("ed-repeat"), repeats, t.repeat_minutes || 0);
  document.querySelectorAll('input[name="ed-urgency"]').forEach(r => r.checked = r.value === t.urgency);
  $("ed-due").value = toLocalInput(t.due_at);
  $("ed-deadline").value = toLocalInput(t.deadline_at);
  $("ed-steps-box").hidden = !!parent;
  $("ed-done").textContent = parent ? "✓ Marcar paso como hecho" : "✓ Marcar como hecha";
  $("ed-new-step").value = "";
  $("ed-error").textContent = "";
  renderEditorSteps();
  if (!$("editor").open) $("editor").showModal();
}
function closeEditor() { editing = null; if ($("editor").open) $("editor").close(); }
function renderEditorSteps() {
  const list = $("ed-steps"); list.replaceChildren();
  if (editing === null) return;
  const steps = stepsFor(editing);
  if (!steps.length) list.append(text("li", "empty", "Sin pasos. Agrega uno abajo."));
  for (const s of steps) {
    const li = text("li", s.status === "done" ? "done" : "", "");
    const name = text("button", "linkish", s.title);
    name.type = "button";
    name.disabled = s.status === "done";
    name.onclick = () => openEditor(s.id);
    li.append(tickButton(s), name);
    if (s.status !== "done") {
      const del = text("button", "icon-btn", "✕");
      del.type = "button";
      del.setAttribute("aria-label", "Borrar paso: " + s.title);
      del.title = "Borrar paso";
      del.onclick = () => editorRun(async () => {
        if (!await ask("¿Borrar el paso «" + s.title + "»?")) return;
        toast((await taskAction({ action: "cancel", id: s.id })).message, s.id);
      });
      li.append(del);
    }
    list.append(li);
  }
}
async function editorRun(work) {
  const buttons = [...$("ed-form").querySelectorAll("button")];
  buttons.forEach(b => b.disabled = true);
  $("ed-error").textContent = "";
  try { await work(); } catch (e) { $("ed-error").textContent = e.message; }
  buttons.forEach(b => b.disabled = false);
  $("ed-parent").disabled = !$("ed-parent").onclick;
  renderEditorSteps();
}
$("ed-close").onclick = closeEditor;
$("editor").addEventListener("close", () => { editing = null; });
$("editor").addEventListener("click", e => { if (e.target === $("editor")) closeEditor(); });
$("ed-nodate").onclick = () => { $("ed-due").value = ""; $("ed-repeat").value = "0"; };
$("ed-nodeadline").onclick = () => { $("ed-deadline").value = ""; };
$("ed-form").addEventListener("submit", e => {
  e.preventDefault();
  editorRun(async () => {
    const t = findPending(editing);
    if (!t) { closeEditor(); return; }
    const body = { action: "edit", id: t.id };
    const title = $("ed-title").value.trim();
    if (!title) throw new Error("El título no puede quedar vacío.");
    if (title !== t.title) body.title = title;
    if ($("ed-category").value !== t.category) body.category = $("ed-category").value;
    const urgency = document.querySelector('input[name="ed-urgency"]:checked').value;
    if (urgency !== t.urgency) body.urgency = urgency;
    const readDate = (id, original, field, label) => {
      const value = $(id).value;
      if (value === toLocalInput(original)) return;
      const ts = value ? Math.floor(new Date(value).getTime() / 1000) : null;
      if (value && !Number.isFinite(ts)) throw new Error("Fecha de " + label + " inválida.");
      body[field] = ts;
    };
    readDate("ed-due", t.due_at, "due_at", "inicio");
    readDate("ed-deadline", t.deadline_at, "deadline_at", "vencimiento");
    const start = "due_at" in body ? body.due_at : t.due_at, end = "deadline_at" in body ? body.deadline_at : t.deadline_at;
    if (start && end && end < start) throw new Error("El vencimiento tiene que ser después del inicio.");
    const repeat = Number($("ed-repeat").value) || null;
    if (repeat !== (t.repeat_minutes || null)) body.repeat_minutes = repeat;
    if (Object.keys(body).length > 2) toast((await taskAction(body)).message);
    closeEditor();
  });
});
$("ed-done").onclick = () => editorRun(async () => {
  const id = editing;
  const r = await taskAction({ action: "done", id });
  toast(r.message, id);
});
$("ed-delete").onclick = () => editorRun(async () => {
  const t = findPending(editing);
  if (!t) return;
  const steps = stepsFor(t.id).filter(s => s.status !== "done").length;
  const extra = steps ? " También se borrarán sus " + steps + " pasos pendientes." : "";
  if (!await ask("¿Borrar «" + t.title + "»? Dejará de aparecer en la página." + extra)) return;
  toast((await taskAction({ action: "delete", id: t.id })).message, t.id, "restore");
});
function addStep() {
  const title = $("ed-new-step").value.trim();
  if (!title) return;
  editorRun(async () => {
    await taskAction({ action: "add_step", id: editing, title });
    $("ed-new-step").value = "";
  });
}
$("ed-add-step").onclick = addStep;
$("ed-new-step").addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); addStep(); } });

/* ---------- En vivo ---------- */
const STATES = {
  inactiva: ["Inactiva", "La voz en casa no está disponible."],
  escuchando: ["Escuchando", "Di “Hermes”. Nada se graba hasta entonces."],
  pausada: ["En pausa", "El micrófono está apagado. Telegram sigue funcionando."],
  pitido: ["Te oí", "Espera el pitido."],
  grabando: ["Grabando tu orden", "Habla ahora. Termina cuando te quedes callado."],
  transcribiendo: ["Entendiendo el audio", "Convirtiendo tu voz en texto."],
  pensando: ["Pensando", "El modelo está procesando tu orden."],
  hablando: ["Respondiendo", "Hermes está hablando."]
};
const OUTCOMES = {
  ok: ["Respondió", false],
  sin_voz: ["No detectó tu voz después del pitido", true],
  sin_texto: ["No entendió palabras", true],
  solo_nombre: ["Solo oyó su nombre", true],
  descartada: ["Ignorado: no oyó “Hermes”, no respondió", true],
  error: ["Ocurrió un error", true]
};
const SCALE = 3000;
let shown = -1;
function pct(value) { return Math.min(100, Math.sqrt(value / SCALE) * 100); }
function line(label, value) {
  const div = document.createElement("div"); div.className = "line";
  div.append(text("b", "", label + ": "), document.createTextNode(value));
  return div;
}
function renderEvents(events) {
  const box = $("events"); box.replaceChildren();
  if (!events.length) { box.append(text("div", "empty", "Di “Hermes” para empezar.")); return; }
  for (const e of events) {
    const item = text("div", "event", "");
    const top = text("div", "top", "");
    const [label, bad] = OUTCOMES[e.outcome] || [e.outcome, true];
    top.append(text("span", "outcome" + (bad ? " bad" : ""), label), text("span", "", e.at));
    item.append(top);
    if (e.heard) item.append(line("Oyó", e.heard));
    if (e.reply) item.append(line("Respondió", e.reply));
    item.append(text("div", "line", "Volumen más alto: " + e.peak + " (mínimo para voz: " + e.threshold + ")"));
    const times = text("div", "times", "");
    for (const [name, seconds] of Object.entries(e.timings)) {
      times.append(text("span", "chip" + (name === "total" ? " total" : ""), name + " " + seconds + " s"));
    }
    item.append(times);
    box.append(item);
  }
}
const PROVIDERS = { claude: "Claude", local: "Modelo local" };
const num = value => Number(value || 0).toLocaleString("es");
const usd = value => "$" + Number(value || 0).toFixed(4);
function table(headers, rows) {
  const el = document.createElement("table");
  const head = document.createElement("tr");
  headers.forEach(h => head.append(text("th", "", h)));
  el.append(head);
  for (const row of rows) {
    const tr = document.createElement("tr");
    row.forEach(cell => tr.append(text("td", "", cell)));
    el.append(tr);
  }
  return el;
}
function totals(label, group) {
  return Object.entries(group || {}).map(([provider, t]) => [
    label + " · " + (PROVIDERS[provider] || provider), num(t.calls),
    num(t.input + t.cache_read + t.cache_write), num(t.output), usd(t.cost)
  ]);
}
/* ---------- Consumo ---------- */
const compact = new Intl.NumberFormat("es", { notation: "compact", maximumFractionDigits: 1 });
const tokensOf = t => (t ? t.input + t.cache_read + t.cache_write + t.output : 0);
function niceMax(value) {
  if (value <= 0) return 1;
  const power = Math.pow(10, Math.floor(Math.log10(value)));
  return [1, 2, 2.5, 5, 10].map(f => f * power).find(v => v >= value);
}
function dayLabel(iso, opts) { const [y, m, d] = iso.split("-").map(Number); return new Date(y, m - 1, d).toLocaleDateString("es", opts); }
function renderChart(data) {
  const box = $("chart-box"); box.replaceChildren();
  const byDay = {};
  for (const r of data.daily || []) (byDay[r.day] = byDay[r.day] || {})[r.provider] = r;
  const days = (data.days || []).map(day => {
    const c = byDay[day] && byDay[day].claude, l = byDay[day] && byDay[day].local;
    return { day, claude: c ? c.input + c.output : 0, local: l ? l.input + l.output : 0, cost: c ? c.cost : 0 };
  });
  const top = niceMax(Math.max(0, ...days.map(d => d.claude + d.local)));
  const chart = text("div", "chart", "");
  chart.setAttribute("role", "img");
  chart.setAttribute("aria-label", "Tokens por día de los últimos 14 días, Claude y modelo local");
  for (const f of [0.5, 1]) {
    const g = text("div", "gridline", ""); g.style.bottom = (f * 100) + "%";
    g.append(text("span", "", compact.format(top * f))); chart.append(g);
  }
  const tip = text("div", "tooltip", "");
  for (const d of days) {
    const col = text("div", "col", ""); col.tabIndex = 0;
    const title = dayLabel(d.day, { weekday: "long", day: "numeric", month: "long" });
    col.setAttribute("aria-label", title + ": Claude " + num(d.claude) + " tokens, modelo local " + num(d.local) + " tokens");
    const stack = text("div", "stack", "");
    for (const [key, value] of [["local", d.local], ["claude", d.claude]]) {
      if (!value) continue;
      const seg = text("div", "seg " + key, "");
      seg.style.height = Math.max(2, Math.round(196 * value / top)) + "px";
      stack.append(seg);
    }
    col.append(stack);
    const show = () => {
      tip.replaceChildren(text("b", "", title));
      for (const [key, label, value] of [["claude", "Claude", d.claude], ["local", "Modelo local", d.local]]) {
        const row = document.createElement("div"); const sw = document.createElement("i");
        sw.style.background = "var(--s-" + key + ")"; row.append(sw, document.createTextNode(label + ": " + num(value) + " tokens"));
        tip.append(row);
      }
      if (d.cost) tip.append(text("div", "", "Costo equivalente: " + usd(d.cost)));
      tip.style.display = "block";
      const boxRect = box.getBoundingClientRect(), colRect = col.getBoundingClientRect();
      const left = colRect.left - boxRect.left + colRect.width / 2 - tip.offsetWidth / 2;
      tip.style.left = Math.max(0, Math.min(left, box.clientWidth - tip.offsetWidth)) + "px";
      tip.style.top = "0px";
    };
    col.addEventListener("mouseenter", show); col.addEventListener("focus", show);
    col.addEventListener("mouseleave", () => tip.style.display = "none"); col.addEventListener("blur", () => tip.style.display = "none");
    chart.append(col);
  }
  const labels = text("div", "xlabels", "");
  days.forEach((d, i) => {
    const showMonth = i === 0 || d.day.endsWith("-01");
    labels.append(text("span", "", dayLabel(d.day, showMonth ? { day: "numeric", month: "short" } : { day: "numeric" })));
  });
  box.append(chart, labels, tip);
  $("daily-table").replaceChildren(table(["Día", "Claude", "Modelo local", "Costo equiv."],
    days.slice().reverse().map(d => [dayLabel(d.day, { weekday: "short", day: "numeric", month: "short" }), num(d.claude), num(d.local), usd(d.cost)])));
}
const PURPOSES = { "conversación": "Conversación", "búsqueda": "Resumir búsquedas", "interpretar": "Entender órdenes", "check": "Verificación", "prueba": "Prueba" };
function renderUsage(data) {
  const today = data.today || {}, month = data.month || {};
  $("u-claude-today").textContent = compact.format(tokensOf(today.claude));
  $("u-claude-today-sub").textContent = num(today.claude ? today.claude.calls : 0) + " llamadas";
  $("u-claude-month").textContent = compact.format(tokensOf(month.claude));
  $("u-claude-month-sub").textContent = num(month.claude ? month.claude.calls : 0) + " llamadas";
  $("u-cost").textContent = usd(month.claude ? month.claude.cost : 0).replace(/(\\.\\d\\d)\\d\\d$/, "$1");
  $("u-local-month").textContent = compact.format(tokensOf(month.local));
  $("u-local-month-sub").textContent = num(month.local ? month.local.calls : 0) + " llamadas";
  renderChart(data);
  $("by-purpose").replaceChildren(table(["Uso", "Modelo", "Llamadas", "Entrada", "Salida", "Costo equiv."],
    (data.by_purpose || []).map(r => [PURPOSES[r.purpose] || r.purpose, PROVIDERS[r.provider] || r.provider, num(r.calls), num(r.input), num(r.output), usd(r.cost)])));
  $("recent-calls").replaceChildren(table(["Hora", "Uso", "Modelo", "Entrada", "Salida"], (data.recent || []).map(r => [
    new Date(r.ts * 1000).toLocaleString("es", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }),
    PURPOSES[r.purpose] || r.purpose, PROVIDERS[r.provider] || r.provider,
    num(r.input_tokens + r.cache_read_tokens + r.cache_write_tokens), num(r.output_tokens)
  ])));
}
let usageSerialized = "";
async function loadUsage() {
  try {
    const data = await (await fetch("/usage", { cache: "no-store" })).json();
    const serialized = JSON.stringify(data);
    if (serialized !== usageSerialized) { usageSerialized = serialized; renderUsage(data); }
  } catch { $("offline").style.display = "block"; }
}

/* ---------- Historial ---------- */
const plainText = s => s.normalize("NFD").replace(/[\\u0300-\\u036f]/g, "").toLowerCase();
let historyData = null;
function renderHistory() {
  if (!historyData) return;
  const query = plainText($("search").value.trim());
  const box = $("messages"); box.replaceChildren();
  const messages = historyData.messages.filter(m => !query || plainText(m.text).includes(query));
  if (!messages.length) box.append(text("div", "empty", query ? "Nada coincide con tu búsqueda." : "Todavía no hay conversaciones."));
  let lastDay = "";
  for (const m of messages) {
    const when = new Date(m.ts * 1000);
    const day = when.toLocaleDateString("es", { weekday: "long", day: "numeric", month: "long" });
    if (day !== lastDay) { box.append(text("div", "day", day)); lastDay = day; }
    const bubble = text("div", "msg " + (m.role === "user" ? "user" : "hermes"), m.text);
    bubble.append(text("small", "", (m.role === "user" ? "Tú" : "Hermes") + " · " + when.toLocaleTimeString("es", { hour: "2-digit", minute: "2-digit" })));
    box.append(bubble);
  }
  renderEvents(historyData.voice || []);
}
let historySerialized = "";
async function loadHistory() {
  try {
    const data = await (await fetch("/history", { cache: "no-store" })).json();
    const serialized = JSON.stringify(data);
    if (serialized !== historySerialized) {
      const atBottom = window.innerHeight + window.scrollY >= document.body.scrollHeight - 40;
      historySerialized = serialized; historyData = data; renderHistory();
      if (atBottom) window.scrollTo(0, document.body.scrollHeight);
    }
  } catch { $("offline").style.display = "block"; }
}
$("search").addEventListener("input", renderHistory);
window.addEventListener("resize", () => document.querySelectorAll(".tooltip").forEach(t => t.style.display = "none"));
setInterval(() => { if (currentView() === "consumo") loadUsage(); if (currentView() === "historial") loadHistory(); }, 5000);
/* ---------- Hablarle desde la página ---------- */
// Tocar para empezar, tocar otra vez para enviar. El audio viaja a Hermes, que lo transcribe y responde.
const MAX_TALK_MS = 60000;
const TALK_LABELS = { lista: "Hablar con Hermes", grabando: "Terminar y enviar", pensando: "Hermes está pensando", hablando: "Callar a Hermes" };
const talk = { recorder: null, stream: null, chunks: [], timer: 0, startedAt: 0, ctx: null, playing: null, done: null };
function talkState(state) { const b = $("talk-btn"); b.dataset.state = state; b.setAttribute("aria-label", TALK_LABELS[state]); }
function talkShow(heard, said, isError) {
  $("talk-heard").textContent = heard ? "Entendí: «" + heard + "»" : "";
  $("talk-said").textContent = said;
  $("talk-panel").classList.toggle("error", !!isError);
  $("talk-panel").hidden = false;
}
function talkMime() {
  for (const m of ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"]) if (MediaRecorder.isTypeSupported(m)) return m;
  return "";
}
function talkSilence() {
  const done = talk.done;
  if (talk.playing) { try { talk.playing.onended = null; talk.playing.stop(); } catch {} }
  talk.playing = null; talk.done = null;
  if (done) done();
}
async function talkStart() {
  if (!navigator.mediaDevices || !window.MediaRecorder) return talkShow("", "Este navegador no permite grabar desde la página.", true);
  // El audio se desbloquea dentro del toque: si no, el teléfono no deja sonar la respuesta después.
  try { talk.ctx = talk.ctx || new (window.AudioContext || window.webkitAudioContext)(); talk.ctx.resume(); } catch {}
  try {
    talk.stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, channelCount: 1 } });
  } catch {
    return talkShow("", "No tengo permiso para usar el micrófono. Actívalo para esta página en los ajustes del navegador.", true);
  }
  const mime = talkMime();
  talk.chunks = [];
  talk.recorder = new MediaRecorder(talk.stream, mime ? { mimeType: mime, audioBitsPerSecond: 32000 } : {});
  talk.recorder.ondataavailable = e => { if (e.data.size) talk.chunks.push(e.data); };
  talk.recorder.onstop = talkSend;
  talk.recorder.start();
  talk.startedAt = Date.now();
  $("talk-panel").hidden = true;
  talkState("grabando");
  talk.timer = setTimeout(talkStop, MAX_TALK_MS);
}
function talkStop() {
  clearTimeout(talk.timer);
  if (talk.recorder && talk.recorder.state !== "inactive") talk.recorder.stop();
  if (talk.stream) { talk.stream.getTracks().forEach(t => t.stop()); talk.stream = null; }  // Cierra el micrófono.
}
async function talkPlay(base64) {
  if (!talk.ctx) return;
  const raw = atob(base64), bytes = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
  const buffer = await talk.ctx.decodeAudioData(bytes.buffer);
  await new Promise(done => {
    const source = talk.ctx.createBufferSource();
    source.buffer = buffer; source.connect(talk.ctx.destination);
    source.onended = () => { talk.playing = null; talk.done = null; done(); };
    talk.playing = source; talk.done = done;
    talkState("hablando");
    source.start();
  });
}
async function talkSend() {
  const type = ((talk.recorder && talk.recorder.mimeType) || "audio/webm").split(";")[0];
  const blob = new Blob(talk.chunks, { type });
  const length = Date.now() - talk.startedAt;
  talk.recorder = null; talk.chunks = [];
  if (!blob.size || length < 500) { talkState("lista"); return talkShow("", "Toca el botón, di la orden y vuelve a tocarlo para enviarla.", true); }
  talkState("pensando");
  try {
    const res = await fetch("/speak", { method: "POST", cache: "no-store", headers: { "Content-Type": type, "X-Hermes-Token": TOKEN }, body: blob });
    if (res.status === 401) { location.href = "/login"; return; }
    if (res.status === 403) { location.reload(); return; }
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || "No se pudo atender la orden.");
    talkShow(data.heard, data.reply);
    if (currentView() === "tareas") loadTasks(true);
    if (data.audio) await talkPlay(data.audio).catch(() => {});
  } catch (e) {
    talkShow("", e instanceof TypeError ? "No pude comunicarme con Hermes. Revisa tu conexión." : e.message, true);
  }
  talkState("lista");
}
$("talk-btn").addEventListener("click", () => {
  const state = $("talk-btn").dataset.state;
  if (state === "lista") talkStart();
  else if (state === "grabando") talkStop();
  else if (state === "hablando") talkSilence();
});
$("talk-close").addEventListener("click", () => { $("talk-panel").hidden = true; });
$("say-form").addEventListener("submit", async event => {
  event.preventDefault();
  const order = $("say-input").value.trim();
  if (!order) return;
  $("say-send").disabled = true;
  try {
    const data = await send("/tasks", { action: "say", text: order });
    $("say-input").value = "";
    talkShow("", data.message);
    loadTasks(true);
  } catch (e) { talkShow("", e.message, true); }
  $("say-send").disabled = false;
});
/* ---------- Apuntes ---------- */
const AP_MONTHS = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"];
AP_MONTHS.forEach((name, i) => { const o = document.createElement("option"); o.value = i + 1; o.textContent = name; $("ap-date-month").appendChild(o); });
let apuntesSerialized = "";
async function apunte(body, quiet) {
  try {
    const data = await send("/extras", body);
    if (!quiet) toast(data.message);
    await loadApuntes(true);
    return true;
  } catch (e) { toast(e.message); return false; }
}
function apRow(main, detail, check, onRemove, removeLabel) {
  const row = text("div", "ap-row", "");
  if (check) row.appendChild(check);
  const body = text("div", "grow", main);
  if (detail) body.appendChild(text("small", "", detail));
  row.appendChild(body);
  if (onRemove) { const x = text("button", "ap-x", "✕"); x.type = "button"; x.setAttribute("aria-label", removeLabel); x.onclick = onRemove; row.appendChild(x); }
  return row;
}
function apCheck(on, label, onClick) {
  const b = text("button", "ap-check" + (on ? " on" : ""), ""); b.type = "button"; b.setAttribute("aria-label", label); b.onclick = onClick; return b;
}
function apFill(id, rows, empty) {
  const box = $(id); box.textContent = "";
  if (!rows.length) box.appendChild(text("div", "ap-empty", empty));
  rows.forEach(r => box.appendChild(r));
}
// Cada lista es un cajón: se abre y se cierra, y dentro se agregan y se quitan sus elementos.
let closedLists = new Set();
try { closedLists = new Set(JSON.parse(localStorage.getItem("hermes-lists-closed") || "[]")); } catch {}
let focusList = null;
let editingItem = null;  // El elemento que se está corrigiendo, y lo escrito hasta ahora.
let editingText = "";
function listItemRow(item, lists) {
  if (editingItem !== item.id) {
    // El círculo marca y desmarca; el elemento marcado se queda en la lista, tachado, hasta que lo quites.
    const check = apCheck(item.done, (item.done ? "Desmarcar " : "Marcar ") + item.text, () => apunte({ action: "list_check", id: item.id, done: !item.done }, true));
    const row = text("div", "ap-row" + (item.done ? " done" : ""), "");
    const name = text("button", "grow ap-item", item.text); name.type = "button";
    name.setAttribute("aria-label", "Editar " + item.text); name.title = "Tocar para editar";
    name.onclick = () => { editingItem = item.id; editingText = item.text; renderLists(lists); };
    const remove = text("button", "ap-x", "✕"); remove.type = "button"; remove.setAttribute("aria-label", "Quitar " + item.text);
    remove.onclick = () => apunte({ action: "list_remove", id: item.id }, true);
    row.append(check, name, remove);
    return row;
  }
  const row = text("form", "ap-row ap-editing", ""); row.autocomplete = "off";
  const input = document.createElement("input");
  input.maxLength = 100; input.value = editingText; input.setAttribute("aria-label", "Nuevo texto del elemento"); input.enterKeyHint = "done";
  input.oninput = () => { editingText = input.value; };
  const stop = () => { editingItem = null; editingText = ""; };
  input.onkeydown = event => { if (event.key === "Escape") { stop(); renderLists(lists); } };
  const save = text("button", "primary", "Guardar"); save.type = "submit";
  const cancel = text("button", "ap-x", "✕"); cancel.type = "button"; cancel.setAttribute("aria-label", "Cancelar la edición");
  cancel.onclick = () => { stop(); renderLists(lists); };
  row.onsubmit = async event => {
    event.preventDefault();
    const value = input.value.trim();
    if (!value) { input.focus(); return; }
    if (value === item.text) { stop(); renderLists(lists); return; }
    save.disabled = true;
    try {
      await send("/extras", { action: "list_edit", id: item.id, text: value });
      stop();
      await loadApuntes(true);
    } catch (e) { toast(e.message); save.disabled = false; }
  };
  row.append(input, save, cancel);
  setTimeout(() => { if (document.activeElement !== input && editingItem === item.id) { input.focus(); input.select(); } }, 0);
  return row;
}
function renderLists(lists) {
  const box = $("ap-lists");
  const typed = {};  // Lo que estabas escribiendo en cada cajón no se pierde al refrescar.
  box.querySelectorAll("input[data-list]").forEach(input => { if (input.value) typed[input.dataset.list] = input.value; });
  box.textContent = "";
  if (!lists.length) box.appendChild(text("div", "ap-empty card", "Todavía no tienes listas. Crea la primera aquí arriba."));
  for (const list of lists) {
    const closed = closedLists.has(list.name);
    const drawer = text("div", "ap-drawer" + (closed ? " closed" : ""), "");
    const head = text("button", "ap-drawer-head", ""); head.type = "button";
    head.setAttribute("aria-expanded", String(!closed));
    head.append(text("span", "name", list.name), text("em", "", (list.items.length === 1 ? "1 elemento" : list.items.length + " elementos") + (list.items.some(i => i.done) ? " · " + list.items.filter(i => i.done).length + " ✓" : "")), text("span", "chev", ""));
    head.onclick = () => {
      if (closedLists.has(list.name)) closedLists.delete(list.name); else closedLists.add(list.name);
      try { localStorage.setItem("hermes-lists-closed", JSON.stringify([...closedLists])); } catch {}
      renderLists(lists);
    };
    drawer.appendChild(head);
    if (!closed) {
      const body = text("div", "ap-drawer-body", "");
      if (!list.items.length) body.appendChild(text("div", "ap-empty", "Esta lista está vacía."));
      for (const item of list.items) body.appendChild(listItemRow(item, lists));
      const form = text("form", "ap-form ap-add", ""); form.autocomplete = "off";
      const input = document.createElement("input");
      input.maxLength = 100; input.placeholder = "Agregar a " + list.name + "…"; input.dataset.list = list.name;
      input.setAttribute("aria-label", "Agregar a la lista de " + list.name); input.enterKeyHint = "done";
      if (typed[list.name]) input.value = typed[list.name];
      const add = text("button", "primary", "Agregar"); add.type = "submit";
      form.append(input, add);
      form.onsubmit = async event => {
        event.preventDefault();
        const item = input.value.trim();
        if (!item) return;
        focusList = list.name; input.value = "";
        if (!await apunte({ action: "list_add", list: list.name, text: item }, true)) { input.value = item; }
      };
      const foot = text("div", "ap-drawer-foot", "");
      const clear = text("button", "ap-link", "Vaciar"); clear.type = "button"; clear.disabled = !list.items.length;
      clear.onclick = async () => { if (await ask("¿Quitar todos los elementos de la lista de " + list.name + "?", "Vaciar")) apunte({ action: "list_clear", list: list.name }); };
      const marked = list.items.filter(item => item.done).length;
      const sweep = text("button", "ap-link", "Quitar marcados"); sweep.type = "button"; sweep.hidden = !marked;
      sweep.onclick = async () => { if (await ask("¿Quitar " + (marked === 1 ? "el elemento marcado" : "los " + marked + " elementos marcados") + " de la lista de " + list.name + "?", "Quitar")) apunte({ action: "list_clear_done", list: list.name }); };
      const remove = text("button", "ap-link danger-link", "Eliminar lista"); remove.type = "button";
      remove.onclick = async () => { if (await ask("¿Eliminar la lista de " + list.name + (list.items.length ? " con todo lo que tiene?" : "?"), "Eliminar")) apunte({ action: "list_delete", list: list.name }); };
      foot.append(clear, sweep, remove);
      body.append(form, foot);
      drawer.appendChild(body);
    }
    box.appendChild(drawer);
  }
  if (focusList) {
    const target = [...box.querySelectorAll("input[data-list]")].find(input => input.dataset.list === focusList);
    focusList = null;
    if (target) target.focus();
  }
}
let lastApuntes = null;
let editingNote = null;  // La nota que se está corrigiendo, y lo escrito hasta ahora.
let editingNoteText = "";
function noteRow(n) {
  const redraw = () => { if (lastApuntes) renderApuntes(lastApuntes); };
  if (editingNote !== n.id) {
    const row = text("div", "ap-row", "");
    const body = text("button", "grow ap-item", n.text); body.type = "button";
    body.setAttribute("aria-label", "Editar la nota: " + n.text); body.title = "Tocar para editar";
    body.onclick = () => { editingNote = n.id; editingNoteText = n.text; redraw(); };
    const remove = text("button", "ap-x", "✕"); remove.type = "button"; remove.setAttribute("aria-label", "Borrar la nota");
    remove.onclick = async () => { if (await ask("¿Borrar esta nota? «" + n.text + "»")) apunte({ action: "note_delete", id: n.id }); };
    row.append(body, remove);
    return row;
  }
  const row = text("form", "ap-row ap-editing ap-editing-note", ""); row.autocomplete = "off";
  const input = document.createElement("textarea");
  input.maxLength = 500; input.rows = 3; input.value = editingNoteText; input.setAttribute("aria-label", "Nuevo texto de la nota"); input.enterKeyHint = "done";
  input.oninput = () => { editingNoteText = input.value; };
  const stop = () => { editingNote = null; editingNoteText = ""; };
  const save = text("button", "primary", "Guardar"); save.type = "submit";
  const cancel = text("button", "ap-x", "✕"); cancel.type = "button"; cancel.setAttribute("aria-label", "Cancelar la edición");
  cancel.onclick = () => { stop(); redraw(); };
  input.onkeydown = event => {
    if (event.key === "Escape") { stop(); redraw(); }
    else if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); row.requestSubmit(); }
  };
  row.onsubmit = async event => {
    event.preventDefault();
    const value = input.value.trim();
    if (!value) { input.focus(); return; }
    if (value === n.text) { stop(); redraw(); return; }
    save.disabled = true;
    try {
      toast((await send("/extras", { action: "note_edit", id: n.id, text: value })).message);
      stop();
      await loadApuntes(true);
    } catch (e) { toast(e.message); save.disabled = false; }
  };
  const buttons = text("div", "ap-edit-buttons", "");
  buttons.append(save, cancel);
  row.append(input, buttons);
  setTimeout(() => { if (document.activeElement !== input && editingNote === n.id) { input.focus(); input.setSelectionRange(input.value.length, input.value.length); } }, 0);
  return row;
}
const dateCal = { year: new Date().getFullYear(), month: new Date().getMonth(), picked: null };
function renderDatesCalendar(dates) {
  const box = $("ap-dates-cal"); box.textContent = "";
  const marks = {}, picked = [];
  for (const x of dates) {
    if (x.month !== dateCal.month + 1) continue;  // Se repiten cada año: basta con que coincida el mes.
    const birthday = x.label.startsWith("cumpleaños de ");
    (marks[x.day] = marks[x.day] || []).push({ label: birthday ? "🎂 " + x.label.slice(14) : "💍 aniversario", cls: "" });
    if (x.day === dateCal.picked) picked.push(x.label);
  }
  box.append(monthGrid(dateCal, marks, () => {
    if (dateCal.picked) { $("ap-date-day").value = dateCal.picked; $("ap-date-month").value = dateCal.month + 1; }
    renderDatesCalendar(dates);
  }));
  if (dateCal.picked) {
    const line = text("div", "cal-picked", "");
    line.append(text("b", "", dateCal.picked + " de " + CAL_MONTHS[dateCal.month] + ": "),
      text("span", "", picked.length ? picked.join(", ") + "." : "nada anotado. Ya puse el día en el formulario de abajo; escribe de quién es y guarda."));
    box.append(line);
  }
}
let editingWaiting = null;  // El seguimiento que se está corrigiendo, con su texto y su día.
let editingWaitingText = "", editingWaitingDate = "";
function isoDay(ts) { const d = new Date(ts * 1000); return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0"); }
function waitingRow(w) {
  const redraw = () => { if (lastApuntes) renderApuntes(lastApuntes); };
  if (editingWaiting !== w.id) {
    const row = text("div", "ap-row", "");
    const check = apCheck(false, "Ya llegó: " + w.title, async () => {
      try { toast((await send("/tasks", { action: "done", id: w.id })).message, w.id); loadApuntes(true); } catch (e) { toast(e.message); }
    });
    const body = text("button", "grow ap-item", w.title); body.type = "button";
    body.setAttribute("aria-label", "Editar el seguimiento: " + w.title); body.title = "Tocar para editar";
    if (w.due_at) body.appendChild(text("small", "", "Te pregunto el " + new Date(w.due_at * 1000).toLocaleDateString("es", { weekday: "long", day: "numeric", month: "short" })));
    body.onclick = () => { editingWaiting = w.id; editingWaitingText = w.title; editingWaitingDate = w.due_at ? isoDay(w.due_at) : ""; redraw(); };
    const remove = text("button", "ap-x", "✕"); remove.type = "button"; remove.setAttribute("aria-label", "Borrar el seguimiento");
    remove.onclick = async () => { if (await ask("¿Borrar el seguimiento «" + w.title + "»?")) apunte({ action: "waiting_delete", id: w.id }); };
    row.append(check, body, remove);
    return row;
  }
  const row = text("form", "ap-row ap-editing ap-editing-wait", ""); row.autocomplete = "off";
  const input = document.createElement("input");
  input.maxLength = 200; input.value = editingWaitingText; input.setAttribute("aria-label", "Texto del seguimiento"); input.enterKeyHint = "done";
  input.oninput = () => { editingWaitingText = input.value; };
  const date = document.createElement("input");
  date.type = "date"; date.value = editingWaitingDate; date.setAttribute("aria-label", "Día en que Hermes te pregunta"); date.title = "Día en que Hermes te pregunta";
  date.oninput = () => { editingWaitingDate = date.value; };
  const stop = () => { editingWaiting = null; editingWaitingText = ""; editingWaitingDate = ""; };
  const onKey = event => { if (event.key === "Escape") { stop(); redraw(); } };
  input.onkeydown = onKey; date.onkeydown = onKey;
  const save = text("button", "primary", "Guardar"); save.type = "submit";
  const cancel = text("button", "ap-x", "✕"); cancel.type = "button"; cancel.setAttribute("aria-label", "Cancelar la edición");
  cancel.onclick = () => { stop(); redraw(); };
  row.onsubmit = async event => {
    event.preventDefault();
    const value = input.value.trim();
    if (!value) { input.focus(); return; }
    const body = { action: "waiting_edit", id: w.id, text: value };
    if (date.value) body.date = date.value;
    save.disabled = true;
    try {
      toast((await send("/extras", body)).message);
      stop();
      await loadApuntes(true);
    } catch (e) { toast(e.message); save.disabled = false; }
  };
  row.append(input, date, save, cancel);
  setTimeout(() => { if (editingWaiting === w.id && document.activeElement !== input && document.activeElement !== date) input.focus(); }, 0);
  return row;
}
let editingHabit = null;  // El hábito que se está corrigiendo, con su nombre y su hora.
let editingHabitTitle = "", editingHabitTime = "";
const HB_DAYS = ["dom", "lun", "mar", "mié", "jue", "vie", "sáb"];
const daysText = n => n === 1 ? "1 día" : n + " días";
function habitCard(h) {
  const redraw = () => { if (lastApuntes) renderApuntes(lastApuntes); };
  const card = text("div", "hb-card" + (h.done ? " done" : ""), "");
  const top = text("div", "hb-top", "");
  const check = text("button", "hb-check" + (h.done ? " on" : ""), ""); check.type = "button";
  check.setAttribute("aria-pressed", String(h.done));
  check.setAttribute("aria-label", (h.done ? "Desmarcar hoy: " : "Marcar hecho hoy: ") + h.title);
  check.title = h.done ? "Hecho hoy · toca para desmarcar" : "Marcar como hecho hoy";
  check.onclick = () => apunte({ action: h.done ? "habit_undo" : "habit_done", id: h.id }, true);
  const name = text("div", "hb-name", "");
  if (editingHabit === h.id) {
    const form = text("form", "hb-edit", ""); form.autocomplete = "off";
    const title = document.createElement("input");
    title.maxLength = 100; title.value = editingHabitTitle; title.setAttribute("aria-label", "Nombre del hábito");
    title.oninput = () => { editingHabitTitle = title.value; };
    const time = document.createElement("input");
    time.type = "time"; time.value = editingHabitTime; time.setAttribute("aria-label", "Hora del recordatorio (vacía para no recordar)");
    time.oninput = () => { editingHabitTime = time.value; };
    const stop = () => { editingHabit = null; editingHabitTitle = editingHabitTime = ""; };
    const save = text("button", "primary", "Guardar"); save.type = "submit";
    const cancel = text("button", "ap-x", "✕"); cancel.type = "button"; cancel.setAttribute("aria-label", "Cancelar la edición");
    cancel.onclick = () => { stop(); redraw(); };
    const onKey = event => { if (event.key === "Escape") { stop(); redraw(); } };
    title.onkeydown = onKey; time.onkeydown = onKey;
    form.onsubmit = async event => {
      event.preventDefault();
      if (!title.value.trim()) { title.focus(); return; }
      save.disabled = true;
      try {
        toast((await send("/extras", { action: "habit_edit", id: h.id, title: title.value.trim(), time: time.value || null })).message);
        stop();
        await loadApuntes(true);
      } catch (e) { toast(e.message); save.disabled = false; }
    };
    form.append(title, time, save, cancel);
    name.append(form);
    setTimeout(() => { if (editingHabit === h.id && !form.contains(document.activeElement)) title.focus(); }, 0);
  } else {
    const label = text("button", "ap-item", h.title); label.type = "button";
    label.setAttribute("aria-label", "Editar el hábito " + h.title); label.title = "Tocar para editar";
    label.onclick = () => { editingHabit = h.id; editingHabitTitle = h.title; editingHabitTime = h.remind_at || ""; redraw(); };
    name.append(label, text("small", "", h.remind_at ? "Te lo recuerdo a las " + h.remind_at : "Sin recordatorio"));
  }
  top.append(check, name);
  const stats = text("div", "hb-stats", "");
  const stat = (cls, value, label) => { const s = text("span", cls, ""); s.append(text("b", "", value), document.createTextNode(" " + label)); return s; };
  stats.append(stat("fire", (h.streak ? "🔥 " : "") + daysText(h.streak), h.streak === 1 ? "seguido" : "seguidos"), stat("", daysText(h.best), "de récord"), stat("", String(h.total), "en total"));
  const week = text("div", "hb-week", "");
  h.week.forEach((d, i) => {
    const [y, m, day] = d.day.split("-").map(Number);
    const label = i === h.week.length - 1 ? "hoy" : HB_DAYS[new Date(y, m - 1, day).getDay()];
    const cell = text("div", "hb-day" + (d.done ? " on" : "") + (i === h.week.length - 1 ? " today" : ""), "");
    cell.title = day + "/" + m + (d.done ? ": hecho" : ": sin marcar");
    cell.append(text("i", "", ""), text("span", "", label));
    week.append(cell);
  });
  const foot = text("div", "hb-foot", "");
  const remove = text("button", "ap-link danger-link", "Quitar hábito"); remove.type = "button";
  remove.onclick = async () => { if (await ask("¿Quitar el hábito «" + h.title + "»? Se pierde también su historial y su racha.", "Quitar")) apunte({ action: "habit_delete", id: h.id }); };
  foot.append(remove);
  card.append(top, stats, week, foot);
  return card;
}
function renderHabits(habits) {
  const box = $("ap-habits"); box.textContent = "";
  if (!habits.length) box.appendChild(text("div", "ap-empty card", "Todavía no tienes hábitos. Crea el primero aquí arriba, con hora si quieres que te lo recuerde."));
  habits.forEach(h => box.appendChild(habitCard(h)));
  const summary = $("ap-habits-count"); summary.textContent = "";
  if (habits.length) {
    const done = habits.filter(h => h.done).length;
    summary.append(text("span", "", "Hoy llevas "), text("b", "", done + " de " + habits.length),
      text("span", "", done === habits.length ? ". ¡Completaste todos!" : "."));
    const bar = text("div", "hb-bar", ""); const fill = document.createElement("i");
    fill.style.width = Math.round(100 * done / habits.length) + "%"; bar.append(fill); summary.append(bar);
  }
}
let editingDate = null;  // La fecha que se está corrigiendo y lo escrito hasta ahora.
let editingDateFields = null;
const DT_DAYS = ["domingo", "lunes", "martes", "miércoles", "jueves", "viernes", "sábado"];
const capital = s => s.charAt(0).toUpperCase() + s.slice(1);
function dateTitle(x) { return (x.kind === "cumpleaños" ? "🎂 " : "💍 ") + capital(x.label); }
function dateWhen(x) {
  const [y, m, d] = x.next.split("-").map(Number);
  const parts = [x.in_days === 0 ? "¡Hoy! 🎉" : x.in_days === 1 ? "Mañana" : "En " + x.in_days + " días"];
  if (x.turns) parts.push(x.kind === "cumpleaños" ? "cumple " + x.turns + (x.turns === 1 ? " año" : " años") : (x.turns === 1 ? "1 año" : x.turns + " años"));
  if (x.in_days > 1) parts.push(DT_DAYS[new Date(y, m - 1, d).getDay()]);
  return parts;
}
// Campos de una fecha (tipo, de quién, día, mes y año), para el formulario de corregir.
function dateFields(values, onInput) {
  const kind = document.createElement("select"); kind.setAttribute("aria-label", "Tipo");
  [["cumpleaños", "Cumpleaños"], ["aniversario", "Aniversario"]].forEach(([v, t]) => { const o = document.createElement("option"); o.value = v; o.textContent = t; kind.appendChild(o); });
  kind.value = values.kind;
  const name = document.createElement("input"); name.maxLength = 80; name.value = values.name; name.placeholder = "De quién"; name.setAttribute("aria-label", "De quién");
  const day = document.createElement("input"); day.type = "number"; day.min = 1; day.max = 31; day.className = "narrow"; day.value = values.day; day.setAttribute("aria-label", "Día");
  const month = document.createElement("select"); month.setAttribute("aria-label", "Mes");
  AP_MONTHS.forEach((m, i) => { const o = document.createElement("option"); o.value = i + 1; o.textContent = m; month.appendChild(o); });
  month.value = values.month;
  const year = document.createElement("input"); year.type = "number"; year.min = 1900; year.max = new Date().getFullYear(); year.className = "narrow";
  year.value = values.year || ""; year.placeholder = "Año"; year.setAttribute("aria-label", "Año (opcional)"); year.title = "Año (opcional): para saber cuántos cumple";
  const read = () => ({ kind: kind.value, name: name.value, day: day.value, month: month.value, year: year.value });
  [kind, name, day, month, year].forEach(el => { el.oninput = () => onInput(read()); });
  return { els: [kind, name, day, month, year], first: name, read };
}
function datePayload(v) {
  const body = { kind: v.kind, name: v.name.trim(), day: parseInt(v.day, 10), month: parseInt(v.month, 10) };
  const year = parseInt(v.year, 10);
  body.year = year || null;
  return body;
}
function dateRow(x) {
  const redraw = () => { if (lastApuntes) renderApuntes(lastApuntes); };
  if (editingDate === x.id) {
    const form = text("form", "ap-form dt-edit", ""); form.autocomplete = "off";
    const fields = dateFields(editingDateFields, v => { editingDateFields = v; });
    const stop = () => { editingDate = null; editingDateFields = null; };
    const save = text("button", "primary", "Guardar"); save.type = "submit";
    const cancel = text("button", "ap-x", "✕"); cancel.type = "button"; cancel.setAttribute("aria-label", "Cancelar la edición");
    cancel.onclick = () => { stop(); redraw(); };
    form.onkeydown = event => { if (event.key === "Escape") { stop(); redraw(); } };
    form.onsubmit = async event => {
      event.preventDefault();
      const body = datePayload(fields.read());
      if (!body.day) { fields.els[2].focus(); return; }
      save.disabled = true;
      try {
        toast((await send("/extras", Object.assign({ action: "date_edit", id: x.id }, body))).message);
        stop();
        await loadApuntes(true);
      } catch (e) { toast(e.message); save.disabled = false; }
    };
    form.append(...fields.els, save, cancel);
    setTimeout(() => { if (editingDate === x.id && !form.contains(document.activeElement)) fields.first.focus(); }, 0);
    return form;
  }
  const row = text("div", "dt-row" + (x.in_days === 0 ? " today" : x.in_days <= 7 ? " soon" : ""), "");
  const badge = text("div", "dt-badge", "");
  badge.append(text("b", "", String(Number(x.next.slice(8)))), text("span", "", AP_MONTHS[Number(x.next.slice(5, 7)) - 1].slice(0, 3)));
  const body = text("div", "dt-body", "");
  const title = text("button", "ap-item", dateTitle(x)); title.type = "button";
  title.title = "Tocar para corregir"; title.setAttribute("aria-label", "Corregir: " + x.label);
  title.onclick = () => { editingDate = x.id; editingDateFields = { kind: x.kind, name: x.name, day: x.day, month: x.month, year: x.year }; redraw(); };
  const when = dateWhen(x);
  const small = text("small", "", "");
  small.append(text("span", "when", when[0]), document.createTextNode(when.length > 1 ? " · " + when.slice(1).join(" · ") : ""));
  body.append(title, small);
  const remove = text("button", "ap-x", "✕"); remove.type = "button"; remove.setAttribute("aria-label", "Borrar: " + x.label);
  remove.onclick = async () => { if (await ask("¿Borrar el " + x.label + "? Hermes dejará de avisarte.", "Borrar")) apunte({ action: "date_delete", id: x.id }); };
  row.append(badge, body, remove);
  return row;
}
// Las fechas en el orden en que llegan, agrupadas por mes, empezando por el actual.
function renderDates(dates) {
  const box = $("ap-dates"); box.textContent = "";
  if (!dates.length) { box.appendChild(text("div", "ap-empty card", "Todavía no hay fechas. Anota cumpleaños y aniversarios aquí arriba y Hermes te avisa un día antes y ese día.")); return; }
  const thisYear = new Date().getFullYear();
  let group = null, key = "";
  for (const x of dates) {
    const [y, m] = x.next.split("-").map(Number);
    if (y + "-" + m !== key) {
      key = y + "-" + m;
      group = text("div", "dt-group", "");
      group.appendChild(text("h4", "", capital(AP_MONTHS[m - 1]) + (y !== thisYear ? " " + y : "")));
      box.appendChild(group);
    }
    group.appendChild(dateRow(x));
  }
}
function renderApuntes(d) {
  lastApuntes = d;
  renderLists(d.lists);
  renderHabits(d.habits);
  apFill("ap-notes", d.notes.map(noteRow), "Todavía no hay notas.");
  $("ap-notes-count").textContent = d.notes.length || "";
  renderDatesCalendar(d.dates);
  renderDates(d.dates);
  $("ap-dates-count").textContent = d.dates.length || "";
  apFill("ap-waiting", d.waiting.map(waitingRow), "No tienes seguimientos abiertos.");
  $("ap-waiting-count").textContent = d.waiting.length || "";
  const counts = { listas: d.lists.length, habitos: d.habits.length, notas: d.notes.length, fechas: d.dates.length, seguimientos: d.waiting.length };
  for (const key in counts) $("ap-tab-" + key).textContent = counts[key] || "";
  $("ap-quiet").hidden = !d.quiet_until;
  if (d.quiet_until) $("ap-quiet-text").textContent = "En silencio hasta las " + new Date(d.quiet_until * 1000).toLocaleTimeString("es", { hour: "2-digit", minute: "2-digit" }) + ". Los avisos salen después.";
}
/* ---------- Gastos: recibos leídos de fotos ---------- */
let receiptsData = null, receiptsSerialized = "", editingReceipt = null, editingReceiptFields = null;
const rcMonth = { year: new Date().getFullYear(), month: new Date().getMonth() };
const rcKey = (y, m) => y + "-" + String(m + 1).padStart(2, "0");
function rcMoney(total, currency) {
  const sign = (receiptsData && receiptsData.currencies[currency]) || currency;
  return sign + " " + Number(total).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
function rcSum(list) {
  const sums = {};
  list.forEach(r => { sums[r.currency] = (sums[r.currency] || 0) + r.total; });
  const parts = Object.entries(sums).sort((a, b) => b[1] - a[1]).map(([c, t]) => rcMoney(t, c));
  return parts.length ? parts.join(" + ") : rcMoney(0, "GTQ");
}
function rcDay(iso) { const [y, m, d] = iso.split("-").map(Number); return d + " " + AP_MONTHS[m - 1].slice(0, 3); }
function rcPhoto(r) {
  $("rc-photo-img").src = "/recibo/" + r.id + ".jpg";
  const items = $("rc-photo-items"); items.textContent = "";
  if (r.items.length) { const ul = document.createElement("ul"); r.items.forEach(i => ul.appendChild(text("li", "", i))); items.appendChild(ul); }
  $("rc-photo").showModal();
}
$("rc-photo-close").addEventListener("click", () => $("rc-photo").close());
$("rc-photo").addEventListener("click", event => { if (event.target === $("rc-photo")) $("rc-photo").close(); });
function receiptRow(r) {
  const redraw = () => renderReceipts();
  if (editingReceipt === r.id) {
    const v = editingReceiptFields;
    const form = text("form", "ap-form rc-edit", ""); form.autocomplete = "off";
    const merchant = document.createElement("input"); merchant.maxLength = 80; merchant.value = v.merchant; merchant.setAttribute("aria-label", "Comercio");
    const total = document.createElement("input"); total.type = "number"; total.step = "0.01"; total.min = "0.01"; total.value = v.total; total.setAttribute("aria-label", "Total");
    const currency = document.createElement("select"); currency.setAttribute("aria-label", "Moneda");
    Object.entries(receiptsData.currencies).forEach(([code, sign]) => { const o = document.createElement("option"); o.value = code; o.textContent = sign; currency.appendChild(o); });
    currency.value = v.currency;
    const day = document.createElement("input"); day.type = "date"; day.value = v.day; day.setAttribute("aria-label", "Fecha de la compra");
    const category = document.createElement("select"); category.setAttribute("aria-label", "Categoría");
    receiptsData.categories.forEach(c => { const o = document.createElement("option"); o.value = c; o.textContent = capital(c); category.appendChild(o); });
    category.value = v.category;
    const warrantyLabel = text("label", "rc-warranty", "Garantía hasta ");
    const warranty = document.createElement("input"); warranty.type = "date"; warranty.value = v.warranty_until || ""; warranty.setAttribute("aria-label", "Garantía hasta (vacío si no tiene)");
    warrantyLabel.appendChild(warranty);
    const read = () => ({ merchant: merchant.value, total: total.value, currency: currency.value, day: day.value, category: category.value, warranty_until: warranty.value });
    [merchant, total, currency, day, category, warranty].forEach(el => { el.oninput = () => { editingReceiptFields = read(); }; });
    const stop = () => { editingReceipt = null; editingReceiptFields = null; };
    const save = text("button", "primary", "Guardar"); save.type = "submit";
    const cancel = text("button", "ap-x", "✕"); cancel.type = "button"; cancel.setAttribute("aria-label", "Cancelar la edición");
    cancel.onclick = () => { stop(); redraw(); };
    form.onkeydown = event => { if (event.key === "Escape") { stop(); redraw(); } };
    form.onsubmit = async event => {
      event.preventDefault();
      const f = read();
      const amount = parseFloat(f.total);
      if (!f.merchant.trim()) { merchant.focus(); return; }
      if (!(amount > 0)) { total.focus(); return; }
      save.disabled = true;
      try {
        toast((await send("/receipts", { action: "edit", id: r.id, merchant: f.merchant.trim(), total: amount, currency: f.currency,
          day: f.day, category: f.category, warranty_until: f.warranty_until || null })).message);
        stop();
        await loadReceipts(true);
      } catch (e) { toast(e.message); save.disabled = false; }
    };
    form.append(merchant, total, currency, day, category, warrantyLabel, save, cancel);
    setTimeout(() => { if (editingReceipt === r.id && !form.contains(document.activeElement)) merchant.focus(); }, 0);
    return form;
  }
  const row = text("div", "rc-row", "");
  const thumb = text("button", "rc-thumb", r.photo ? "" : "🧾"); thumb.type = "button";
  if (r.photo) { const img = document.createElement("img"); img.src = "/recibo/" + r.id + ".jpg"; img.alt = ""; img.loading = "lazy"; thumb.appendChild(img); }
  thumb.setAttribute("aria-label", "Ver la foto del recibo de " + r.merchant);
  thumb.disabled = !r.photo;
  thumb.onclick = () => rcPhoto(r);
  const body = text("div", "rc-body", "");
  const name = text("button", "ap-item", r.merchant); name.type = "button"; name.title = "Tocar para corregir";
  name.setAttribute("aria-label", "Corregir el recibo de " + r.merchant);
  name.onclick = () => { editingReceipt = r.id; editingReceiptFields = { merchant: r.merchant, total: r.total, currency: r.currency, day: r.day, category: r.category, warranty_until: r.warranty_until }; redraw(); };
  const detail = rcDay(r.day) + " · " + r.category + (r.warranty_until && r.warranty_until >= receiptsData.today ? " · 🛡 hasta " + rcDay(r.warranty_until) : "");
  body.append(name, text("small", "", detail));
  const amount = text("div", "rc-amount", rcMoney(r.total, r.currency));
  const remove = text("button", "ap-x", "✕"); remove.type = "button"; remove.setAttribute("aria-label", "Borrar el recibo de " + r.merchant);
  remove.onclick = async () => {
    if (!(await ask("¿Borrar el recibo de " + r.merchant + " por " + rcMoney(r.total, r.currency) + "? También se borra su foto.", "Borrar"))) return;
    try { toast((await send("/receipts", { action: "delete", id: r.id })).message); await loadReceipts(true); } catch (e) { toast(e.message); }
  };
  row.append(thumb, body, amount, remove);
  return row;
}
let editingBudgets = false;
// Presupuesto mensual de cada categoría, en quetzales. Vacío: sin presupuesto.
function budgetEditor() {
  const form = text("form", "rc-budgets", ""); form.autocomplete = "off";
  form.appendChild(text("p", "", "Cuánto quieres gastar al mes en cada categoría, en quetzales. Hermes te avisa al llegar al 80 % y al pasarte. Deja vacío lo que no quieras controlar."));
  const inputs = {};
  receiptsData.categories.forEach(c => {
    const row = text("label", "rc-budget-row", "");
    const input = document.createElement("input"); input.type = "number"; input.min = "0"; input.step = "1"; input.inputMode = "decimal";
    input.placeholder = "Sin límite"; input.value = receiptsData.budgets[c] || "";
    inputs[c] = input;
    row.append(text("span", "", capital(c)), input);
    form.appendChild(row);
  });
  const buttons = text("div", "rc-budget-buttons", "");
  const save = text("button", "primary", "Guardar"); save.type = "submit";
  const cancel = text("button", "ghost", "Cancelar"); cancel.type = "button";
  cancel.onclick = () => { editingBudgets = false; renderReceipts(); };
  buttons.append(cancel, save);
  form.appendChild(buttons);
  form.onsubmit = async event => {
    event.preventDefault();
    const budgets = {};
    for (const c in inputs) { const v = parseFloat(inputs[c].value); budgets[c] = v > 0 ? v : null; }
    save.disabled = true;
    try {
      toast((await send("/receipts", { action: "budgets", budgets })).message);
      editingBudgets = false;
      await loadReceipts(true);
    } catch (e) { toast(e.message); save.disabled = false; }
  };
  return form;
}
function renderReceipts() {
  if (!receiptsData) return;
  const key = rcKey(rcMonth.year, rcMonth.month);
  const today = receiptsData.today;
  const [ty, tm] = today.split("-").map(Number);
  $("rc-month").textContent = capital(AP_MONTHS[rcMonth.month]) + (rcMonth.year !== ty ? " " + rcMonth.year : "");
  $("rc-next").disabled = key >= today.slice(0, 7);
  $("rc-prev").disabled = key <= rcKey(ty - 1, tm - 1);  // Se guardan 13 meses a la vista.
  const month = receiptsData.receipts.filter(r => r.day.slice(0, 7) === key);
  const summary = $("rc-summary"); summary.textContent = "";
  const budgets = receiptsData.budgets || {};
  const budgetTotal = Object.values(budgets).reduce((s, v) => s + v, 0);
  const top = text("div", "rc-total", "");
  top.append(text("b", "", rcSum(month)), text("span", "", (month.length === 1 ? "1 recibo" : month.length + " recibos")
    + (budgetTotal ? " · presupuesto " + rcMoney(budgetTotal, "GTQ") : "")));
  const edit = text("button", "ap-link", budgetTotal ? "Cambiar presupuestos" : "Poner presupuestos"); edit.type = "button";
  edit.onclick = () => { editingBudgets = !editingBudgets; renderReceipts(); };
  top.appendChild(edit);
  summary.appendChild(top);
  if (editingBudgets) { summary.appendChild(budgetEditor()); }
  const byCategory = {};
  month.forEach(r => { (byCategory[r.category] = byCategory[r.category] || []).push(r); });
  Object.keys(budgets).forEach(c => { byCategory[c] = byCategory[c] || []; });  // Con presupuesto se ve aunque no haya gasto.
  // Las barras comparan quetzales: con presupuesto, contra el límite; sin él, contra la categoría más grande.
  const ranked = Object.entries(byCategory).map(([c, list]) => [c, list, list.filter(r => r.currency === "GTQ").reduce((s, r) => s + r.total, 0)])
    .sort((a, b) => (budgets[b[0]] ? b[2] / budgets[b[0]] : 0) - (budgets[a[0]] ? a[2] / budgets[a[0]] : 0) || b[2] - a[2]);
  const biggest = Math.max(1, ...ranked.filter(x => !budgets[x[0]]).map(x => x[2]));
  ranked.forEach(([c, list, amount]) => {
    const limit = budgets[c];
    const line = text("div", "rc-cat" + (limit && amount >= limit ? " over" : limit && amount >= 0.8 * limit ? " near" : ""), "");
    const bar = text("div", "rc-bar", ""); const fill = document.createElement("i");
    fill.style.width = (limit ? Math.min(100, Math.round(100 * amount / limit)) : Math.max(2, Math.round(100 * amount / biggest))) + "%";
    bar.appendChild(fill);
    const amountText = limit ? rcMoney(amount, "GTQ") + " de " + rcMoney(limit, "GTQ") : rcSum(list);
    line.append(text("span", "rc-cat-name", capital(c)), bar, text("span", "rc-cat-amount", amountText));
    if (limit) line.title = Math.round(100 * amount / limit) + " % del presupuesto";
    summary.appendChild(line);
  });
  const box = $("rc-list"); box.textContent = "";
  if (!month.length) {
    box.appendChild(text("div", "ap-empty card", key === today.slice(0, 7)
      ? "Todavía no hay recibos este mes. Mándale a Hermes por Telegram la foto de uno y aparece aquí."
      : "No hay recibos guardados en este mes."));
    return;
  }
  month.forEach(r => box.appendChild(receiptRow(r)));
}
async function loadReceipts(force) {
  try {
    const res = await fetch("/receipts", { cache: "no-store" });
    if (!res.ok) return;
    const data = await res.json();
    if (!data.receipts) return;
    const serialized = JSON.stringify(data);
    $("ap-tab-gastos").textContent = data.receipts.filter(r => r.day.slice(0, 7) === data.today.slice(0, 7)).length || "";
    if (!force && (serialized === receiptsSerialized || editingReceipt !== null || editingBudgets)) return;  // No pisa lo que estás corrigiendo.
    receiptsSerialized = serialized; receiptsData = data;
    renderReceipts();
  } catch {}
}
$("rc-prev").addEventListener("click", () => { rcMonth.month--; if (rcMonth.month < 0) { rcMonth.month = 11; rcMonth.year--; } editingReceipt = null; renderReceipts(); });
$("rc-next").addEventListener("click", () => { rcMonth.month++; if (rcMonth.month > 11) { rcMonth.month = 0; rcMonth.year++; } editingReceipt = null; renderReceipts(); });
async function loadApuntes(force) {
  loadReceipts(force);
  try {
    const res = await fetch("/extras", { cache: "no-store" });
    if (res.status === 401) { location.href = "/login"; return; }
    const data = await res.json();
    const serialized = JSON.stringify({ ...data, now: 0 });
    if (force || serialized !== apuntesSerialized) { apuntesSerialized = serialized; renderApuntes(data); }
  } catch { $("offline").style.display = "block"; }
}
function apForm(id, build, reset) {
  $(id).addEventListener("submit", async event => {
    event.preventDefault();
    const body = build();
    if (body && await apunte(body)) reset();
  });
}
$("ap-list-form").addEventListener("submit", async event => {
  event.preventDefault();
  const name = $("ap-list-name").value.trim();
  if (!name) { $("ap-list-name").focus(); return; }
  const key = plainText(name).split(" ").filter(Boolean).join(" ");
  closedLists.delete(key); focusList = key;  // La lista nueva queda abierta y lista para escribir.
  if (await apunte({ action: "list_create", list: name })) $("ap-list-name").value = "";
});
apForm("ap-habit-form", () => {
  const title = $("ap-habit-title").value.trim();
  return title ? { action: "habit_add", title, time: $("ap-habit-time").value || null } : null;
}, () => { $("ap-habit-title").value = ""; $("ap-habit-time").value = ""; });
apForm("ap-waiting-form", () => {
  const what = $("ap-waiting-text").value.trim();
  const days = parseInt($("ap-waiting-days").value, 10);
  return what ? { action: "waiting_add", text: what, days: days || 3 } : null;
}, () => { $("ap-waiting-text").value = ""; });
apForm("ap-note-form", () => {
  const note = $("ap-note-text").value.trim();
  return note ? { action: "note_add", text: note } : null;
}, () => { $("ap-note-text").value = ""; });
apForm("ap-date-form", () => {
  const day = parseInt($("ap-date-day").value, 10);
  if (!day) return null;
  const year = parseInt($("ap-date-year").value, 10);
  return { action: "date_add", kind: $("ap-date-kind").value, name: $("ap-date-name").value.trim(), day, month: parseInt($("ap-date-month").value, 10), year: year || null };
}, () => { $("ap-date-name").value = ""; $("ap-date-day").value = ""; $("ap-date-year").value = ""; });
$("ap-quiet-off").addEventListener("click", () => apunte({ action: "quiet_off" }));
setInterval(() => { if (currentView() === "apuntes") loadApuntes(); }, 5000);

/* ---------- Sesiones abiertas ---------- */
function ago(ts) {
  const minutes = Math.max(0, Math.round((Date.now() / 1000 - ts) / 60));
  if (minutes < 2) return "ahora";
  if (minutes < 60) return "hace " + minutes + " min";
  if (minutes < 1440) return "hace " + Math.round(minutes / 60) + " h";
  return "hace " + Math.round(minutes / 1440) + " días";
}
async function sessionAction(body) {
  try {
    const data = await send("/sessions", body);
    toast(data.message);
    if (body.action === "logout") { location.href = "/login"; return; }
    loadSessions();
  } catch (e) { toast(e.message); }
}
async function loadSessions() {
  try {
    const res = await fetch("/sessions", { cache: "no-store" });
    if (!res.ok) return;
    const data = await res.json();
    $("set-sessions").hidden = !data.enabled;
    const box = $("set-sessions-list"); box.textContent = "";
    if (!data.sessions.length) box.appendChild(text("div", "ap-empty", "No hay ningún dispositivo con la página abierta desde fuera."));
    for (const s of data.sessions) {
      const row = text("div", "ap-row", "");
      const body = text("div", "grow", s.label + (s.current ? " · este dispositivo" : ""));
      body.appendChild(text("small", "", (s.ip || "origen desconocido") + " · entró " + ago(s.created_at) + " · activo " + ago(s.last_seen)));
      row.appendChild(body);
      if (!s.current) {
        const close = text("button", "ap-link danger-link", "Cerrar"); close.type = "button";
        close.onclick = async () => { if (await ask("¿Cerrar la sesión de " + s.label + "? Tendrá que entrar de nuevo.", "Cerrar")) sessionAction({ action: "revoke", id: s.id }); };
        row.appendChild(close);
      }
      box.appendChild(row);
    }
    const others = data.sessions.filter(s => !s.current).length;
    $("set-sessions-all").hidden = !others;
    $("set-sessions-all").textContent = data.remote ? "Cerrar las demás" : "Cerrar todas";
    $("set-logout").hidden = !data.remote;
  } catch {}
}
$("set-sessions-all").addEventListener("click", async () => { if (await ask("¿Cerrar todas las demás sesiones? Cada dispositivo tendrá que entrar de nuevo.", "Cerrar")) sessionAction({ action: "revoke_all" }); });
$("set-logout").addEventListener("click", async () => { if (await ask("¿Cerrar la sesión en este dispositivo?", "Cerrar sesión", true)) sessionAction({ action: "logout" }); });

/* ---------- Ajustes ---------- */
let settingsData = null;
let restarting = false;
// Categorías: etiquetas con color que se agregan y se quitan, en vez de una lista separada por comas.
// Por debajo sigue siendo el mismo valor ("trabajo, casa, …"), en un campo oculto que lee el guardado.
function categoryEditor(s) {
  const box = text("div", "chips", "");
  const hidden = document.createElement("input");
  hidden.type = "hidden"; hidden.value = s.value || ""; hidden.dataset.initial = hidden.value; hidden.dataset.key = s.key;
  const current = () => hidden.value.split(",").map(c => c.trim()).filter(Boolean);
  // Los colores van en su propio ajuste, oculto, que se guarda junto con las categorías.
  const colorSetting = settingsData.groups.flatMap(g => g.settings).find(x => x.kind === "colors") || null;
  const colorInput = document.createElement("input");
  colorInput.type = "hidden";
  if (colorSetting) { colorInput.value = colorSetting.value || ""; colorInput.dataset.initial = colorInput.value; colorInput.dataset.key = colorSetting.key; }
  const colors = {};
  colorInput.value.split(",").forEach(part => {
    const at = part.lastIndexOf(":");
    if (at > 0) colors[part.slice(0, at).trim()] = part.slice(at + 1).trim();
  });
  const saveColors = () => {
    colorInput.value = current().filter(c => colors[c]).map(c => c + ":" + colors[c]).join(", ");
    colorInput.dispatchEvent(new Event("input", { bubbles: true }));
  };
  // Color actual de una categoría, en #rrggbb: el elegido, o el que la página usa por defecto.
  const colorOf = category => {
    if (colors[category]) return colors[category];
    const value = getComputedStyle(document.body).getPropertyValue("--c-" + (KNOWN.includes(category) ? category : "otra")).trim();
    return /^#[0-9a-fA-F]{6}$/.test(value) ? value.toLowerCase() : "#7b7870";
  };
  const PALETTE = ["#e05d5d", "#e8833a", "#e2c044", "#9bcf53", "#3fae6f", "#33b5b0", "#3fa7e0", "#5a73e8",
    "#8a63d6", "#c75bd1", "#e0609e", "#a07a5a", "#7f8c99", "#c9a227", "#5fc4c0", "#ec86a7"];
  // El color más distinto de los que ya tienen las demás categorías.
  const freeColor = () => {
    const rgb = hex => [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16));
    const used = current().map(c => rgb(colorOf(c)));
    const distance = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);
    let best = PALETTE[0], bestScore = -1;
    for (const candidate of PALETTE) {
      const score = used.length ? Math.min(...used.map(u => distance(u, rgb(candidate)))) : 999;
      if (score > bestScore) { best = candidate; bestScore = score; }
    }
    return best;
  };
  const list = text("div", "chip-list", "");
  const form = text("div", "chip-add", "");
  const input = document.createElement("input");
  input.id = "set-" + s.key; input.maxLength = 20; input.placeholder = "Nueva categoría"; input.enterKeyHint = "done";
  input.setAttribute("aria-label", "Nueva categoría"); input.autocomplete = "off";
  const add = text("button", "ghost", "+ Agregar"); add.type = "button";
  const note = text("div", "chip-note", "");
  const set = values => {
    hidden.value = values.join(", ");
    hidden.dispatchEvent(new Event("input", { bubbles: true }));  // Activa «Guardar cambios».
    draw();
  };
  const pendingIn = async category => {
    try {
      const data = lastTasks || await (await fetch("/tasks", { cache: "no-store" })).json();
      return (data.pending || []).filter(t => t.category === category && t.parent_id === null).length;
    } catch { return 0; }
  };
  function draw() {
    list.textContent = "";
    const values = current();
    for (const category of values) {
      const chip = text("span", "chip", "");
      const swatch = document.createElement("input");
      swatch.type = "color"; swatch.className = "chip-color"; swatch.value = colorOf(category); swatch.disabled = !!s.locked;
      swatch.setAttribute("aria-label", "Color de la categoría " + category); swatch.title = "Cambiar el color";
      swatch.oninput = () => { colors[category] = swatch.value.toLowerCase(); saveColors(); };
      chip.append(swatch, text("span", "", category.charAt(0).toUpperCase() + category.slice(1)));
      if (!s.locked) {
        const remove = text("button", "chip-x", "✕"); remove.type = "button";
        remove.setAttribute("aria-label", "Quitar la categoría " + category);
        remove.disabled = values.length === 1;
        remove.title = values.length === 1 ? "Tiene que quedar al menos una" : "Quitar";
        remove.onclick = async () => {
          const count = await pendingIn(category);
          if (count && !await ask("«" + category + "» tiene " + (count === 1 ? "1 tarea pendiente" : count + " tareas pendientes") +
            ". Las tareas no se borran: siguen apareciendo con esa categoría, pero ya no podrás elegirla para tareas nuevas. ¿Quitarla?", "Quitar")) return;
          delete colors[category];
          set(current().filter(c => c !== category));
          saveColors();
        };
        chip.append(remove);
      }
      list.append(chip);
    }
    const full = values.length >= 50;
    input.disabled = add.disabled = !!s.locked || full;
    note.textContent = full ? "Llegaste al máximo de 50 categorías." : "";
  }
  const tryAdd = () => {
    const raw = input.value.toLowerCase().split(" ").filter(Boolean).join(" ");
    if (!raw) { input.focus(); return; }
    if (raw.length < 2 || !/^[a-záéíóúüñ0-9 ]+$/.test(raw)) { note.textContent = "Usa solo letras, números y espacios (de 2 a 20)."; return; }
    if (current().includes(raw)) { note.textContent = "«" + raw + "» ya está."; return; }
    input.value = "";
    colors[raw] = freeColor();  // Cada categoría nueva nace con un color propio, que luego puedes cambiar.
    set([...current(), raw]);
    saveColors();
    input.focus();
  };
  add.onclick = tryAdd;
  input.onkeydown = event => { if (event.key === "Enter") { event.preventDefault(); tryAdd(); } };
  input.oninput = () => { note.textContent = ""; };
  form.append(input, add);
  box.append(list, form, note, hidden);
  if (colorSetting) box.append(colorInput);
  draw();
  return box;
}
function settingControl(s) {
  if (s.kind === "list") return categoryEditor(s);
  let el;
  if (s.kind === "switch") {
    el = document.createElement("input"); el.type = "checkbox"; el.checked = s.value === "on";
    el.dataset.initial = el.checked ? "on" : "off";
  } else if (s.kind === "choice") {
    el = document.createElement("select");
    s.choices.forEach((c, i) => { const o = document.createElement("option"); o.value = c; o.textContent = (s.choice_labels || [])[i] || c; el.appendChild(o); });
    el.value = s.value; el.dataset.initial = s.value;
    // Valor del archivo que no está en la lista: se propone el de siempre y queda como cambio por guardar.
    if (el.value !== s.value) el.value = s.choices.includes(s.default) ? s.default : s.choices[0];
  } else {
    el = document.createElement("input");
    const secret = s.kind === "secret" || s.kind === "url";
    el.type = secret ? "password" : s.kind === "int" ? "number" : (s.kind === "time" || s.kind === "time_off") ? "time" : "text";
    if (s.kind === "int") { el.min = s.low; el.max = s.high; }
    if (secret) { el.placeholder = s.set ? "Guardada · escribe una nueva" : "Sin configurar"; el.autocomplete = "new-password"; }
    else if (s.confirm) el.placeholder = s.set ? "Guardado · escribe uno nuevo" : "Sin configurar";
    el.value = s.value || ""; el.dataset.initial = el.value; el.maxLength = 600;
  }
  el.id = "set-" + s.key; el.dataset.key = s.key; el.disabled = !!s.locked;
  return el;
}
// Botón de ojo: muestra lo que estás escribiendo en un campo secreto. Lo guardado nunca llega a la página.
const EYE_SVG = '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/><path class="eye-off" d="M4 4l16 16"/></svg>';
function withEye(input) {
  if (input.type !== "password") return input;
  const wrap = text("span", "pw", "");
  const eye = document.createElement("button");
  eye.type = "button"; eye.className = "pw-eye"; eye.innerHTML = EYE_SVG; eye.disabled = input.disabled;
  eye.setAttribute("aria-pressed", "false"); eye.setAttribute("aria-label", "Mostrar lo que escribes"); eye.title = "Mostrar lo que escribes";
  eye.onclick = () => {
    const show = input.type === "password";
    input.type = show ? "text" : "password";
    eye.setAttribute("aria-pressed", String(show));
    eye.setAttribute("aria-label", show ? "Ocultar" : "Mostrar lo que escribes"); eye.title = eye.getAttribute("aria-label");
  };
  wrap.append(input, eye);
  return wrap;
}
function settingValue(el) { return el.type === "checkbox" ? (el.checked ? "on" : "off") : el.value.trim(); }
function settingChanges() {
  const changes = {};
  document.querySelectorAll("#set-groups [data-key]").forEach(el => { if (!el.disabled && settingValue(el) !== el.dataset.initial) changes[el.dataset.key] = settingValue(el); });
  return changes;
}
function renderSettings(data) {
  settingsData = data;
  const box = $("set-groups"); box.textContent = "";
  for (const group of data.groups) {
    const card = text("section", "set-group", ""); card.appendChild(text("h3", "", group.name));
    for (const s of group.settings) {
      if (s.kind === "colors") continue;  // Se edita dentro de las etiquetas de categorías.
      const row = text("div", "set-row" + (s.kind === "list" ? " wide" : ""), "");
      const label = text("label", "", s.label); label.htmlFor = "set-" + s.key;
      if (!s.live) label.appendChild(text("span", "set-tag", "Al reiniciar"));
      const help = s.locked ? "Solo se cambia desde la computadora de Hermes."
        : s.confirm ? (s.help ? s.help + " " : "") + "Desde aquí, el cambio espera tu aprobación en Telegram." : s.help;
      if (help) label.appendChild(text("small", "", help));
      row.appendChild(label); row.appendChild(withEye(settingControl(s))); card.appendChild(row);
    }
    box.appendChild(card);
  }
  $("set-restart").hidden = !data.restart_needed || !data.can_restart;
  $("set-save").disabled = !Object.keys(settingChanges()).length;
}
// Un cambio delicado pedido desde fuera queda en espera: la página revisa hasta que lo resuelvas en Telegram.
async function waitForApproval() {
  for (let i = 0; i < 110; i++) {
    await new Promise(resolve => setTimeout(resolve, 3000));
    try {
      const res = await fetch("/settings", { cache: "no-store" });
      if (!res.ok) continue;
      const data = await res.json();
      if (data.pending) continue;
      renderSettings(data);
      $("set-status").textContent = "La solicitud ya quedó resuelta en Telegram. Aquí ves cómo quedó.";
      return;
    } catch {}
  }
  $("set-status").textContent = "La solicitud venció sin aprobarse. No se cambió nada.";
}
async function loadSettings() {
  if (Object.keys(settingChanges()).length) return;  // No pisa lo que estás escribiendo.
  try {
    const res = await fetch("/settings", { cache: "no-store" });
    if (res.status === 401) { location.href = "/login"; return; }
    if (res.status === 404) { $("set-groups").textContent = ""; $("set-groups").appendChild(text("div", "empty", "Los ajustes no están disponibles.")); return; }
    renderSettings(await res.json());
  } catch { $("offline").style.display = "block"; }
}
$("set-form").addEventListener("input", () => { $("set-save").disabled = !Object.keys(settingChanges()).length; $("set-status").textContent = ""; });
$("set-form").addEventListener("submit", async event => {
  event.preventDefault();
  const changes = settingChanges();
  if (!Object.keys(changes).length) return;
  $("set-save").disabled = true;
  try {
    const data = await send("/settings", { changes });
    document.querySelectorAll("#set-groups [data-key]").forEach(el => { el.dataset.initial = settingValue(el); });
    $("set-status").textContent = data.message;
    if (data.pending) { waitForApproval(); return; }
    await loadSettings();
  } catch (e) { $("set-status").textContent = e.message; $("set-save").disabled = false; }
});
$("set-restart-btn").addEventListener("click", async () => {
  if (!await ask("Hermes se detiene unos segundos y vuelve a arrancar. ¿Reiniciar ahora?", "Reiniciar", true)) return;
  $("set-restart-btn").disabled = true;
  try {
    await send("/settings", { action: "restart" });
    restarting = true;
    $("set-restart").firstElementChild.textContent = "Reiniciando Hermes… puede tardar hasta un minuto. La página se recarga sola.";
  } catch (e) { toast(e.message); $("set-restart-btn").disabled = false; }
});
let orbLevel = 0;
let bootId = null;
function updateOrb(s) {
  const orb = $("orb");
  orb.dataset.state = s.state;
  // Nivel relativo al umbral de voz: el ruido de fondo apenas mueve los anillos, la voz los enciende.
  const reference = Math.max(s.threshold || 250, 1) * 1.6;
  const target = s.state === "inactiva" ? 0 : Math.min(1, Math.sqrt((s.level || 0) / reference));
  orbLevel = orbLevel * 0.45 + target * 0.55;
  orb.style.setProperty("--level", orbLevel.toFixed(3));
}
let micBusy = false;
function updateMicButton(s) {
  const btn = $("mic-btn");
  btn.disabled = micBusy || s.state === "inactiva";
  btn.setAttribute("aria-pressed", String(!!s.paused));
  $("mic-label").textContent = s.paused ? "Volver a escuchar" : "Dejar de escuchar";
  $("mic-slash").style.display = s.paused ? "none" : "";
}
$("mic-btn").addEventListener("click", async () => {
  const listening = $("mic-btn").getAttribute("aria-pressed") === "true";
  micBusy = true; $("mic-btn").disabled = true;
  try { await send("/voice", { listening }); } catch (e) { toast(e.message); }
  micBusy = false;
});
async function tick() {
  try {
    const res = await fetch("/status", { cache: "no-store" });
    if (res.status === 401) { location.href = "/login"; return; }
    const s = await res.json();
    if (bootId === null) bootId = s.boot;
    else if (s.boot !== bootId) { location.reload(); return; }  // Hermes se reinició: la página trae una clave nueva.
    $("offline").style.display = "none";
    const [title, hint] = STATES[s.state] || [s.state, ""];
    $("pill").classList.toggle("on", s.state !== "inactiva" && s.state !== "pausada");
    updateMicButton(s);
    $("talk-btn").hidden = !s.speak;
    document.body.classList.toggle("can-speak", !!s.speak);
    $("pill").lastElementChild.textContent = "Voz: " + title.toLowerCase();
    if (currentView() === "vivo") {
      $("state").textContent = title; $("hint").textContent = hint;
      $("fill").style.width = pct(s.level) + "%";
      $("fill").classList.toggle("voice", s.level >= s.threshold && s.threshold > 0);
      $("mark").style.left = pct(s.threshold) + "%";
      $("level").textContent = "Nivel: " + s.level;
      $("threshold").textContent = "Mínimo para contar como voz: " + s.threshold;
      updateOrb(s);
    }
    if (s.version !== shown && currentView() === "historial") { shown = s.version; loadHistory(); }
  } catch {
    $("offline").style.display = restarting ? "none" : "block";
    $("pill").classList.remove("on");
    $("pill").lastElementChild.textContent = "Sin conexión";
  }
  setTimeout(tick, currentView() === "vivo" ? 200 : 2000);
}
showView();
tick();
</script>
</body>
</html>
"""


MAX_POST_BYTES = 4096


class _CountingReader:
    """Envuelve lo que llega en una solicitud y cuenta cuánto se leyó."""

    def __init__(self, raw: Any):
        self.raw, self.count = raw, 0

    def read(self, size: int = -1) -> bytes:
        data = self.raw.read(size)
        self.count += len(data)
        return data

    def readline(self, size: int = -1) -> bytes:
        data = self.raw.readline(size)
        self.count += len(data)
        return data
MAX_LOGIN_BYTES = 1024
MAX_AUDIO_BYTES = 3_000_000  # Una orden hablada de hasta un minuto pesa mucho menos.


def make_handler(status: VoiceStatus, port: int, remote: RemoteAccess | None = None) -> type[BaseHTTPRequestHandler]:
    remote = remote or RemoteAccess()
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
    allowed_origins = {f"http://{host}" for host in allowed_hosts}
    # Clave nueva en cada arranque: solo la conoce la página servida aquí, así otra web no puede pausar el micrófono.
    token = secrets.token_urlsafe(24)
    page = PAGE.replace("__CSRF_TOKEN__", token).replace("__TOUCH_ICON__", touch_icon()).encode("utf-8")

    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, content_type: str, body: bytes, extra: dict[str, str] | None = None) -> None:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            # "no-referrer" haría que el navegador mande "Origin: null" en el formulario de entrada.
            self.send_header("Referrer-Policy", "same-origin")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; "
                "img-src 'self' data:; manifest-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'",
            )
            for name, value in (extra or {}).items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)

        def _is_remote(self) -> bool:
            """Llegó por el túnel: o trae otro Host, o trae los encabezados que agrega un túnel."""
            return self.headers.get("Host") not in allowed_hosts or remote.is_forwarded(self.headers)

        def _remote_allowed(self) -> bool:
            # Solo el dominio configurado; cualquier otro nombre (o un túnel que reescribe el Host) se rechaza.
            return remote.enabled and (self.headers.get("Host") or "").lower() == remote.host

        def _login(self) -> None:
            origin = self.headers.get("Origin")
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= MAX_LOGIN_BYTES or (origin and origin != remote.origin):
                    raise ValueError
                password = parse_qs(self.rfile.read(length).decode("utf-8")).get("password", [""])[0]
            except ValueError:
                return self._send(400, "text/html; charset=utf-8", login_page("Solicitud inválida."))
            ip = remote.client_ip(self.headers)
            try:
                session = remote.login(password, ip, self.headers.get("User-Agent", ""))
            except ApprovalUnavailable:
                return self._send(503, "text/html; charset=utf-8", login_page("No pude avisarte por Telegram. Intenta de nuevo en un momento."))
            if session:
                return self._send(303, "text/plain; charset=utf-8", b"", {"Location": "/", "Set-Cookie": remote.cookie(session)})
            wait = remote.locked_for(ip)
            if wait:
                minutes = -(-wait // 60)
                message = f"Demasiados intentos. Espera {minutes} min y vuelve a intentar."
                return self._send(429, "text/html; charset=utf-8", login_page(message))
            self._send(401, "text/html; charset=utf-8", login_page("Contraseña incorrecta."))

        def do_GET(self) -> None:
            # Valida el Host para que una web externa no pueda leer esto mediante DNS rebinding.
            path = urlsplit(self.path).path
            if self._is_remote() and not self._remote_allowed():
                return self._send(403, "text/plain; charset=utf-8", b"Solo desde esta computadora.")
            if path == "/manifest.webmanifest":
                return self._send(200, "application/manifest+json", MANIFEST)
            if path in PUBLIC_FILES and (ASSETS / path[1:]).exists():
                return self._send(200, PUBLIC_FILES[path], (ASSETS / path[1:]).read_bytes())
            if self._is_remote():
                if path == "/login":
                    return self._send(200, "text/html; charset=utf-8", login_page())
                state = remote.state(self.headers.get("Cookie"))
                if path == "/login/state":
                    return self._json(200, {"state": state})
                if state == "pending" and path == "/":
                    # La contraseña fue correcta, pero falta que el dueño apruebe este dispositivo en Telegram.
                    return self._send(200, "text/html; charset=utf-8", wait_page())
                if state != "ok":
                    if path == "/":
                        return self._send(303, "text/plain; charset=utf-8", b"", {"Location": "/login"})
                    return self._send(401, "text/plain; charset=utf-8", "Sesión requerida.".encode("utf-8"))
            if path == "/sessions":
                is_remote = self._is_remote()
                return self._json(200, {"sessions": remote.sessions(self.headers.get("Cookie")), "remote": is_remote, "enabled": remote.enabled})
            if path == "/":
                self._send(200, "text/html; charset=utf-8", page)
            elif path == "/logo.webp" and LOGO_PATH.exists():
                self._send(200, "image/webp", LOGO_PATH.read_bytes())
            elif path == "/status":
                self._send(200, "application/json", json.dumps(status.snapshot()).encode("utf-8"))
            elif path == "/settings" and status.settings is not None:
                self._json(200, status.settings.snapshot(not self._is_remote()))
            elif path in ("/tasks", "/usage", "/history", "/extras", "/receipts"):
                self._send(200, "application/json", json.dumps(status.read(path[1:])).encode("utf-8"))
            elif path.startswith("/recibo/") and path.endswith(".jpg") and path[8:-4].isdigit() and status.receipt_photo:
                photo = status.receipt_photo(int(path[8:-4]))
                if photo is None:
                    return self._send(404, "text/plain; charset=utf-8", b"No encontrado.")
                self._send(200, "image/jpeg", photo)
            else:
                self._send(404, "text/plain; charset=utf-8", b"No encontrado.")

        def _json(self, code: int, data: dict[str, Any]) -> None:
            self._send(code, "application/json", json.dumps(data).encode("utf-8"))

        def _settings(self) -> None:
            """Cambios a los ajustes. El editor recibe si la visita es local: lo delicado no se toca desde fuera."""
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= MAX_POST_BYTES or self.headers.get("Content-Type") != "application/json":
                    raise ValueError
                payload = json.loads(self.rfile.read(length))
            except ValueError:
                return self._json(400, {"error": "Solicitud inválida."})
            try:
                self._json(200, status.settings.apply(payload, not self._is_remote()))
            except ValueError as exc:
                self._json(400, {"error": str(exc) or "Solicitud inválida."})
            except Exception:
                log.exception("Falló el cambio de ajustes pedido desde la página")
                self._json(500, {"error": "Ocurrió un error. Revisa el registro de Hermes."})

        def _sessions(self) -> None:
            """Cerrar sesiones de la página: la de este dispositivo, una en particular o todas las demás."""
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= MAX_POST_BYTES or self.headers.get("Content-Type") != "application/json":
                    raise ValueError
                payload = json.loads(self.rfile.read(length))
                action = payload.get("action") if isinstance(payload, dict) else None
                if action not in ("logout", "revoke", "revoke_all"):
                    raise ValueError
            except ValueError:
                return self._json(400, {"error": "Solicitud inválida."})
            cookie = self.headers.get("Cookie")
            if action == "logout":
                remote.logout(cookie)
                body = json.dumps({"ok": True, "message": "Sesión cerrada."}).encode("utf-8")
                return self._send(200, "application/json", body, {"Set-Cookie": remote.clear_cookie()})
            if action == "revoke":
                session_id = payload.get("id")
                if isinstance(session_id, bool) or not isinstance(session_id, int) or not remote.revoke(session_id):
                    return self._json(400, {"error": "Esa sesión ya estaba cerrada."})
                return self._json(200, {"ok": True, "message": "Sesión cerrada."})
            count = remote.revoke_all(cookie)
            self._json(200, {"ok": True, "message": "Cerré " + str(count) + (" sesión." if count == 1 else " sesiones.")})

        def _speak(self) -> None:
            """Una orden grabada en la página: el cuerpo es el audio tal como lo entrega el navegador."""
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= MAX_AUDIO_BYTES or not self.headers.get("Content-Type", "").startswith("audio/"):
                    raise ValueError
            except ValueError:
                return self._json(400, {"error": "Solicitud inválida."})
            code, result = status.act("speak", self.rfile.read(length))
            self._json(code, result)

        def do_POST(self) -> None:
            # Si se responde sin leer todo lo enviado (un 401, 403 o 404), Windows corta la conexión con un
            # reinicio y el navegador ve un error de red en vez de la respuesta: lo que sobre se lee y se descarta.
            try:
                declared = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                declared = 0
            raw = self.rfile
            counted = _CountingReader(raw)
            self.rfile = counted  # type: ignore[assignment]
            try:
                self._post()
            finally:
                self.rfile = raw
                left = declared - counted.count
                if 0 < left <= MAX_AUDIO_BYTES:
                    try:
                        raw.read(left)
                    except OSError:
                        pass

        def _post(self) -> None:
            # Otra web abierta en el navegador podría enviar formularios aquí: se exige el origen
            # de esta página y la clave que solo ella conoce.
            sent_token = self.headers.get("X-Hermes-Token", "").encode("latin-1", "replace")
            path = urlsplit(self.path).path
            if self._is_remote():
                # Por el túnel, además: el dominio configurado y una sesión abierta con la contraseña.
                if not self._remote_allowed():
                    return self._send(403, "text/plain; charset=utf-8", b"No permitido.")
                if path == "/login":
                    return self._login()
                if not remote.valid(self.headers.get("Cookie")):
                    return self._send(401, "text/plain; charset=utf-8", "Sesión requerida.".encode("utf-8"))
                origin_ok = self.headers.get("Origin") == remote.origin
            else:
                origin_ok = self.headers.get("Origin") in allowed_origins
            if not origin_ok or not secrets.compare_digest(sent_token, token.encode("ascii")):
                return self._send(403, "text/plain; charset=utf-8", b"No permitido.")
            if path == "/settings" and status.settings is not None:
                return self._settings()
            if path == "/sessions":
                return self._sessions()
            if path not in ("/voice", "/tasks", "/speak", "/extras", "/receipts") or (path != "/voice" and not status.has_action(path[1:])):
                return self._send(404, "text/plain; charset=utf-8", b"No encontrado.")
            if path == "/speak":
                return self._speak()
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= MAX_POST_BYTES or self.headers.get("Content-Type") != "application/json":
                    raise ValueError
                payload = json.loads(self.rfile.read(length))
            except ValueError:
                return self._json(400, {"error": "Solicitud inválida."})
            if path == "/voice":
                listening = payload.get("listening") if isinstance(payload, dict) else None
                if not isinstance(listening, bool):
                    return self._json(400, {"error": "Solicitud inválida."})
                status.set_paused(not listening)
                return self._json(200, {"paused": status.paused})
            code, result = status.act(path[1:], payload)
            self._json(code, result)

        def log_message(self, *_: Any) -> None:
            pass

    return Handler


class StatusServer(ThreadingHTTPServer):
    allow_reuse_address = False  # En Windows, reutilizar dejaría a dos programas en el mismo puerto.
    daemon_threads = True


def start_status_server(
    status: VoiceStatus, port: int, remote: RemoteAccess | None = None
) -> ThreadingHTTPServer | None:
    try:
        server = StatusServer(("127.0.0.1", port), make_handler(status, port, remote))
    except OSError as exc:
        log.warning("No se pudo abrir la página de estado: %s", exc)
        return None
    threading.Thread(target=server.serve_forever, daemon=True, name="status-page").start()
    log.info("Página de estado en http://127.0.0.1:%d", port)
    if remote is not None and remote.enabled:
        log.info("Página: acceso remoto con contraseña encendido para %s", remote.host)
    elif remote is not None and remote.problem:
        log.warning("Página: acceso remoto apagado, %s", remote.problem)
    return server
