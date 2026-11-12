"""Página local con las tareas y lo que oye Hermes en vivo. Solo acepta conexiones de esta computadora."""
from __future__ import annotations

import json
import logging
import threading
import time
from collections import deque
from dataclasses import asdict
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Sequence
from urllib.parse import urlsplit

log = logging.getLogger(__name__)

LOGO_PATH = Path(__file__).resolve().parent / "assets" / "logo.webp"
MAX_EVENTS = 25
USAGE_REFRESH_SECONDS = 3.0
RECENT_DONE_DAYS = 7


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


def tasks_snapshot(store: Any, categories: Sequence[str], now: int) -> dict[str, Any]:
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
        "pending": pending,
        "done_steps": done_steps,
        "finished": store.recently_finished(now - RECENT_DONE_DAYS * 86400),
    }


PAGE = """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Hermes</title>
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
body { margin:0; background:var(--bg); color:var(--ink); font:15px/1.5 "Segoe UI Variable Text","Segoe UI",system-ui,sans-serif; }
header { position:sticky; top:0; z-index:5; background:color-mix(in srgb, var(--bg) 88%, transparent); backdrop-filter:blur(8px); border-bottom:1px solid var(--line); }
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
.orb[data-state="pitido"], .orb[data-state="grabando"] { --glow:1; --speed:1.5s; }
.orb[data-state="transcribiendo"], .orb[data-state="pensando"] { --glow:.7; --speed:2.4s; }
.orb[data-state="pensando"] .disc { animation:breathe 1.6s ease-in-out infinite; }
.orb[data-state="hablando"] { --glow:.85; --speed:1.9s; }
@keyframes breathe { 50% { transform:scale(1.035); } }
.stage-wrap #state { color:rgb(242,194,48); font-size:28px; }
.stage-wrap #hint { margin-top:-12px; }
.stage-meter { width:min(78vw, 360px); }
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

@media (max-width:640px) {
  .stats { grid-template-columns:repeat(2, 1fr); }
  .tabs a { padding:6px 10px; }
  .xlabels span:nth-child(even):not(:first-child) { visibility:hidden; }
  .brand { width:100%; }
}
</style>
</head>
<body class="stage">
<header>
  <div class="bar">
    <div class="brand"><span class="brand-dot"></span>Hermes</div>
    <nav class="tabs" aria-label="Secciones">
      <a href="#tareas" data-view="tareas">Tareas</a>
      <a href="#consumo" data-view="consumo">Consumo</a>
      <a href="#historial" data-view="historial">Historial</a>
      <a href="#vivo" data-view="vivo">En vivo</a>
    </nav>
    <div class="pill" id="pill"><i></i><span>Conectando…</span></div>
  </div>
</header>
<main>
<div id="offline">Hermes no responde. Revisa que esté encendido.</div>

<div class="view" id="view-tareas">
  <h2>Tus tareas</h2>
  <div class="subtitle" id="updated">Cargando…</div>
  <div class="stats">
    <div class="stat"><b id="s-pending">–</b><span id="s-pending-label">Pendientes</span></div>
    <div class="stat" id="s-urgent-box"><b id="s-urgent">–</b><span>Urgentes</span></div>
    <div class="stat" id="s-overdue-box"><b id="s-overdue">–</b><span>Vencidas</span></div>
    <div class="stat"><b id="s-today">–</b><span>Para hoy</span></div>
  </div>
  <div class="filters" id="filters" role="group" aria-label="Filtrar por categoría"></div>
  <div class="groups" id="groups"></div>
  <details class="finished card" id="finished-box">
    <summary id="finished-title" style="padding:12px 16px">Completadas en los últimos 7 días</summary>
    <div class="finished-list" id="finished"></div>
  </details>
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
<script>
const $ = id => document.getElementById(id);
function text(tag, cls, value) { const el = document.createElement(tag); if (cls) el.className = cls; el.textContent = value; return el; }

/* ---------- Navegación ---------- */
const VIEWS = ["tareas", "consumo", "historial", "vivo"];
function currentView() { const v = location.hash.slice(1); return VIEWS.includes(v) ? v : "tareas"; }
function showView() {
  const view = currentView();
  for (const name of VIEWS) $("view-" + name).hidden = name !== view;
  document.querySelectorAll(".tabs a").forEach(a => a.setAttribute("aria-current", a.dataset.view === view ? "page" : "false"));
  if (view === "tareas") loadTasks();
  if (view === "consumo") loadUsage();
  if (view === "historial") loadHistory();
}
window.addEventListener("hashchange", showView);

/* ---------- Tareas ---------- */
const URGENCY = { alta: "Urgente", media: "Normal", baja: "Baja" };
const URGENCY_ORDER = { alta: 0, media: 1, baja: 2 };
const KNOWN = ["trabajo", "negocios", "casa", "personal", "salud", "finanzas", "reptiles"];
let filter = "todas";
let lastTasks = null;
const catColor = c => "var(--c-" + (KNOWN.includes(c) ? c : "otra") + ")";
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
function sortTasks(a, b) {
  const da = a.due_at || Infinity, db = b.due_at || Infinity;
  return da - db || URGENCY_ORDER[a.urgency] - URGENCY_ORDER[b.urgency] || a.id - b.id;
}
function metaLine(t, nowTs, compact) {
  const meta = text("div", "meta", "");
  if (!compact) meta.append(text("span", "", "#" + t.id));
  const d = due(t.due_at, nowTs);
  meta.append(text("span", "due " + d.cls, d.label));
  if (t.urgency === "alta") meta.append(text("span", "tag alta", "Urgente"));
  else if (!compact && t.urgency === "baja") meta.append(text("span", "tag", "Baja"));
  if (t.repeat_minutes) meta.append(text("span", "tag", "🔁 " + interval(t.repeat_minutes)));
  return meta;
}
function taskRow(t, steps, nowTs) {
  const row = text("div", "task", "");
  row.append(text("span", "urg " + t.urgency, ""));
  const main = text("div", "task-main", "");
  main.append(text("div", "task-title", t.title), metaLine(t, nowTs, false));
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
      li.append(text("span", "check", ""), text("span", "", s.title));
      if (s.status !== "done") li.append(metaLine(s, nowTs, true));
      list.append(li);
    }
    main.append(progress, list);
  }
  row.append(main);
  return row;
}
function renderTasks(data) {
  const nowTs = data.now;
  const pending = data.pending || [];
  const ids = new Set(pending.map(t => t.id));
  const stepsOf = id => [...pending, ...(data.done_steps || [])].filter(t => t.parent_id === id).sort((a, b) => a.id - b.id);
  const roots = pending.filter(t => t.parent_id === null || !ids.has(t.parent_id));
  const todayEnd = dayStart(new Date(nowTs * 1000)) / 1000 + 86400;
  $("s-pending").textContent = roots.length;
  const steps = pending.length - roots.length;
  $("s-pending-label").textContent = steps ? "Pendientes · " + steps + (steps === 1 ? " paso" : " pasos") : "Pendientes";
  $("s-urgent").textContent = pending.filter(t => t.urgency === "alta").length;
  const overdue = pending.filter(t => t.due_at && t.due_at < nowTs).length;
  $("s-overdue").textContent = overdue;
  $("s-overdue-box").classList.toggle("alert", overdue > 0);
  $("s-today").textContent = pending.filter(t => t.due_at && t.due_at >= nowTs && t.due_at < todayEnd).length;
  $("updated").textContent = "Actualizado " + new Date(nowTs * 1000).toLocaleTimeString("es", { hour: "2-digit", minute: "2-digit" });

  const categories = [...new Set([...(data.categories || []), ...roots.map(t => t.category)])];
  const counts = Object.fromEntries(categories.map(c => [c, roots.filter(t => t.category === c).length]));
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
  chip("todas", "Todas", roots.length);
  categories.filter(c => counts[c]).forEach(c => chip(c, c.charAt(0).toUpperCase() + c.slice(1), counts[c]));

  const groups = $("groups"); groups.replaceChildren();
  const visible = categories.filter(c => counts[c] && (filter === "todas" || filter === c));
  if (!visible.length) {
    const empty = text("div", "empty-state card", "");
    empty.append(text("b", "", "No tienes tareas pendientes"), text("span", "", "Escríbele o háblale a Hermes para anotar algo."));
    groups.append(empty);
  }
  for (const c of visible) {
    const card = text("div", "card group", "");
    const head = text("div", "group-head", "");
    const dot = text("span", "dot", ""); dot.style.setProperty("--cat", catColor(c));
    head.append(dot, text("span", "name", c), text("em", "", counts[c] + (counts[c] === 1 ? " tarea" : " tareas")));
    card.append(head);
    roots.filter(t => t.category === c).sort(sortTasks).forEach(t => card.append(taskRow(t, stepsOf(t.id), nowTs)));
    groups.append(card);
  }

  const finished = data.finished || [];
  $("finished-title").textContent = "Completadas en los últimos 7 días (" + finished.length + ")";
  const list = $("finished"); list.replaceChildren();
  if (!finished.length) list.append(text("div", "empty", "Nada todavía."));
  for (const f of finished) {
    const item = document.createElement("div");
    item.append(
      text("span", "", f.status === "done" ? "✓" : "✕"),
      text("span", "", f.title),
      text("span", "when", new Date(f.completed_at * 1000).toLocaleDateString("es", { weekday: "short", day: "numeric", month: "short" }))
    );
    list.append(item);
  }
}
let tasksSerialized = "";
async function loadTasks() {
  try {
    const res = await fetch("/tasks", { cache: "no-store" });
    const data = await res.json();
    const serialized = JSON.stringify({ ...data, now: Math.floor(data.now / 60) });
    if (serialized !== tasksSerialized || !lastTasks) { tasksSerialized = serialized; lastTasks = data; renderTasks(data); }
  } catch { $("offline").style.display = "block"; }
}
setInterval(() => { if (currentView() === "tareas") loadTasks(); }, 5000);

/* ---------- En vivo ---------- */
const STATES = {
  inactiva: ["Inactiva", "La voz en casa no está disponible."],
  escuchando: ["Escuchando", "Di “Hermes”. Nada se graba hasta entonces."],
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
  $("u-cost").textContent = usd(month.claude ? month.claude.cost : 0).replace(/(\.\d\d)\d\d$/, "$1");
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
let orbLevel = 0;
function updateOrb(s) {
  const orb = $("orb");
  orb.dataset.state = s.state;
  // Nivel relativo al umbral de voz: el ruido de fondo apenas mueve los anillos, la voz los enciende.
  const reference = Math.max(s.threshold || 250, 1) * 1.6;
  const target = s.state === "inactiva" ? 0 : Math.min(1, Math.sqrt((s.level || 0) / reference));
  orbLevel = orbLevel * 0.45 + target * 0.55;
  orb.style.setProperty("--level", orbLevel.toFixed(3));
}
async function tick() {
  try {
    const res = await fetch("/status", { cache: "no-store" });
    const s = await res.json();
    $("offline").style.display = "none";
    const [title, hint] = STATES[s.state] || [s.state, ""];
    $("pill").classList.toggle("on", s.state !== "inactiva");
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
    $("offline").style.display = "block";
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


def make_handler(status: VoiceStatus, port: int) -> type[BaseHTTPRequestHandler]:
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, content_type: str, body: bytes) -> None:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; img-src 'self'",
            )
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            # Valida el Host para que una web externa no pueda leer esto mediante DNS rebinding.
            path = urlsplit(self.path).path
            if self.headers.get("Host") not in allowed_hosts:
                self._send(403, "text/plain; charset=utf-8", b"Solo desde esta computadora.")
            elif path == "/":
                self._send(200, "text/html; charset=utf-8", PAGE.encode("utf-8"))
            elif path == "/logo.webp" and LOGO_PATH.exists():
                self._send(200, "image/webp", LOGO_PATH.read_bytes())
            elif path == "/status":
                self._send(200, "application/json", json.dumps(status.snapshot()).encode("utf-8"))
            elif path in ("/tasks", "/usage", "/history"):
                self._send(200, "application/json", json.dumps(status.read(path[1:])).encode("utf-8"))
            else:
                self._send(404, "text/plain; charset=utf-8", b"No encontrado.")

        def log_message(self, *_: Any) -> None:
            pass

    return Handler


class StatusServer(ThreadingHTTPServer):
    allow_reuse_address = False  # En Windows, reutilizar dejaría a dos programas en el mismo puerto.
    daemon_threads = True


def start_status_server(status: VoiceStatus, port: int) -> ThreadingHTTPServer | None:
    try:
        server = StatusServer(("127.0.0.1", port), make_handler(status, port))
    except OSError as exc:
        log.warning("No se pudo abrir la página de estado: %s", exc)
        return None
    threading.Thread(target=server.serve_forever, daemon=True, name="status-page").start()
    log.info("Página de estado en http://127.0.0.1:%d", port)
    return server
