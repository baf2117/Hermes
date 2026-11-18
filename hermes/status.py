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
        "background_color": "#56646A",
        "theme_color": "#56646A",
        "icons": [
            {"src": "/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png"},
        ],
    }
).encode("utf-8")
# Lo que el teléfono pide para instalar la página como app. No dice nada privado: el nombre y el ícono.
PUBLIC_FILES = {"/icon-192.png": "image/png", "/icon-512.png": "image/png"}
# Tipografía de la página. Lista cerrada (clave exacta, sin recorrer carpetas) y fuera de PUBLIC_FILES:
# por el acceso remoto solo se entrega con sesión aprobada, como la página.
FONTS = ASSETS / "fonts"
FONT_FILES = {"/fonts/atkinson-hyperlegible-next.woff2": "atkinson-hyperlegible-next-latin.woff2"}


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
<meta name="theme-color" media="(prefers-color-scheme: light)" content="#F4F6F6">
<meta name="theme-color" media="(prefers-color-scheme: dark)" content="#101416">
<meta name="robots" content="noindex">
<title>Hermes</title>
<meta name="hermes-token" content="__CSRF_TOKEN__">
<link rel="manifest" href="/manifest.webmanifest" crossorigin="use-credentials">
<link rel="icon" type="image/png" href="/icon-192.png">
<link rel="apple-touch-icon" href="__TOUCH_ICON__">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="default">
<meta name="apple-mobile-web-app-title" content="Hermes">
<style>
:root {
  /* Tokens de docs/design.md (modo claro). Los controles nativos siguen el modo del sistema. */
  color-scheme:light dark;
  --bg:#F4F6F6; --surface:#FFFFFF; --surface-soft:#EAEEEF; --line:#DCE2E4; --line-strong:#7C898E;
  --ink:#142023; --ink-2:#3D4A4F; --ink-3:#5F6C72;
  --accent:#17697A; --accent-ink:#FFFFFF; --accent-soft:color-mix(in oklab, var(--accent) 12%, var(--surface)); --focus:var(--accent);
  --ok:#2D7A2F; --warn:#8A5A00; --danger:#B42318; --danger-soft:color-mix(in oklab, var(--danger) 10%, var(--surface));
  --data-1:#3A5FCD; --data-2:#C26A00;
  --scrim:rgb(16 20 22 / .5); --shadow-float:0 8px 24px rgb(20 32 35 / .16); --cat-mix:65%;
  --u-alta:var(--danger); --u-media:var(--ink-2); --u-baja:var(--ink-3);
  --c-trabajo:#3567b5; --c-negocios:#7a4fb3; --c-casa:#b36b2a; --c-personal:#2f8a87;
  --c-salud:#c0436b; --c-finanzas:#4b7d2f; --c-reptiles:#6d7a1f; --c-otra:#7b7870;
  --font:"Atkinson Hyperlegible Next", system-ui, -apple-system, "Segoe UI Variable Text", "Segoe UI", sans-serif;
  --fs-xs:13px; --fs-sm:14px; --fs-md:16px; --fs-lg:20px; --fs-xl:24px;
  --sp-0:2px; --sp-1:4px; --sp-2:8px; --sp-3:12px; --sp-4:16px; --sp-5:24px; --sp-6:32px; --sp-7:48px;
  --w-page:1040px; --w-col:720px;
  --r-sm:6px; --r-md:10px; --r-lg:14px; --r-full:999px;
  --dur-1:120ms; --dur-2:200ms; --dur-3:240ms;
  --ease-out:cubic-bezier(.23,1,.32,1); --ease-io:cubic-bezier(.77,0,.175,1); --ease:ease;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg:#101416; --surface:#171C1F; --surface-soft:#20272A; --line:#2A3236; --line-strong:#6A777D;
    --ink:#E8EEEF; --ink-2:#AAB6BA; --ink-3:#8A979C;
    --accent:#5CC3D6; --accent-ink:#0B1A1E;
    --ok:#6CC36F; --warn:#E0B04A; --danger:#F2836F;
    --data-1:#7F9BF0; --data-2:#E89A3C;
    --scrim:rgb(0 0 0 / .6); --shadow-float:0 8px 24px rgb(0 0 0 / .5); --cat-mix:55%;
    --c-trabajo:#7aa5ec; --c-negocios:#b496e8; --c-casa:#e3a46a; --c-personal:#5fc4c0;
    --c-salud:#ec86a7; --c-finanzas:#93c56f; --c-reptiles:#b8c55a; --c-otra:#a3a198;
  }
}
/* Base: tipografía propia, servida por la propia página (font-src 'self'); si no carga, la del sistema. */
@font-face {
  font-family:"Atkinson Hyperlegible Next";
  src:url("/fonts/atkinson-hyperlegible-next.woff2") format("woff2");
  font-weight:200 800; font-style:normal; font-display:swap;
}
* { box-sizing:border-box; }
/* Marco — cabecera, pestañas, indicador de conexión, contenido, subpestañas, botones, campos, foco, aviso emergente y franja «Hermes no responde» (docs/design.md, Componentes clave). */
html { -webkit-text-size-adjust:100%; }
body { margin:0; background:var(--bg); color:var(--ink); font:var(--fs-md)/1.5 var(--font); }
a, button, input, select, textarea, summary { -webkit-tap-highlight-color:transparent; touch-action:manipulation; }
/* Foco: anillo de 2 px con 2 px de separación en todo control. */
:focus-visible { outline:2px solid var(--focus); outline-offset:2px; }
/* Cabecera opaca: marca a la izquierda, indicador a la derecha; las pestañas se subrayan contra el borde inferior. */
header { position:sticky; top:0; z-index:5; background:var(--bg); border-bottom:1px solid var(--line); padding-top:env(safe-area-inset-top); }
.bar { max-width:var(--w-page); min-height:56px; margin:0 auto; padding:0 max(var(--sp-4), env(safe-area-inset-right)) 0 max(var(--sp-4), env(safe-area-inset-left));
  display:flex; align-items:stretch; flex-wrap:wrap; gap:0 var(--sp-4); }
.brand { align-self:center; margin-right:auto; padding:var(--sp-3) 0; display:flex; align-items:center; gap:var(--sp-2); font-size:var(--fs-lg); font-weight:600; line-height:1.3; }
/* Marca: el monograma del logo (docs/logo.svg) en el acento del modo activo. */
.brand-mark { flex:none; width:20px; height:20px; }
.brand-mark .bm-bg { fill:var(--accent); }
.brand-mark .bm-fg { fill:var(--accent-ink); }
.tabs { display:flex; gap:var(--sp-1); max-width:100%; overflow-x:auto; scrollbar-width:none; }
.tabs::-webkit-scrollbar { display:none; }
.tabs a { flex:none; display:inline-flex; align-items:center; min-height:44px; padding:0 var(--sp-3); border-bottom:2px solid transparent;
  color:var(--ink-2); font-size:var(--fs-md); font-weight:500; text-decoration:none; white-space:nowrap; }
.tabs a:focus-visible { outline-offset:-2px; border-radius:var(--r-sm); }
.tabs a[aria-current="page"] { color:var(--ink); font-weight:600; border-bottom-color:var(--accent); }
/* Indicador de conexión: punto gris en reposo, lleno en verde con conexión y hueco en rojo sin ella (la forma también cambia). */
.pill { align-self:center; display:flex; align-items:center; gap:var(--sp-2); padding:var(--sp-3) 0; color:var(--ink-2); font-size:var(--fs-sm); }
.pill i { flex:none; display:inline-block; width:8px; height:8px; border-radius:var(--r-full); background:var(--ink-3); }
.pill.on i { background:var(--ok); }
.pill.off i { background:transparent; border:2px solid var(--danger); }
/* Contenido: ancho máximo de vista y margen inferior reservado para el aviso y el botón de hablar. */
main { max-width:var(--w-page); margin:0 auto;
  padding:var(--sp-5) max(var(--sp-4), env(safe-area-inset-right)) calc(var(--sp-7) * 2 + env(safe-area-inset-bottom)) max(var(--sp-4), env(safe-area-inset-left)); }
body.can-speak main { padding-bottom:calc(var(--sp-7) * 3 + var(--sp-4) + env(safe-area-inset-bottom)); }
.view[hidden] { display:none; }
h2 { margin:var(--sp-1) 0 var(--sp-0); font-size:var(--fs-xl); font-weight:600; line-height:1.25; }
.subtitle { max-width:70ch; margin-bottom:var(--sp-4); color:var(--ink-2); font-size:var(--fs-sm); line-height:1.4; }
section, .card { background:var(--surface); border:1px solid var(--line); border-radius:var(--r-lg); }
section { padding:var(--sp-5); margin-bottom:var(--sp-4); }
.label { margin-bottom:var(--sp-2); color:var(--ink-2); font-size:var(--fs-sm); font-weight:500; line-height:1.4; }
.empty { color:var(--ink-2); }
/* «Hermes no responde»: franja en el flujo, al principio de main (el script la muestra con display:block). */
#offline { display:none; margin:0 0 var(--sp-4); padding:var(--sp-3) var(--sp-4); border-radius:var(--r-md); background:var(--danger-soft); color:var(--ink); }
#offline svg { width:20px; height:20px; margin-right:var(--sp-2); vertical-align:-4px; color:var(--danger); }
/* Subpestañas: píldoras en una fila que se desplaza por dentro; la activa, con fondo, borde de acento y más peso. */
.subtabs { display:flex; gap:var(--sp-2); margin:0 calc(-1 * var(--sp-1)) var(--sp-3); padding:var(--sp-1); overflow-x:auto; scrollbar-width:none; }
.subtabs::-webkit-scrollbar { display:none; }
.subtabs a { flex:none; display:inline-flex; align-items:center; gap:var(--sp-2); min-height:36px; padding:0 var(--sp-4); border:1px solid var(--line); border-radius:var(--r-full);
  background:var(--surface); color:var(--ink-2); font-size:var(--fs-sm); font-weight:500; text-decoration:none; white-space:nowrap; }
.subtabs a[aria-current="page"] { background:var(--accent-soft); border-color:var(--accent); color:var(--ink); font-weight:600; }
.subtabs a span { color:var(--ink-2); font-size:var(--fs-xs); font-weight:400; font-variant-numeric:tabular-nums; }
.subtabs a span:empty { display:none; }
/* Botones: principal (acento), secundario (.ghost), peligro (.danger) y de icono (.icon-btn). */
.primary, .ghost, .danger { display:inline-flex; align-items:center; justify-content:center; gap:var(--sp-2); min-height:36px; padding:0 var(--sp-4);
  font:inherit; font-size:var(--fs-md); line-height:1.25; border-radius:var(--r-md); cursor:pointer;
  transition:background-color var(--dur-1) var(--ease), border-color var(--dur-1) var(--ease), transform var(--dur-1) var(--ease-out); }
.primary { margin-left:auto; color:var(--accent-ink); background:var(--accent); border:1px solid var(--accent); font-weight:600; }
.ghost { color:var(--ink); background:var(--surface); border:1px solid var(--line-strong); white-space:nowrap; }
.danger { margin-right:auto; color:var(--danger); background:var(--surface); border:1px solid var(--line-strong); }
.primary:disabled, .ghost:disabled, .danger:disabled { color:var(--ink-3); background:var(--surface-soft); border-color:var(--surface-soft); cursor:default; }
.icon-btn { margin-left:auto; display:inline-grid; place-items:center; min-width:32px; min-height:32px; padding:0 var(--sp-2);
  font:inherit; font-size:var(--fs-md); line-height:1; color:var(--ink-2); background:transparent; border:0; border-radius:var(--r-md); cursor:pointer;
  transition:background-color var(--dur-1) var(--ease), color var(--dur-1) var(--ease), transform var(--dur-1) var(--ease-out); }
.icon-btn:disabled { color:var(--ink-3); cursor:default; }
.primary:active:not(:disabled), .ghost:active:not(:disabled), .danger:active:not(:disabled), .icon-btn:active:not(:disabled) { transform:scale(.97); }
@media (hover:hover) and (pointer:fine) {
  .tabs a:hover, .subtabs a:hover { color:var(--ink); }
  .subtabs a:hover { border-color:var(--line-strong); }
  .primary:hover:not(:disabled) { background:color-mix(in oklab, var(--accent) 92%, var(--ink)); border-color:color-mix(in oklab, var(--accent) 92%, var(--ink)); }
  .ghost:hover:not(:disabled) { background:var(--surface-soft); }
  .danger:hover:not(:disabled) { border-color:var(--danger); }
  .icon-btn:hover:not(:disabled) { color:var(--ink); background:var(--surface-soft); }
}
/* En oscuro, «más oscuro» se mezcla con el fondo (la tinta es clara). */
@media (hover:hover) and (pointer:fine) and (prefers-color-scheme: dark) {
  .primary:hover:not(:disabled) { background:color-mix(in oklab, var(--accent) 92%, var(--bg)); border-color:color-mix(in oklab, var(--accent) 92%, var(--bg)); }
}
/* Campos: base común sin especificidad (:where), para que las vistas aún sin migrar conserven sus ajustes. */
:where(input:not([type="checkbox"], [type="radio"], [type="color"], [type="range"], [type="file"], [type="hidden"]), select, textarea) {
  min-height:44px; padding:var(--sp-2) var(--sp-3); font:inherit; font-size:var(--fs-md); color:var(--ink);
  background:var(--surface); border:1px solid var(--line-strong); border-radius:var(--r-md); }
:where(input, textarea)::placeholder { color:var(--ink-3); opacity:1; }
:where(input:not([type="checkbox"], [type="radio"], [type="color"], [type="range"], [type="file"], [type="hidden"]), select, textarea):focus-visible { border-color:var(--accent); }
:where(input, select, textarea):disabled { opacity:.5; background:var(--surface-soft); cursor:default; }
:where(input, select, textarea)[aria-invalid="true"] { border-color:var(--danger); }
/* Safari del iPhone da a los campos de hora y fecha un ancho propio que ignora width:100% y se sale de la tarjeta. */
input[type="time"], input[type="date"], input[type="datetime-local"] { -webkit-appearance:none; appearance:none; min-width:0; max-width:100%; min-height:44px; }
input::-webkit-date-and-time-value { text-align:left; }
/* Aviso emergente: abajo y centrado, por encima del botón de hablar; entra en --dur-2 y sale un 20 % más rápido. */
.toast { position:fixed; left:0; right:0; bottom:calc(var(--sp-5) + env(safe-area-inset-bottom)); z-index:20; width:max-content; max-width:calc(100vw - 2 * var(--sp-4)); margin:0 auto;
  display:flex; align-items:center; gap:var(--sp-3); padding:var(--sp-2) var(--sp-4); background:var(--surface); color:var(--ink);
  border:1px solid var(--line-strong); border-radius:var(--r-lg); box-shadow:var(--shadow-float); font-size:var(--fs-md); white-space:pre-line;
  opacity:0; transform:translateY(8px); pointer-events:none;
  transition:opacity calc(var(--dur-2) * .8) var(--ease-out), transform calc(var(--dur-2) * .8) var(--ease-out); }
.toast.show { opacity:1; transform:none; pointer-events:auto; transition-duration:var(--dur-2); }
.toast button { min-height:32px; padding:0 var(--sp-1); font:inherit; font-weight:600; color:var(--accent); background:none; border:0; border-radius:var(--r-sm); cursor:pointer; white-space:nowrap; }
.toast button[hidden] { display:none; }
body.can-speak .toast { bottom:calc(var(--sp-7) * 2 + env(safe-area-inset-bottom)); }
/* Táctil o pantalla estrecha: zonas de 44×44 px. */
@media (pointer:coarse), (max-width:640px) {
  .primary, .ghost, .danger, .subtabs a { min-height:44px; }
  .icon-btn, .toast button { min-width:44px; min-height:44px; }
}
@media (max-width:640px) {
  .tabs { order:3; width:100%; }
  .tabs a { flex:1 0 auto; justify-content:center; }
  main { padding-top:var(--sp-4); }
  section { padding:var(--sp-4); }
}
@media (prefers-reduced-motion: reduce) {
  .toast, .toast.show { transform:none; }
  .primary:active:not(:disabled), .ghost:active:not(:disabled), .danger:active:not(:disabled), .icon-btn:active:not(:disabled) { transform:none; }
}

/* Tareas — contadores, Lista/Calendario, filtros, grupos, tarjetas, pasos, terminadas y estados de carga y vacío (docs/design.md, Vistas; RF-19 a RF-23, RF-35).
   El estado vive en el glifo, no en la fila: urgencia en una columna fija (triángulo, círculo lleno o hueco),
   «Urgente» y «Vencida · …» en --danger y 600, hecha con la casilla llena y el título tachado. Sin sombras ni
   filas de color; el color de categoría, solo como punto atenuado. */
.sr-only { position:absolute; width:1px; height:1px; margin:0; padding:0; overflow:hidden; clip-path:inset(50%); white-space:nowrap; border:0; }
/* Caja de escribir: la acción principal de la vista. */
.say { display:flex; gap:var(--sp-2); margin:0 0 var(--sp-4); }
.say input { flex:1; min-width:0; }
.say .primary { flex:none; margin-left:0; min-height:44px; }
/* Contadores por estado: botones con cifra tabular; el elegido, con borde de acento de 2 px y fondo. */
#stats { display:grid; grid-template-columns:repeat(5, minmax(0, 1fr)); gap:var(--sp-3); margin:0 0 var(--sp-4); }
#stats > * { min-width:0; }
#stats .stat { display:flex; flex-direction:column; align-items:flex-start; gap:var(--sp-0); width:100%; min-width:0; padding:var(--sp-3) var(--sp-4);
  font:inherit; color:var(--ink); text-align:left; background:var(--surface); border:1px solid var(--line); border-radius:var(--r-lg); box-shadow:none; cursor:pointer; }
#stats .stat b { display:block; font-size:var(--fs-xl); font-weight:600; line-height:1.25; font-variant-numeric:tabular-nums; }
#stats .stat span { max-width:100%; color:var(--ink-3); font-size:var(--fs-sm); font-weight:500; line-height:1.4; overflow-wrap:anywhere; }
#stats .stat[aria-pressed="true"] { padding:calc(var(--sp-3) - var(--sp-0) / 2) calc(var(--sp-4) - var(--sp-0) / 2); background:var(--accent-soft); border:2px solid var(--accent); }
#stats .stat[aria-pressed="true"] span { color:var(--ink-2); }
#stats .stat.alert b { color:var(--danger); }
/* Lista o Calendario: control segmentado; el activo, con superficie, borde y más peso. */
.mode { display:inline-flex; flex-wrap:wrap; max-width:100%; gap:var(--sp-1); margin:0 0 var(--sp-3); padding:var(--sp-1); background:var(--surface-soft); border-radius:var(--r-md); }
.mode button { min-height:36px; padding:0 var(--sp-4); font:inherit; font-size:var(--fs-md); font-weight:500; color:var(--ink-2);
  background:transparent; border:1px solid transparent; border-radius:var(--r-sm); cursor:pointer; }
.mode button[aria-pressed="true"] { color:var(--ink); background:var(--surface); border-color:var(--line-strong); font-weight:600; }
/* Filtros por categoría: píldoras como las subpestañas, con el punto de la categoría atenuado. */
.filters { display:flex; flex-wrap:wrap; gap:var(--sp-2); margin:0 0 var(--sp-4); }
.filters button { flex:none; display:inline-flex; align-items:center; gap:var(--sp-2); min-height:36px; padding:0 var(--sp-4);
  font:inherit; font-size:var(--fs-sm); font-weight:500; line-height:1.4; color:var(--ink-2); background:var(--surface);
  border:1px solid var(--line); border-radius:var(--r-full); cursor:pointer; white-space:nowrap; }
.filters button[aria-pressed="true"] { color:var(--ink); background:var(--accent-soft); border-color:var(--accent); font-weight:600; }
.filters button em { font-style:normal; color:var(--ink-2); font-size:var(--fs-xs); font-weight:400; font-variant-numeric:tabular-nums; }
.dot { flex:none; width:8px; height:8px; border-radius:var(--r-full); background:color-mix(in oklab, var(--cat, var(--c-otra)) var(--cat-mix), var(--surface)); }
/* Grupos por categoría: tarjeta con cabecera (punto, nombre, cuenta y chevron); dos columnas en pantalla ancha. */
.groups { display:grid; grid-template-columns:repeat(auto-fill, minmax(min(100%, 460px), 1fr)); gap:var(--sp-4); align-items:start; }
.groups > * { min-width:0; }
.group { overflow:hidden; }
.group-head { display:flex; align-items:center; gap:var(--sp-2); min-height:44px; padding:var(--sp-3) var(--sp-4); border-bottom:1px solid var(--line);
  font-size:var(--fs-lg); font-weight:600; line-height:1.3; }
.group-head .name { min-width:0; overflow-wrap:anywhere; text-transform:capitalize; }
button.group-head { width:100%; font:inherit; font-size:var(--fs-lg); font-weight:600; line-height:1.3; color:inherit; text-align:left;
  background:none; border:0; border-bottom:1px solid var(--line); cursor:pointer; }
button.group-head:focus-visible { outline-offset:-2px; }
.group-head .chev { flex:none; width:8px; height:8px; margin:0 var(--sp-1) var(--sp-1); border:solid var(--ink-2); border-width:0 2px 2px 0;
  transform:rotate(45deg); transition:transform var(--dur-1) var(--ease-out); }
.group.closed .group-head { border-bottom:0; }
.group.closed .chev { transform:rotate(-45deg); margin-bottom:0; }
.group-head em { margin-left:auto; color:var(--ink-3); font-size:var(--fs-sm); font-style:normal; font-weight:500; white-space:nowrap; font-variant-numeric:tabular-nums; }
/* Tarjeta de tarea: glifo de urgencia, casilla y título en una fila de 32 px (44 en táctil); los metadatos debajo. */
.task { display:flex; align-items:flex-start; gap:var(--sp-2); padding:var(--sp-1) var(--sp-4) var(--sp-3); border-top:1px solid var(--line); }
.task:first-of-type, .group-head + .task { border-top:0; }
.urg { flex:none; display:grid; place-items:center; width:10px; height:32px; }
.urg::before { content:""; width:8px; height:8px; border-radius:var(--r-full); background:var(--u-media); }
.urg.alta::before { width:10px; height:10px; border-radius:0; background:var(--u-alta); clip-path:polygon(50% 0, 100% 100%, 0 100%); }
.urg.baja::before { background:transparent; border:2px solid var(--u-baja); }
.task-main { flex:1; min-width:0; }
.task-main.clickable { cursor:pointer; }
.task-title { display:flex; align-items:center; min-height:32px; font-weight:500; line-height:1.5; overflow-wrap:anywhere; }
.task-title.linkish { width:100%; font-weight:500; }
.task-title.linkish span { display:-webkit-box; -webkit-box-orient:vertical; -webkit-line-clamp:2; overflow:hidden; }
.task.ended .task-title { color:var(--ink-3); text-decoration:line-through; }
.task.ended .urg { height:32px; }
.meta { display:flex; flex-wrap:wrap; align-items:center; gap:var(--sp-1) var(--sp-3); color:var(--ink-3); font-size:var(--fs-xs); line-height:1.4; }
.task-main > .meta + .meta { margin-top:var(--sp-1); }
.tag { padding:0 var(--sp-2); border-radius:var(--r-sm); background:var(--surface-soft); color:var(--ink-2); font-size:var(--fs-xs); }
.tag.alta { color:var(--danger); font-weight:600; }
.tag.ok { color:var(--ok); font-weight:600; }
.due.overdue { color:var(--danger); font-weight:600; }
.due.today { color:var(--ink); font-weight:600; }
/* Progreso de los pasos: barra neutra (el acento no marca progreso). */
.progress { display:flex; align-items:center; gap:var(--sp-3); margin-top:var(--sp-2); color:var(--ink-3); font-size:var(--fs-xs); }
.track { flex:1; height:6px; overflow:hidden; background:var(--surface-soft); border-radius:var(--r-full); }
.track div { height:100%; background:var(--ink-3); border-radius:var(--r-full); }
.steps { list-style:none; margin:var(--sp-1) 0 0; padding:0; }
.steps li { display:flex; flex-wrap:wrap; align-items:center; gap:0 var(--sp-2); font-size:var(--fs-sm); }
.steps li.done { color:var(--ink-3); text-decoration:line-through; }
.steps .linkish { flex:1 1 auto; min-width:0; min-height:32px; display:flex; align-items:center; }
.steps li .meta, .steps .meta { margin:0 0 0 auto; font-size:var(--fs-xs); }
.check { flex:none; width:14px; height:14px; border:2px solid var(--line-strong); border-radius:var(--r-full); }
.steps li.done .check { background:var(--accent); border-color:var(--accent); }
/* Casilla de hecha (también en los pasos y en el editor): círculo de 22 px con borde --line-strong (≥ 3:1) en una
   zona de 32 px (44 en táctil). Marcada: el span del ✓ se ve como círculo lleno de acento. */
.tick { position:relative; flex:none; display:grid; place-items:center; width:32px; height:32px; padding:0; font:inherit; font-size:var(--fs-xs); line-height:1;
  color:var(--ink); background:transparent; border:0; border-radius:var(--r-full); cursor:pointer; }
.tick::before { content:""; position:absolute; inset:0; width:22px; height:22px; margin:auto; border:2px solid var(--line-strong); border-radius:var(--r-full); }
.tick span { position:relative; display:grid; place-items:center; width:22px; height:22px; border-radius:var(--r-full); font-weight:600; visibility:hidden; }
.tick[aria-pressed="true"]::before { border-color:var(--accent); }
.tick[aria-pressed="true"] span { visibility:visible; color:var(--accent-ink); background:var(--accent); }
.tick:disabled { cursor:default; opacity:.5; }
.steps .tick::before, .steps .tick span { width:18px; height:18px; }
/* Botones con forma de texto: el título de la tarea y los pasos. */
.linkish { padding:0; font:inherit; color:inherit; text-align:left; background:none; border:0; cursor:pointer; overflow-wrap:anywhere; }
.linkish:disabled { cursor:default; }
/* Terminadas: volver a pendientes y borrar. */
.fin-actions { display:flex; flex-wrap:wrap; gap:var(--sp-2) var(--sp-5); margin-top:var(--sp-2); }
.undo { display:inline-flex; align-items:center; min-height:32px; padding:0; font:inherit; font-size:var(--fs-sm); font-weight:500; color:var(--ink-2);
  text-decoration:underline; background:none; border:0; border-radius:var(--r-sm); cursor:pointer; white-space:nowrap; }
.undo.danger-link { color:var(--danger); }
.fin-mark { flex:none; width:18px; color:var(--ink-2); }
/* Vacío: centrado, con el mismo texto de hoy. Carga: esqueleto quieto de 3 filas, sin animación. */
.empty-state { grid-column:1 / -1; display:flex; flex-direction:column; align-items:center; gap:var(--sp-1); padding:var(--sp-7) var(--sp-4);
  color:var(--ink-2); font-size:var(--fs-sm); line-height:1.4; text-align:center; }
.empty-state b { color:var(--ink); font-size:var(--fs-md); font-weight:600; line-height:1.5; }
.skeleton { grid-column:1 / -1; display:flex; flex-direction:column; gap:var(--sp-2); }
.skeleton i { display:block; height:56px; background:var(--surface-soft); border-radius:var(--r-lg); }
/* Calendario mensual (Tareas y Fechas): números tabulares; hoy en neutro invertido; el día elegido con borde de acento. */
.cal { margin:0 0 var(--sp-4); padding:var(--sp-3); background:var(--surface); border:1px solid var(--line); border-radius:var(--r-lg); }
.cal-head { display:flex; align-items:center; gap:var(--sp-2); margin-bottom:var(--sp-2); }
.cal-head b { flex:1; min-width:0; font-size:var(--fs-md); font-weight:600; text-align:center; text-transform:capitalize; }
.cal-nav { flex:none; display:inline-grid; place-items:center; min-width:36px; min-height:36px; padding:0 var(--sp-3); font:inherit; font-size:var(--fs-md); line-height:1;
  color:var(--ink); background:var(--surface); border:1px solid var(--line-strong); border-radius:var(--r-md); cursor:pointer; }
.cal-grid { display:grid; grid-template-columns:repeat(7, minmax(0, 1fr)); gap:var(--sp-1); }
.cal-wd { padding:var(--sp-1) 0; color:var(--ink-3); font-size:var(--fs-xs); text-align:center; }
.cal-day { min-width:0; min-height:72px; padding:var(--sp-1); display:flex; flex-direction:column; align-items:stretch; gap:var(--sp-0); overflow:hidden;
  font:inherit; color:var(--ink); text-align:left; background:none; border:1px solid transparent; border-radius:var(--r-md); cursor:pointer; }
.cal-day .n { flex:none; display:grid; place-items:center; width:24px; height:24px; border-radius:var(--r-full); font-size:var(--fs-xs); font-weight:600; font-variant-numeric:tabular-nums; }
.cal-day.today .n { color:var(--bg); background:var(--ink); }
.cal-day.picked { background:var(--accent-soft); border-color:var(--accent); }
.cal-day .m { padding:0 var(--sp-1); overflow:hidden; color:var(--ink-2); font-size:var(--fs-xs); line-height:1.4; white-space:nowrap; text-overflow:ellipsis;
  background:var(--surface-soft); border-radius:var(--r-sm); }
.cal-day.picked .m { background:var(--surface); }
.cal-day .m.alta, .cal-day .m.late { color:var(--danger); font-weight:600; }
.cal-day .more { padding-left:var(--sp-1); color:var(--ink-2); font-size:var(--fs-xs); }
.cal-day .dots { display:none; justify-content:center; gap:var(--sp-0); }
.cal-day .dots i { width:6px; height:6px; border-radius:var(--r-full); background:var(--ink-3); }
.cal-day .dots i.alta, .cal-day .dots i.late { background:var(--danger); }
.cal-none { padding:var(--sp-3) var(--sp-4); color:var(--ink-2); font-size:var(--fs-sm); }
@media (hover:hover) and (pointer:fine) {
  #stats .stat:not([aria-pressed="true"]):hover { border-color:var(--line-strong); }
  .mode button:not([aria-pressed="true"]):hover { color:var(--ink); }
  .filters button:not([aria-pressed="true"]):hover { color:var(--ink); border-color:var(--line-strong); }
  button.group-head:hover { background:var(--surface-soft); }
  .task-main.clickable:hover .task-title { text-decoration:underline; }
  .tick:not(:disabled):hover::before { border-color:var(--accent); }
  .tick:not([aria-pressed="true"]):not(:disabled):hover span { visibility:visible; color:var(--accent); }
  .undo:hover { color:var(--ink); }
  .undo.danger-link:hover { color:var(--danger); }
  .cal-nav:hover { background:var(--surface-soft); }
  .cal-day:not(.picked):hover { background:var(--surface-soft); }
}
/* Táctil o pantalla estrecha: zonas de 44×44 px (la casilla, el título y los pasos crecen; el dibujo no). */
@media (pointer:coarse), (max-width:640px) {
  .mode button, .filters button, .undo { min-height:44px; }
  .undo { min-width:44px; justify-content:center; }
  .cal-nav { min-width:44px; min-height:44px; }
  .tick { width:44px; height:44px; }
  .urg { height:44px; }
  .task.ended .urg { height:32px; }
  .task-title.linkish, .steps .linkish { min-height:44px; }
}
@media (max-width:640px) {
  #stats { grid-template-columns:repeat(2, minmax(0, 1fr)); gap:var(--sp-2); }
  #stats .stat:last-child { grid-column:1 / -1; }
  .filters { flex-wrap:nowrap; margin:0 calc(-1 * var(--sp-1)) var(--sp-3); padding:var(--sp-1); overflow-x:auto; scrollbar-width:none; }
  .filters::-webkit-scrollbar { display:none; }
  .task { gap:var(--sp-1); padding:0 var(--sp-3) var(--sp-3); }
  .group-head { padding-left:var(--sp-3); padding-right:var(--sp-3); }
  /* Siete días caben a 375 px (también con barra de desplazamiento) con celdas de al menos 44×48: sin relleno y 2 px de separación. */
  .cal { padding:0; }
  .cal-head { padding:var(--sp-1) var(--sp-1) 0; }
  .cal-grid { gap:var(--sp-0); }
  .cal-day { min-height:48px; align-items:center; padding:var(--sp-1) 0; }
  .cal-day .m, .cal-day .more { display:none; }
  .cal-day .dots { display:flex; }
}
@media (prefers-reduced-motion: reduce) {
  .group-head .chev { transition:none; }
}

/* Consumo — cifras, gráfico de 14 días con leyenda y tooltip, vista como tabla, tablas y estado de carga (docs/design.md, Vistas;
   RF-12, RF-25, RF-43, RF-47, RF-49, RF-50). Los colores de datos solo se usan aquí: en las barras, la leyenda y el tooltip.
   La serie 2 (Modelo local) va además rayada y siempre encima de Claude, separada 2 px: se distingue sin el color.
   La acción principal, «Ver como tabla», es lo único con acento (borde y texto, como la navegación de mes de Gastos).
   Toda cifra, con cifras tabulares. Sin transiciones en cifras, columnas ni tooltip. */
/* Cifras: como los contadores de Tareas, sin ser botones; dos columnas en pantalla estrecha. */
#view-consumo .stats { display:grid; grid-template-columns:repeat(4, minmax(0, 1fr)); gap:var(--sp-3); margin:0 0 var(--sp-4); }
#view-consumo .stat { display:flex; flex-direction:column; gap:var(--sp-0); min-width:0; padding:var(--sp-3) var(--sp-4);
  background:var(--surface); border:1px solid var(--line); border-radius:var(--r-lg); }
#view-consumo .stat b { display:block; font-size:var(--fs-xl); font-weight:600; line-height:1.25; font-variant-numeric:tabular-nums; overflow-wrap:anywhere; }
#view-consumo .stat span { color:var(--ink-2); font-size:var(--fs-sm); font-weight:500; line-height:1.4; overflow-wrap:anywhere; }
#view-consumo .stat small { display:block; color:var(--ink-3); font-size:var(--fs-xs); line-height:1.4; font-variant-numeric:tabular-nums; }
/* Leyenda: muestra (lisa o rayada, como su barra) y nombre en texto. */
.legend { display:flex; flex-wrap:wrap; gap:var(--sp-1) var(--sp-4); margin:0 0 var(--sp-3); color:var(--ink-2); font-size:var(--fs-sm); line-height:1.4; }
.legend span { display:inline-flex; align-items:center; gap:var(--sp-2); }
.swatch { flex:none; display:inline-block; width:14px; height:14px; border-radius:0; }
/* Series: Claude lisa; Modelo local rayada en diagonal (el color de fondo queda debajo del rayado). */
.swatch.claude, .seg.claude { background-color:var(--data-1); }
.swatch.local, .seg.local { background-color:var(--data-2);
  background-image:repeating-linear-gradient(135deg, var(--data-2) 0 4px, var(--surface) 4px 6px); }
/* Gráfico: 14 columnas que se reparten el ancho, sin huecos entre ellas: cada columna es la zona pulsable de toda su franja
   y a todo el alto (200 px; E1: estrechas, pero ≥ 44 px de alto). Ejes en --fs-xs y --ink-3. */
.chart-box { position:relative; }
.chart { position:relative; height:200px; display:flex; align-items:flex-end; gap:0; margin-left:var(--sp-7); border-bottom:1px solid var(--line-strong); }
.gridline { position:absolute; left:0; right:0; border-top:1px dashed var(--line); }
.gridline span { position:absolute; right:calc(100% + var(--sp-1)); top:calc(-1 * var(--sp-2) - var(--sp-0)); color:var(--ink-3); font-size:var(--fs-xs); line-height:1.4;
  white-space:nowrap; font-variant-numeric:tabular-nums; }
.col { position:relative; z-index:1; flex:1; min-width:0; height:100%; display:flex; align-items:flex-end; justify-content:center; cursor:default; }
.col:focus-visible { outline-offset:-2px; background:var(--surface-soft); }
@media (hover:hover) and (pointer:fine) {
  .col:hover { background:var(--surface-soft); }
}
.stack { width:min(24px, 70%); display:flex; flex-direction:column; gap:var(--sp-0); }
.xlabels { display:flex; gap:0; margin:var(--sp-1) 0 0 var(--sp-7); }
.xlabels span { flex:1; min-width:0; color:var(--ink-3); font-size:var(--fs-xs); line-height:1.4; text-align:center; white-space:nowrap; overflow:hidden;
  font-variant-numeric:tabular-nums; }
/* Tooltip: flota sobre el gráfico (superficie y sombra flotante); se muestra al pasar el ratón, con el foco o al tocar. */
.tooltip { position:absolute; z-index:4; display:none; pointer-events:none; padding:var(--sp-2) var(--sp-3); color:var(--ink); background:var(--surface);
  border:1px solid var(--line); border-radius:var(--r-md); box-shadow:var(--shadow-float); font-size:var(--fs-sm); line-height:1.4;
  width:max-content; max-width:100%; overflow-wrap:anywhere; font-variant-numeric:tabular-nums; }
.tooltip b { display:block; margin-bottom:var(--sp-1); font-weight:600; }
.tooltip div { display:flex; align-items:center; gap:var(--sp-2); color:var(--ink-2); }
.tooltip .swatch { width:10px; height:10px; }
/* Ver como tabla: la acción principal; abierta, con el fondo de lo seleccionado. */
details.table-view { margin-top:var(--sp-3); }
details.table-view summary { display:inline-flex; align-items:center; gap:var(--sp-2); min-height:36px; padding:0 var(--sp-4); color:var(--accent); font-size:var(--fs-md);
  font-weight:600; line-height:1.25; list-style:none; background:var(--surface); border:1px solid var(--accent); border-radius:var(--r-md); cursor:pointer; }
details.table-view summary::-webkit-details-marker { display:none; }
details.table-view summary::before { content:""; width:0; height:0; border-style:solid; border-width:5px 0 5px 7px; border-color:transparent transparent transparent currentColor; }
details.table-view[open] summary { background:var(--accent-soft); }
details.table-view[open] summary::before { transform:rotate(90deg); }
details.table-view .wide { margin-top:var(--sp-3); }
/* Tablas: 14 px y cifras tabulares; si no caben, se desplazan por dentro (la página no). */
.wide { max-width:100%; overflow-x:auto; }
table { width:100%; border-collapse:collapse; font-size:var(--fs-sm); line-height:1.4; font-variant-numeric:tabular-nums; }
th, td { padding:var(--sp-2) 0 var(--sp-2) var(--sp-3); text-align:right; border-top:1px solid var(--line); white-space:nowrap; }
th { color:var(--ink-2); font-weight:500; border-top:0; }
th:first-child, td:first-child { padding-left:0; text-align:left; white-space:normal; }
#recent-calls td:first-child { white-space:nowrap; }  /* La hora no se parte en tres líneas: la tabla se desplaza por dentro. */
/* Dos columnas en pantalla ancha (también la usa Historial). */
.grid2 { display:grid; grid-template-columns:repeat(auto-fit, minmax(min(100%, 420px), 1fr)); gap:var(--sp-4); }
.grid2 > *, .groups > * { min-width:0; }
/* Carga: esqueleto quieto en el sitio del gráfico (el script lo sustituye al pintar el gráfico). */
#chart-box > .skeleton i { height:60px; }
@media (pointer:coarse), (max-width:640px) {
  details.table-view summary { min-height:44px; }
}
@media (max-width:640px) {
  #view-consumo .stats { grid-template-columns:repeat(2, minmax(0, 1fr)); }
  .xlabels span:nth-child(even):not(:first-child) { visibility:hidden; }
  .xlabels span:nth-child(odd) { overflow:visible; }
}
/* Texto al 200 % en el teléfono (~188 px útiles): cifras en una columna y, en el eje, solo el primer y el último día. */
@media (max-width:300px) {
  #view-consumo .stats { grid-template-columns:minmax(0, 1fr); }
  .xlabels span:not(:first-child):not(:last-child) { visibility:hidden; }
  .xlabels span:first-child { text-align:left; }
  .xlabels span:last-child:not(:first-child) { visibility:visible; overflow:visible; direction:rtl; text-align:right; }
}

/* En vivo — indicador con el logo, mensaje y pista, botón del micrófono, medidor y estado de carga (docs/design.md, Vistas;
   RF-9, RF-30, RF-31, RF-45, RF-47). Sin el tema negro y dorado ni degradado: fondo de la página, disco con la superficie
   del modo y anillos finos de acento sin halos. El estado lo nombra el mensaje (texto), no solo el color; en pausa el
   logo queda gris y atenuado y los anillos pasan a --line-strong. Las ondas y el «respirar» son la excepción E3; con
   reducir movimiento no hay ondas, escala ni desplazamiento (el nivel se ve solo en la opacidad de los anillos).
   La acción principal es el botón del micrófono: secundario mientras escucha y principal (acento) en pausa.
   El medidor no tiene transición: se actualiza 5 veces por segundo. */
.stage-wrap { min-height:calc(100vh - 150px); min-height:calc(100dvh - 150px); display:flex; flex-direction:column; align-items:center; justify-content:center;
  gap:var(--sp-4); text-align:center; }
/* Indicador: --level (0..1) lo pone el script según el nivel del micrófono; --glow y --speed dependen del estado. */
.orb { --level:0; --glow:.3; --speed:4s; position:relative; width:min(78vw, 380px); aspect-ratio:1; display:grid; place-items:center; }
.ring { position:absolute; inset:0; border-radius:var(--r-full); border:1.5px solid var(--accent); opacity:min(1, calc(var(--glow) * .6 + var(--level) * .35));
  transform:scale(calc(.6 + var(--i) * .13 + var(--level) * var(--i) * .05));
  transition:transform var(--dur-1) var(--ease-out), opacity var(--dur-1) var(--ease), border-color var(--dur-2) var(--ease); }
/* Ondas (E3): solo escuchando, grabando, pensando y hablando (y sus pasos intermedios); en reposo y en pausa, quietas. */
.ripple { position:absolute; inset:0; border-radius:var(--r-full); border:2px solid var(--accent); opacity:0; animation:ripple var(--speed) var(--ease-out) infinite; }
.ripple.r2 { animation-delay:calc(var(--speed) / -3); }
.ripple.r3 { animation-delay:calc(var(--speed) / -1.5); }
@keyframes ripple { 0% { transform:scale(.5); opacity:calc(var(--glow) * .9); } 100% { transform:scale(1.18); opacity:0; } }
/* Disco con el logo: superficie del modo y borde de control, sin sombra ni resplandor. */
.disc { position:relative; z-index:2; width:44%; aspect-ratio:1; display:grid; place-items:center; overflow:hidden;
  background:var(--surface); border:1px solid var(--line-strong); border-radius:var(--r-full); }
.disc img { width:78%; height:78%; object-fit:contain; user-select:none; transition:opacity var(--dur-2) var(--ease); }
.orb[data-state="inactiva"] { --glow:.06; }
.orb[data-state="escuchando"] { --glow:.32; --speed:4.2s; }
.orb[data-state="pausada"] { --glow:0; }
.orb[data-state="pitido"], .orb[data-state="grabando"] { --glow:1; --speed:1.5s; }
.orb[data-state="transcribiendo"], .orb[data-state="pensando"] { --glow:.7; --speed:2.4s; }
.orb[data-state="hablando"] { --glow:.85; --speed:1.9s; }
.orb[data-state="inactiva"] .ripple, .orb[data-state="pausada"] .ripple { animation:none; }
/* En pausa: logo gris y atenuado, anillos neutros y quietos. */
.orb[data-state="pausada"] .disc img { filter:grayscale(1); opacity:.45; }
.orb[data-state="pausada"] .ring { border-color:var(--line-strong); opacity:1; }
/* «Respirar» (E3) mientras piensa. */
.orb[data-state="pensando"] .disc { animation:breathe 1.6s var(--ease-io) infinite; }
@keyframes breathe { 50% { transform:scale(1.035); } }
/* Mensaje de estado y pista. */
#state { font-size:var(--fs-xl); font-weight:600; line-height:1.25; color:var(--ink); overflow-wrap:anywhere; }
#hint { min-height:1.5em; max-width:70ch; margin-top:calc(-1 * var(--sp-3)); color:var(--ink-2); font-size:var(--fs-md); line-height:1.5; overflow-wrap:anywhere; }
/* Botón del micrófono: secundario mientras escucha (micrófono tachado: «Dejar de escuchar»); en pausa, principal
   con el micrófono sin tachar («Volver a escuchar»). El icono y el texto cambian, no solo el color. */
.mic-btn { display:inline-flex; align-items:center; justify-content:center; gap:var(--sp-2); min-height:36px; padding:0 var(--sp-5);
  font:inherit; font-size:var(--fs-md); line-height:1.25; color:var(--ink); background:var(--surface); border:1px solid var(--line-strong); border-radius:var(--r-md); cursor:pointer;
  transition:background-color var(--dur-1) var(--ease), border-color var(--dur-1) var(--ease), color var(--dur-1) var(--ease), transform var(--dur-1) var(--ease-out); }
.mic-btn[aria-pressed="true"] { color:var(--accent-ink); background:var(--accent); border-color:var(--accent); font-weight:600; }
.mic-btn:disabled { color:var(--ink-3); background:var(--surface-soft); border-color:var(--surface-soft); cursor:default; }
.mic-btn:active:not(:disabled) { transform:scale(.97); }
.mic-btn svg { flex:none; width:20px; height:20px; }
@media (hover:hover) and (pointer:fine) {
  .mic-btn:not([aria-pressed="true"]):hover:not(:disabled) { background:var(--surface-soft); }
  .mic-btn[aria-pressed="true"]:hover:not(:disabled) { background:color-mix(in oklab, var(--accent) 92%, var(--ink)); border-color:color-mix(in oklab, var(--accent) 92%, var(--ink)); }
}
@media (hover:hover) and (pointer:fine) and (prefers-color-scheme: dark) {
  .mic-btn[aria-pressed="true"]:hover:not(:disabled) { background:color-mix(in oklab, var(--accent) 92%, var(--bg)); border-color:color-mix(in oklab, var(--accent) 92%, var(--bg)); }
}
/* Medidor: pista --surface-soft, nivel --ink-3 (--ok cuando cuenta como voz) y umbral --ink; cifras tabulares. */
.stage-meter { width:min(78vw, 360px); }
.meter { position:relative; height:6px; overflow:hidden; background:var(--surface-soft); border-radius:var(--r-full); }
#fill { position:absolute; inset:0 auto 0 0; width:0; background:var(--ink-3); }
#fill.voice { background:var(--ok); }
#mark { position:absolute; top:0; bottom:0; width:2px; background:var(--ink); }
.nums { display:flex; flex-wrap:wrap; justify-content:space-between; gap:0 var(--sp-3); margin-top:var(--sp-2); color:var(--ink-3); font-size:var(--fs-xs); line-height:1.4;
  font-variant-numeric:tabular-nums; }
/* Carga: hasta el primer dato, disco quieto en --surface-soft sin logo ni anillos, y anuncio .sr-only. */
#view-vivo[aria-busy="true"] .ring, #view-vivo[aria-busy="true"] .ripple { display:none; }
#view-vivo[aria-busy="true"] .disc { background:var(--surface-soft); border-color:var(--surface-soft); }
#view-vivo[aria-busy="true"] .disc img { visibility:hidden; }
#view-vivo[aria-busy="false"] .stage-wrap > .sr-only { display:none; }
@media (pointer:coarse), (max-width:640px) {
  .mic-btn { min-height:44px; }
}
@media (prefers-reduced-motion: reduce) {
  .ripple, .orb[data-state="pensando"] .disc { animation:none; }
  .ring { transform:scale(calc(.6 + var(--i) * .13)); transition:opacity var(--dur-1) var(--ease), border-color var(--dur-2) var(--ease); }
  .mic-btn:active:not(:disabled) { transform:none; }
}

/* Historial — buscador, conversación (burbujas y separador de día), escuchas por voz y estados de carga y vacío (docs/design.md, Vistas;
   RF-24, RF-44, RF-47). El buscador es la acción principal: el campo de la base común (16 px, 44 px y anillo de foco), sin más acento.
   Las burbujas se distinguen por el lado y la esquina, no solo por el fondo: las tuyas a la derecha, en --surface-soft y con la
   esquina inferior derecha en --r-sm; las de Hermes a la izquierda, en --surface con borde y la esquina inferior izquierda en --r-sm.
   Sin sombras (no flotan) ni colores de categoría o de datos. Los textos largos se parten: la página nunca se desplaza en horizontal. */
#view-historial .grid2 { align-items:start; }
.thread { min-width:0; max-width:var(--w-col); }
.search { display:block; width:100%; margin:0 0 var(--sp-3); }
/* Carga: el «Cargando…» de hoy, acompañado de un esqueleto quieto con forma de burbujas alternas. */
#messages > .empty { margin:0 0 var(--sp-2); color:var(--ink-2); font-size:var(--fs-sm); line-height:1.4; }
#messages > .skeleton i { width:70%; height:44px; border-radius:var(--r-lg); }
#messages > .skeleton i:nth-child(even) { align-self:flex-end; }
#messages > .empty-state { margin-top:var(--sp-2); }
/* Separador de día: discreto, centrado, con la inicial en mayúscula. */
.day { margin:var(--sp-5) 0 var(--sp-2); color:var(--ink-3); font-size:var(--fs-xs); line-height:1.4; text-align:center; }
#messages > .day:first-child { margin-top:var(--sp-2); }
.day::first-letter { text-transform:uppercase; }
.msg { width:fit-content; max-width:88%; margin:var(--sp-2) 0; padding:var(--sp-2) var(--sp-3); color:var(--ink); font-size:var(--fs-md); line-height:1.5;
  white-space:pre-wrap; overflow-wrap:anywhere; border:1px solid transparent; border-radius:var(--r-lg); }
.msg.user { margin-left:auto; background:var(--surface-soft); border-bottom-right-radius:var(--r-sm); }
.msg.hermes { margin-right:auto; background:var(--surface); border-color:var(--line); border-bottom-left-radius:var(--r-sm); }
.msg small { display:block; margin-top:var(--sp-1); color:var(--ink-3); font-size:var(--fs-xs); line-height:1.4; white-space:normal; font-variant-numeric:tabular-nums; }
.msg.user small { text-align:right; }
/* Escuchas por voz: resultado con punto lleno --ok (respondió) o hueco --danger (no), como el indicador de conexión;
   el texto del resultado ya lo nombra. Tiempos en chips de 13 px con cifras tabulares (no se pulsan). */
#events .event { padding:var(--sp-3) 0; border-top:1px solid var(--line); }
#events .event:first-child { padding-top:0; border-top:0; }
#events .top { display:flex; flex-wrap:wrap; align-items:baseline; justify-content:space-between; gap:var(--sp-1) var(--sp-3);
  color:var(--ink-3); font-size:var(--fs-xs); line-height:1.4; font-variant-numeric:tabular-nums; }
#events .outcome { display:inline-flex; align-items:center; gap:var(--sp-2); min-width:0; color:var(--ok); font-size:var(--fs-sm); font-weight:600; overflow-wrap:anywhere; }
#events .outcome::before { content:""; flex:none; width:8px; height:8px; border-radius:var(--r-full); background:var(--ok); }
#events .outcome.bad { color:var(--danger); }
#events .outcome.bad::before { background:transparent; border:2px solid var(--danger); }
#events .line { margin-top:var(--sp-1); color:var(--ink-2); font-size:var(--fs-sm); line-height:1.4; overflow-wrap:anywhere; }
#events .line b { color:var(--ink); font-weight:600; }
#events .times { display:flex; flex-wrap:wrap; gap:var(--sp-1); margin-top:var(--sp-2); }
#events .chip { display:inline-block; padding:0 var(--sp-2); color:var(--ink-2); font-size:var(--fs-xs); font-weight:400; line-height:1.5; white-space:nowrap;
  font-variant-numeric:tabular-nums; background:var(--surface-soft); border:0; border-radius:var(--r-full); }
#events .chip.total { color:var(--ink); font-weight:600; }
#events > .empty-state { padding:var(--sp-5) 0; }
@media (max-width:640px) {
  .msg { max-width:92%; }
}

/* Apuntes — marco (título, explicación, subpestañas, aviso de silencio y estado de carga) y Listas (docs/design.md, Vistas; RF-15, RF-34, RF-42, RF-47).
   Las piezas comunes de todos los apartados (formularios, filas, casillas, ✕, enlaces de acción y vacíos) también
   quedan aquí; lo propio de cada apartado va en su sección, más abajo. Cada apartado es una página sin caja
   propia: sus tarjetas ya son las superficies (sin tarjetas dentro de tarjetas). */
#ap-title { margin:var(--sp-1) 0 var(--sp-0); font-size:var(--fs-xl); font-weight:600; line-height:1.25; }
#ap-tabs a[hidden] { display:none; }
.ap-page { padding:0; background:none; border:0; border-radius:0; }
/* Aviso de silencio: el silencio es una elección activa del usuario, así que va como selección (fondo y borde de acento). */
#ap-quiet { display:flex; flex-wrap:wrap; align-items:center; gap:var(--sp-2) var(--sp-3); max-width:var(--w-col); margin:0 0 var(--sp-4); padding:var(--sp-3) var(--sp-4);
  color:var(--ink); font-size:var(--fs-md); line-height:1.5; background:var(--accent-soft); border:1px solid var(--accent); border-radius:var(--r-md); }
#ap-quiet[hidden] { display:none; }
#ap-quiet span { flex:1 1 16em; min-width:0; }
#ap-quiet .ghost { flex:none; }
/* Formularios de crear y agregar: una fila que se parte en columnas a 375 px; campos de 44 y botón a su altura. */
.ap-form { display:flex; flex-wrap:wrap; gap:var(--sp-2); margin:0 0 var(--sp-3); }
.ap-form input, .ap-form select { flex:1 1 110px; min-width:0; }
.ap-form .primary, .ap-form .ghost { flex:none; min-height:44px; margin-left:0; }
.ap-create { max-width:var(--w-col); margin-bottom:var(--sp-4); }
/* Listas: un cajón por lista, como los grupos de Tareas (cabecera con nombre, cuenta y chevron). */
.ap-drawers { display:grid; grid-template-columns:repeat(auto-fill, minmax(min(100%, 320px), 1fr)); gap:var(--sp-4); align-items:start; }
.ap-drawer { min-width:0; overflow:hidden; background:var(--surface); border:1px solid var(--line); border-radius:var(--r-lg); }
.ap-drawer-head { display:flex; align-items:center; gap:var(--sp-2); width:100%; min-height:44px; padding:var(--sp-3) var(--sp-4);
  font:inherit; font-size:var(--fs-lg); font-weight:600; line-height:1.3; color:inherit; text-align:left; background:none; border:0; cursor:pointer; }
.ap-drawer-head:focus-visible { outline-offset:-2px; }
.ap-drawer-head .name { flex:1; min-width:0; overflow-wrap:anywhere; text-transform:capitalize; }
.ap-drawer-head em { color:var(--ink-3); font-size:var(--fs-sm); font-style:normal; font-weight:500; white-space:nowrap; font-variant-numeric:tabular-nums; }
.ap-drawer-head .chev { flex:none; width:8px; height:8px; margin:0 var(--sp-1) var(--sp-1); border:solid var(--ink-2); border-width:0 2px 2px 0;
  transform:rotate(45deg); transition:transform var(--dur-1) var(--ease-out); }
.ap-drawer.closed .chev { transform:rotate(-45deg); margin-bottom:0; }
.ap-drawer-body { padding:0 var(--sp-4) var(--sp-3); border-top:1px solid var(--line); }
.ap-drawer-body .ap-row:first-child { border-top:0; }
/* Dentro de una tarjeta, los campos van sobre --surface-soft. */
.ap-drawer .ap-form input, .ap-drawer .ap-editing input { background:var(--surface-soft); }
.ap-add { margin:var(--sp-3) 0 var(--sp-1); }
.ap-drawer-foot { display:flex; flex-wrap:wrap; justify-content:space-between; gap:var(--sp-1) var(--sp-4); margin-top:var(--sp-1); }
/* Filas: casilla, texto que se toca para corregirlo y ✕ para quitar; la marcada se queda tachada y atenuada. */
.ap-row { display:flex; align-items:center; gap:var(--sp-2); padding:var(--sp-1) 0; border-top:1px solid var(--line); font-size:var(--fs-md); }
.ap-row .grow { flex:1; min-width:0; overflow-wrap:anywhere; }
.ap-item { min-height:32px; padding:var(--sp-1) 0; font:inherit; color:inherit; text-align:left; background:none; border:0; border-radius:var(--r-sm); cursor:text; }
.ap-row.done .ap-item { color:var(--ink-3); text-decoration:line-through; }
/* Casilla: círculo de 22 px con borde --line-strong en una zona de 32 px (44 en táctil); marcada, llena de acento con ✓. */
.ap-check { position:relative; flex:none; display:grid; place-items:center; width:32px; height:32px; padding:0; background:transparent; border:0; border-radius:var(--r-full); cursor:pointer; }
.ap-check::before { content:""; width:22px; height:22px; border:2px solid var(--line-strong); border-radius:var(--r-full); }
.ap-check.on::before { background:var(--accent); border-color:var(--accent); }
.ap-check.on::after { content:""; position:absolute; left:50%; top:50%; width:6px; height:11px; border:solid var(--accent-ink); border-width:0 2px 2px 0;
  transform:translate(-50%, -60%) rotate(45deg); }
.ap-x { flex:none; display:inline-grid; place-items:center; min-width:32px; min-height:32px; padding:0 var(--sp-2); font:inherit; font-size:var(--fs-md); line-height:1;
  color:var(--ink-2); background:none; border:0; border-radius:var(--r-md); cursor:pointer; }
.ap-x svg { display:block; width:16px; height:16px; pointer-events:none; }
/* Corregir un elemento: el campo ocupa la fila, con Guardar y ✕ a su altura. */
.ap-editing { gap:var(--sp-2); }
.ap-editing input { flex:1; min-width:0; border-color:var(--accent); }
.ap-editing .primary { flex:none; min-height:44px; margin-left:0; }
/* Acciones de texto (Vaciar, Quitar marcados, Eliminar lista): como «Volver a pendientes» de Tareas. */
.ap-link { display:inline-flex; align-items:center; min-height:32px; padding:0; font:inherit; font-size:var(--fs-sm); font-weight:500; color:var(--ink-2);
  text-decoration:underline; text-transform:none; background:none; border:0; border-radius:var(--r-sm); cursor:pointer; white-space:nowrap; }
.ap-link[hidden] { display:none; }
.ap-link.danger-link { color:var(--danger); }
.ap-link:disabled { color:var(--ink-3); text-decoration:none; cursor:default; }
/* Vacíos: dentro de un cajón, una línea atenuada; sin nada que mostrar, una tarjeta centrada con el mismo texto de hoy. */
.ap-empty { padding:var(--sp-2) 0; color:var(--ink-3); font-size:var(--fs-sm); line-height:1.4; }
.ap-empty.card { padding:var(--sp-6) var(--sp-4); color:var(--ink-2); text-align:center; }
/* Carga: el esqueleto quieto de Tareas, debajo del formulario del apartado abierto. */
.ap-grid > .skeleton { max-width:var(--w-col); }
@media (hover:hover) and (pointer:fine) {
  .ap-drawer-head:hover { background:var(--surface-soft); }
  .ap-item:not(:disabled):hover { text-decoration:underline; }
  .ap-row.done .ap-item:hover { text-decoration:line-through underline; }
  .ap-check:hover::before { border-color:var(--accent); }
  .ap-x:hover { color:var(--danger); background:var(--surface-soft); }
  .ap-link:not(:disabled):hover { color:var(--ink); }
  .ap-link.danger-link:not(:disabled):hover { color:var(--danger); }
}
/* Táctil o pantalla estrecha: zonas de 44×44 px (la casilla y el ✕ crecen; el dibujo no). */
@media (pointer:coarse), (max-width:640px) {
  .ap-check { width:44px; height:44px; }
  .ap-x { min-width:44px; min-height:44px; }
  .ap-item, .ap-link { min-height:44px; }
  .ap-link { min-width:44px; justify-content:center; }
}
@media (max-width:640px) {
  .ap-drawer-head { padding-left:var(--sp-3); padding-right:var(--sp-3); }
  .ap-drawer-body { padding:0 var(--sp-3) var(--sp-3); }
  .ap-row { gap:var(--sp-1); }
}
@media (prefers-reduced-motion: reduce) {
  .ap-drawer-head .chev { transition:none; }
}

/* Apuntes — Notas y Seguimientos (docs/design.md, Vistas; RF-24, RF-34, RF-42, RF-47). Página sin caja propia:
   título con su cuenta, explicación, formulario de crear (la acción principal) y una sola tarjeta con las filas.
   Sin nada que mostrar, la tarjeta lleva el texto de hoy centrado (como el vacío de Listas). Los textos largos se
   parten dentro de la fila y se ven completos; al tocarlos se corrigen en la misma fila. */
.ap-head { display:flex; align-items:baseline; flex-wrap:wrap; gap:var(--sp-0) var(--sp-2); margin:0 0 var(--sp-1); font-size:var(--fs-lg); font-weight:600; line-height:1.3; }
.ap-head span { color:var(--ink-3); font-size:var(--fs-sm); font-weight:500; font-variant-numeric:tabular-nums; }
.ap-hint { max-width:var(--w-col); margin:0 0 var(--sp-4); color:var(--ink-2); font-size:var(--fs-sm); line-height:1.5; }
.ap-form input.narrow { flex:0 1 84px; }
.ap-list { max-width:var(--w-col); min-width:0; padding:0 var(--sp-4); background:var(--surface); border:1px solid var(--line); border-radius:var(--r-lg); }
.ap-list > .ap-row:first-child { border-top:0; }
.ap-list > .ap-empty { padding:var(--sp-6) 0; color:var(--ink-2); text-align:center; }
.ap-list .ap-row { min-height:44px; }
.ap-list .ap-item { line-height:1.5; }
.ap-item small { display:block; margin-top:var(--sp-0); color:var(--ink-3); font-size:var(--fs-xs); line-height:1.4; text-decoration:none; }
/* Corregir: dentro de la tarjeta los campos van sobre --surface-soft, con borde de acento mientras se editan. */
.ap-list .ap-editing { padding:var(--sp-2) 0; }
.ap-list .ap-editing input, .ap-list .ap-editing textarea { background:var(--surface-soft); }
.ap-editing textarea { flex:1; min-width:0; line-height:1.5; border-color:var(--accent); resize:vertical;
  field-sizing:content; /* Crece con el texto: la nota se ve entera al corregirla (donde el navegador lo admite). */ }
/* Nota: el texto a lo ancho y, a su lado, Guardar arriba y ✕ debajo. */
.ap-editing-note { align-items:flex-start; }
.ap-edit-buttons { display:flex; flex:none; flex-direction:column; align-items:center; gap:var(--sp-1); }
/* Seguimiento: el texto a lo ancho y, debajo, el día con Guardar y ✕. */
.ap-editing-wait { flex-wrap:wrap; }
.ap-editing-wait input:not([type]) { flex:1 1 100%; }
.ap-editing-wait input[type="date"] { flex:1 1 140px; }
/* A 375 px, lo que esperas va a lo ancho (se lee el ejemplo entero) y, debajo, los días y Agregar. */
@media (max-width:640px) {
  #ap-waiting-text { flex:1 1 100%; }
}

/* Apuntes — Fechas (docs/design.md, Vistas; RF-12, RF-24, RF-34, RF-42, RF-47). Como Notas: página sin caja propia,
   título con su cuenta, explicación, el calendario de Tareas (número tabular, hoy en neutro invertido, día elegido
   con borde de acento), el formulario de agregar (la acción principal) y las próximas agrupadas por mes, cada mes en
   una tarjeta con sus filas. El distintivo del día va en --surface-soft (el de hoy, invertido como en el
   calendario) y las próximas (hoy y los 7 días siguientes) llevan su plazo en --ink 600: el acento queda para la
   selección y la acción principal. */
#ap-dates-cal { max-width:var(--w-col); }
.cal-picked { margin:calc(-1 * var(--sp-2)) 0 var(--sp-4); color:var(--ink-2); font-size:var(--fs-sm); line-height:1.5; }
.cal-picked b { color:var(--ink); font-weight:600; }
.dt-group { max-width:var(--w-col); margin-top:var(--sp-5); }
.dt-group:first-child { margin-top:0; }
.dt-group h4 { margin:0 0 var(--sp-2); color:var(--ink-2); font-size:var(--fs-sm); font-weight:600; line-height:1.4; }
.dt-row { gap:var(--sp-3); padding:var(--sp-2) 0; }
.dt-row .dt-badge { flex:none; display:flex; flex-direction:column; align-items:center; justify-content:center; width:48px; min-height:48px; padding:var(--sp-1) 0;
  color:var(--ink); line-height:1.2; text-align:center; background:var(--surface-soft); border-radius:var(--r-md); }
.dt-row .dt-badge b { font-size:var(--fs-lg); font-weight:600; line-height:1.1; font-variant-numeric:tabular-nums; }
.dt-row .dt-badge span { color:var(--ink-2); font-size:var(--fs-xs); }
.dt-row.today .dt-badge { color:var(--bg); background:var(--ink); }
.dt-row.today .dt-badge span { color:var(--bg); }
.dt-row .dt-body { flex:1; min-width:0; }
.dt-row .dt-body .ap-item { display:block; width:100%; font-size:var(--fs-md); font-weight:500; overflow-wrap:anywhere; }
.dt-row .dt-body small { display:block; color:var(--ink-3); font-size:var(--fs-xs); line-height:1.4; }
.dt-row.today .when, .dt-row.soon .when { color:var(--ink); font-weight:600; }
/* Corregir una fecha: de quién a lo ancho y, debajo, tipo, día, mes y año; Guardar y ✕ al final. */
.dt-edit { flex-wrap:wrap; }
.dt-edit input, .dt-edit select { flex:1 1 110px; min-width:0; }
.dt-edit input:not([type]) { flex:1 1 100%; }
.dt-edit input.narrow { flex:0 1 84px; }
.ap-list .dt-edit select { background:var(--surface-soft); border-color:var(--accent); }
/* A 375 px, el tipo con sitio para leerse entero junto a de quién; debajo, día, mes y año, y luego Agregar. */
@media (max-width:640px) {
  #ap-date-kind, #ap-date-name { flex:1 1 140px; }
}
/* Apuntes — Hábitos (docs/design.md, Vistas; RF-25, RF-34, RF-42). Una tarjeta por hábito: botón de hoy de 46 px
   (casilla grande), nombre que se toca para corregirlo, racha en --ink 600 y la semana de 7 días. Los días van
   sin huecos y la tarjeta con menos relleno para que cada uno tenga su zona de 44 px a 375 px. Hecho y sin hacer
   se distinguen por algo más que el color: círculo lleno con ✓ frente a círculo hueco. */
.hb-today { max-width:var(--w-col); margin:0 0 var(--sp-4); color:var(--ink-2); font-size:var(--fs-sm); line-height:1.4; }
.hb-today:empty { display:none; }
.hb-today b { color:var(--ink); font-weight:600; font-variant-numeric:tabular-nums; }
.hb-bar { max-width:420px; height:6px; margin-top:var(--sp-2); overflow:hidden; background:var(--surface-soft); border-radius:var(--r-full); }
.hb-bar i { display:block; height:100%; background:var(--accent); border-radius:var(--r-full); }
.hb-grid { display:grid; grid-template-columns:repeat(auto-fill, minmax(min(100%, 320px), 1fr)); gap:var(--sp-4); align-items:start; }
.hb-grid > .ap-empty.card { grid-column:1 / -1; max-width:var(--w-col); }
.hb-card { display:flex; flex-direction:column; gap:var(--sp-3); min-width:0; padding:var(--sp-3); background:var(--surface); border:1px solid var(--line); border-radius:var(--r-lg); }
.hb-top { display:flex; align-items:center; gap:var(--sp-3); min-width:0; }
.hb-check { position:relative; flex:none; width:46px; height:46px; padding:0; background:transparent; border:2px solid var(--line-strong); border-radius:var(--r-full); cursor:pointer;
  transition:background-color var(--dur-1) var(--ease), border-color var(--dur-1) var(--ease); }
.hb-check.on { background:var(--accent); border-color:var(--accent); }
.hb-check.on::after { content:""; position:absolute; left:50%; top:50%; width:10px; height:19px; border:solid var(--accent-ink); border-width:0 3px 3px 0;
  transform:translate(-50%, -60%) rotate(45deg); }
.hb-name { flex:1; min-width:0; }
.hb-name .ap-item { display:block; width:100%; font-size:var(--fs-md); font-weight:600; line-height:1.3; overflow-wrap:anywhere; }
.hb-name small { display:block; color:var(--ink-3); font-size:var(--fs-xs); line-height:1.4; }
.hb-stats { display:flex; flex-wrap:wrap; gap:var(--sp-1) var(--sp-4); color:var(--ink-2); font-size:var(--fs-xs); line-height:1.4; }
.hb-stats b { color:var(--ink); font-size:var(--fs-sm); font-weight:600; font-variant-numeric:tabular-nums; }
/* Semana: 7 columnas iguales; cada día es un botón a todo su ancho, con el círculo de 22 px y la letra del día debajo.
   La fila invade casi todo el relleno lateral de la tarjeta para que cada día tenga sus 44 px a 375 px. */
.hb-week { display:grid; grid-template-columns:repeat(7, minmax(0, 1fr)); gap:0; margin:0 calc(-1 * var(--sp-2)); }
.hb-day { display:flex; flex-direction:column; align-items:center; justify-content:center; gap:var(--sp-0); min-width:0; min-height:44px; padding:var(--sp-1) 0;
  font:inherit; font-size:var(--fs-xs); line-height:1.2; color:var(--ink-3); background:none; border:0; border-radius:var(--r-md); cursor:pointer; }
.hb-day:focus-visible { outline-offset:-2px; }
.hb-day i { position:relative; display:block; width:22px; height:22px; background:transparent; border:2px solid var(--line-strong); border-radius:var(--r-full); }
.hb-day.on i { background:var(--accent); border-color:var(--accent); }
.hb-day.on i::after { content:""; position:absolute; left:50%; top:50%; width:5px; height:10px; border:solid var(--accent-ink); border-width:0 2px 2px 0;
  transform:translate(-50%, -60%) rotate(45deg); }
.hb-day.today { color:var(--ink); font-weight:600; }
/* Corregir el hábito: nombre a lo ancho y, debajo, la hora; Guardar y ✕ van juntos y, si no caben a su lado, bajan a otra fila. */
.hb-edit { display:flex; flex-wrap:wrap; gap:var(--sp-2); }
.hb-edit input { min-width:0; background:var(--surface-soft); }
.hb-edit input:not([type]) { flex:1 1 100%; border-color:var(--accent); }
.hb-edit input[type="time"] { flex:1 1 7em; }
.hb-edit-actions { display:flex; flex:none; gap:var(--sp-2); }
.hb-edit .primary { flex:none; min-height:44px; margin-left:0; }
.hb-foot { display:flex; justify-content:flex-end; }
@media (hover:hover) and (pointer:fine) {
  .hb-check:not(.on):hover, .hb-day:not(.on):hover i { border-color:var(--accent); }
  .hb-day:hover { background:var(--surface-soft); }
}
/* Texto al 200 % en el teléfono (~188 px útiles, RF-40): siete días de ~21 px juntan sus nombres («sábdomlun»), así
   que la semana pasa a dos filas de cuatro, en el mismo orden. */
@media (max-width:300px) {
  .hb-week { grid-template-columns:repeat(4, minmax(0, 1fr)); row-gap:var(--sp-1); }
}
@media (prefers-reduced-motion: reduce) {
  .hb-check { transition:none; }
}
/* Apuntes — Gastos (docs/design.md, Vistas; RF-12, RF-25, RF-34, RF-42, RF-47). Como Notas y Fechas: página sin caja
   propia. Arriba, la navegación de mes ‹ ›: la acción principal y lo único con acento (borde y glifo; como los botones
   del calendario, 36 px con ratón y 44 en táctil). Debajo, una tarjeta con el total del mes (--fs-xl), el enlace de
   presupuestos y una barra por categoría; la explicación, y una tarjeta con los recibos. Barras en --ink-3; cerca del
   presupuesto (desde el 80 %), --warn con el importe en 600; pasado, --danger con el importe en 600 y el triángulo de
   «Urgente» de Tareas: el estado se lee también en «X de Y» y en la forma, no solo en el color. Todo importe con
   cifras tabulares. La miniatura (48 px) abre la foto del recibo. */
.rc-head { display:flex; align-items:center; gap:var(--sp-3); max-width:var(--w-col); margin:0 0 var(--sp-3); }
.rc-head h3 { min-width:7em; margin:0; font-size:var(--fs-lg); font-weight:600; line-height:1.3; text-align:center; font-variant-numeric:tabular-nums; }
.rc-nav { flex:none; display:inline-grid; place-items:center; width:36px; height:36px; padding:0; font:inherit; font-size:var(--fs-lg); font-weight:600; line-height:1;
  color:var(--accent); background:var(--surface); border:1px solid var(--accent); border-radius:var(--r-md); cursor:pointer;
  transition:background-color var(--dur-1) var(--ease), transform var(--dur-1) var(--ease-out); }
.rc-nav:active:not(:disabled) { transform:scale(.97); }
.rc-nav:disabled { color:var(--ink-3); background:var(--surface-soft); border-color:var(--surface-soft); cursor:default; }
#rc-summary, #bl-summary { display:flex; flex-direction:column; gap:var(--sp-2); max-width:var(--w-col); margin:0 0 var(--sp-4); padding:var(--sp-4);
  background:var(--surface); border:1px solid var(--line); border-radius:var(--r-lg); }
#rc-summary .rc-total, #bl-summary .rc-total { display:flex; align-items:baseline; flex-wrap:wrap; gap:var(--sp-1) var(--sp-3); margin-bottom:var(--sp-1); }
#rc-summary .rc-total b, #bl-summary .rc-total b { min-width:0; font-size:var(--fs-xl); font-weight:600; line-height:1.25; font-variant-numeric:tabular-nums; overflow-wrap:anywhere; }
#rc-summary .rc-total span, #bl-summary .rc-total span { color:var(--ink-2); font-size:var(--fs-sm); line-height:1.4; font-variant-numeric:tabular-nums; }
#rc-summary .rc-total .ap-link { margin-left:auto; }
/* Una categoría: nombre, barra e importe en una fila, con columnas fijas para que las barras empiecen y acaben igual
   (un importe más largo se parte en dos líneas); a 375 px, la barra baja a lo ancho. */
.rc-cat { display:grid; grid-template-columns:minmax(80px, 130px) minmax(0, 1fr) 15em; align-items:center; gap:var(--sp-1) var(--sp-3); min-height:32px; font-size:var(--fs-sm); line-height:1.4; }
.rc-cat-name { min-width:0; color:var(--ink); overflow-wrap:anywhere; }
.rc-cat-amount { display:inline-flex; flex-wrap:wrap; align-items:center; justify-content:flex-end; gap:var(--sp-1); justify-self:end; min-width:0; color:var(--ink-2); text-align:right; font-variant-numeric:tabular-nums; }
.rc-bar { height:8px; overflow:hidden; background:var(--surface-soft); border-radius:var(--r-full); }
.rc-bar i { display:block; height:100%; background:var(--ink-3); border-radius:var(--r-full); }
.rc-cat.near .rc-bar i { background:var(--warn); }
.rc-cat.near .rc-cat-amount { color:var(--warn); font-weight:600; }
.rc-cat.over .rc-bar i { background:var(--danger); }
.rc-cat.over .rc-cat-amount { color:var(--danger); font-weight:600; }
.rc-cat.over .rc-cat-amount::before { content:""; flex:none; width:10px; height:10px; background:var(--danger); clip-path:polygon(50% 0, 100% 100%, 0 100%); }
/* Presupuestos: dentro de la tarjeta del total, entre dos líneas; los campos sobre --surface-soft. */
.rc-budgets { display:grid; grid-template-columns:repeat(auto-fill, minmax(min(100%, 220px), 1fr)); gap:var(--sp-2) var(--sp-4); margin:0 0 var(--sp-1); padding:var(--sp-3) 0;
  border-top:1px solid var(--line); border-bottom:1px solid var(--line); }
.rc-budgets p { grid-column:1 / -1; max-width:var(--w-col); margin:0 0 var(--sp-1); color:var(--ink-2); font-size:var(--fs-sm); line-height:1.5; }
.rc-budget-row { display:flex; align-items:center; gap:var(--sp-3); min-width:0; font-size:var(--fs-sm); }
.rc-budget-row span { flex:1; min-width:0; overflow-wrap:anywhere; }
.rc-budget-row input { flex:0 1 128px; width:128px; min-width:0; background:var(--surface-soft); font-variant-numeric:tabular-nums; }
.rc-budget-buttons { grid-column:1 / -1; display:flex; flex-wrap:wrap; justify-content:flex-end; gap:var(--sp-2); }
.rc-budget-buttons .primary { margin-left:0; }
/* Recibos: miniatura, comercio que se toca para corregirlo con su día y categoría debajo, importe y ✕. */
#rc-list .rc-row { gap:var(--sp-3); padding:var(--sp-2) 0; }
.rc-thumb { flex:none; display:grid; place-items:center; width:48px; height:48px; padding:0; overflow:hidden; font:inherit; font-size:var(--fs-lg); line-height:1;
  color:var(--ink-2); background:var(--surface-soft); border:1px solid var(--line-strong); border-radius:var(--r-md); cursor:zoom-in; }
.rc-thumb:disabled { border-color:var(--line); cursor:default; }
.rc-thumb img { display:block; width:100%; height:100%; object-fit:cover; }
.rc-body { flex:1; min-width:0; }
.rc-body .ap-item { display:block; width:100%; font-size:var(--fs-md); font-weight:500; overflow-wrap:anywhere; }
#rc-list .rc-body small { display:block; color:var(--ink-3); font-size:var(--fs-xs); line-height:1.4; }
.rc-amount { flex:none; font-size:var(--fs-md); font-weight:600; font-variant-numeric:tabular-nums; white-space:nowrap; }
/* Corregir un recibo: el comercio a lo ancho y, debajo, total, moneda, día, categoría y garantía; Guardar y ✕ al final. */
#rc-list .rc-edit, #bl-list .rc-edit { flex-wrap:wrap; padding:var(--sp-2) 0; }
#rc-list .rc-edit input, #rc-list .rc-edit select, #bl-list .rc-edit input, #bl-list .rc-edit select { flex:1 1 110px; min-width:0; }
#rc-list .rc-edit input:not([type]), #bl-list .rc-edit input:not([type]) { flex:1 1 100%; }
#rc-list .rc-edit input[type="number"], #bl-list .rc-edit input[type="number"] { font-variant-numeric:tabular-nums; }
#rc-list .rc-edit input[type="date"], #bl-list .rc-edit input[type="date"] { flex:1 1 140px; }
#rc-list .rc-edit select, #bl-list .rc-edit select { background:var(--surface-soft); border-color:var(--accent); }
#rc-list .rc-warranty, #bl-list .rc-warranty { display:flex; flex:1 1 100%; align-items:center; gap:var(--sp-2); color:var(--ink-2); font-size:var(--fs-sm); }
@media (hover:hover) and (pointer:fine) {
  .rc-nav:hover:not(:disabled) { background:var(--accent-soft); }
  .rc-thumb:not(:disabled):hover { border-color:var(--ink-2); }
}
@media (pointer:coarse), (max-width:640px) {
  .rc-nav { width:44px; height:44px; }
}
@media (max-width:640px) {
  .rc-cat { grid-template-columns:minmax(0, 1fr) auto; }
  .rc-cat .rc-bar { grid-column:1 / -1; grid-row:2; }
  /* A 375 px el comercio necesita el ancho: el importe baja debajo de la fecha y la categoría. */
  #rc-list .rc-row { display:grid; grid-template-columns:auto minmax(0, 1fr) auto; grid-template-areas:"thumb body x" "thumb amount x"; gap:0 var(--sp-3); }
  #rc-list .rc-row .rc-thumb { grid-area:thumb; align-self:center; }
  #rc-list .rc-row .rc-body { grid-area:body; }
  #rc-list .rc-row .rc-amount { grid-area:amount; }
  #rc-list .rc-row .ap-x { grid-area:x; align-self:center; }
}
/* Texto al 200 % en el teléfono (~188 px útiles, RF-40): el mes sube a su propia línea y ‹ › quedan debajo. */
@media (max-width:300px) {
  .rc-head { flex-wrap:wrap; }
  .rc-head h3 { order:-1; flex:1 1 100%; min-width:0; text-align:left; overflow-wrap:anywhere; }
}
@media (prefers-reduced-motion: reduce) {
  .rc-nav { transition:none; }
}
/* Apuntes — Pagos (docs/design.md, Vistas; RF-12, RF-34, RF-42, RF-47). Como Gastos: página sin caja propia. Arriba, la
   tarjeta del total al mes (la de Gastos: --fs-xl tabular) con el próximo pago; debajo, el formulario de agregar (la acción
   principal), la explicación y una tarjeta con los pagos. Cada fila es la de Fechas (distintivo del día en --surface-soft,
   nombre que se toca para corregirlo y su plazo debajo), con «Pagado» (secundario) y ✕ a la derecha. Próximo (vence en
   3 días o menos): el plazo en --warn 600. Vencido: el distintivo con borde de 2 px --danger y el plazo en --danger 600
   con el triángulo de «Urgente» de Tareas; el estado se lee también en su texto («venció hace…»), no solo en el color.
   Todo importe con cifras tabulares. */
.bl-next { color:var(--ink-2); font-size:var(--fs-sm); line-height:1.4; font-variant-numeric:tabular-nums; }
.bl-add input:not([type]) { flex:1 1 100%; }
.bl-add input[type="number"] { flex:1 1 160px; font-variant-numeric:tabular-nums; /* Con sitio para leer «Monto (opcional)» entero. */ }
.bl-date { display:flex; flex:1 1 220px; align-items:center; gap:var(--sp-2); min-width:0; color:var(--ink-2); font-size:var(--fs-sm); line-height:1.4; }
.bl-date input { flex:1; min-width:0; }
.bl-row { flex-wrap:wrap; }
.bl-row .dt-body small { font-variant-numeric:tabular-nums; }
.bl-row.soon .when { color:var(--warn); font-weight:600; }
.bl-row.late .when { color:var(--danger); font-weight:600; }
.bl-row.late .when::before { content:""; display:inline-block; width:10px; height:10px; margin-right:var(--sp-1); background:var(--danger);
  clip-path:polygon(50% 0, 100% 100%, 0 100%); }
.bl-row.late .dt-badge { border:2px solid var(--danger); }
.bl-row .bl-actions { display:flex; flex:none; align-items:center; justify-content:flex-end; gap:var(--sp-2); margin-left:auto; }
/* Anotar lo pagado: el monto (campo dentro de la tarjeta, con borde de acento mientras se escribe), Anotar y ✕. */
.bl-pay { display:flex; align-items:center; gap:var(--sp-2); min-width:0; }
.bl-pay input { flex:0 1 128px; width:128px; min-width:0; background:var(--surface-soft); border-color:var(--accent); font-variant-numeric:tabular-nums; }
.bl-pay .primary { flex:none; min-height:44px; margin-left:0; }
/* A 375 px el nombre necesita el ancho: «Pagado» y ✕ (o el monto, Anotar y ✕) bajan a su propia línea, a la derecha. */
@media (max-width:640px) {
  .bl-row .bl-actions { flex:1 1 100%; }
  .bl-pay { flex:1 1 auto; justify-content:flex-end; }
  .bl-pay input { flex:1 1 110px; }
}
/* Texto al 200 % en el teléfono (~188 px útiles, RF-40): si «Pagado» (o Anotar) y ✕ no caben juntos, ✕ baja. */
@media (max-width:300px) {
  .bl-row .bl-actions, .bl-pay { flex-wrap:wrap; }
}
/* Apuntes — restos comunes de los apartados: la hora del formulario de Hábitos y el detalle bajo el texto de una fila.
   Van aquí, después de los apartados, para conservar el orden en que se aplican hoy (el detalle de Notas y Seguimientos
   sale en --ink-2). */
.ap-form input[type="time"] { flex:0 1 120px; }
.ap-row small { display:block; color:var(--ink-2); font-size:var(--fs-xs); }
/* Apuntes — Lecturas (docs/design.md, Vistas; RF-24, RF-34, RF-40, RF-42, RF-47). Como Pagos: página sin caja propia,
   el formulario de guardar (la acción principal), la explicación y una tarjeta con los enlaces por leer; los leídos,
   en otra tarjeta dentro de «Leídos (n)», como las terminadas de Tareas. Cada fila: el título del enlace en una línea
   (si es largo, se corta con … y se ve completo en su title y al abrirlo), el sitio y cuándo se guardó en --ink-3, el
   resumen con overflow-wrap:anywhere y, a la derecha, «✓ Leído» (secundario) y ✕. Leído: el título en --ink-2 500
   (sin bajar la opacidad, para no perder contraste). */
.ln-row { flex-wrap:wrap; align-items:flex-start; gap:var(--sp-1) var(--sp-3); padding:var(--sp-2) 0; }
.ln-body { flex:1 1 260px; min-width:0; }
.ln-title { display:block; min-height:32px; padding:var(--sp-1) 0; overflow:hidden; color:var(--ink); font-size:var(--fs-md); font-weight:600; line-height:1.5;
  text-decoration:none; white-space:nowrap; text-overflow:ellipsis; border-radius:var(--r-sm); }
.ln-row.read .ln-title { color:var(--ink-2); font-weight:500; }
.ln-body small { display:block; overflow:hidden; color:var(--ink-3); font-size:var(--fs-xs); line-height:1.4; white-space:nowrap; text-overflow:ellipsis; }
.ln-summary { margin:var(--sp-1) 0 0; color:var(--ink-2); font-size:var(--fs-sm); line-height:1.5; overflow-wrap:anywhere; }
.ln-row .bl-actions { display:flex; flex:none; align-items:center; justify-content:flex-end; gap:var(--sp-2); margin-left:auto; }
.ln-done { max-width:var(--w-col); margin-top:var(--sp-4); }
.ln-done summary { min-height:32px; padding:var(--sp-1) 0; color:var(--ink-2); font-size:var(--fs-sm); line-height:1.6; cursor:pointer; }
.ln-done .ap-list { margin-top:var(--sp-2); }
@media (hover:hover) and (pointer:fine) {
  .ln-title:hover { text-decoration:underline; }
}
@media (pointer:coarse), (max-width:640px) {
  .ln-title { min-height:44px; padding:var(--sp-2) 0; }
  .ln-done summary { padding:var(--sp-3) 0; }
}
/* A 375 px el título necesita el ancho: «✓ Leído» y ✕ bajan a su propia línea, a la derecha. */
@media (max-width:640px) {
  .ln-row .bl-actions { flex:1 1 100%; }
}
/* Texto al 200 % en el teléfono (~188 px útiles, RF-40): si «✓ Leído» y ✕ no caben juntos, ✕ baja. */
@media (max-width:300px) {
  .ln-row .bl-actions { flex-wrap:wrap; }
}

/* Ajustes — aviso de reinicio, dispositivos, grupos de ajustes (Funciones, interruptores, campos, secretos y categorías),
   barra de Guardar y estado de carga (docs/design.md, Vistas; RF-8, RF-25, RF-46, RF-47). Un solo acento: «Guardar
   cambios» (la acción principal, en el flujo al pie del formulario); los interruptores marcados usan el acento como
   selección (accent-color) y el resto de botones son secundarios o de texto. Los grupos son tarjetas --surface sin
   sombra; dentro, los campos van sobre --surface-soft con la base común (16 px, 44 px y anillo de foco). Una columna
   a ≤ 640 px. El color de cada categoría se ve tal cual solo en su selector nativo (E2), sin vista previa añadida; el
   nombre de la categoría va en neutro. */
#view-ajustes > h1 { margin:var(--sp-1) 0 var(--sp-0); font-size:var(--fs-xl); font-weight:600; line-height:1.25; }
#set-restart, #set-sessions, #set-form { max-width:var(--w-col); }
/* Aviso de reinicio: como el aviso de silencio de Apuntes (fondo y borde de acento, en el flujo, botón secundario). */
.set-note { display:flex; flex-wrap:wrap; align-items:center; gap:var(--sp-2) var(--sp-3); max-width:var(--w-col); margin:0 0 var(--sp-4); padding:var(--sp-3) var(--sp-4);
  color:var(--ink); font-size:var(--fs-md); line-height:1.5; background:var(--accent-soft); border:1px solid var(--accent); border-radius:var(--r-md); }
.set-note[hidden] { display:none; }
.set-note > span { flex:1 1 16em; min-width:0; }
.set-note .ghost { flex:none; }
/* Grupos: tarjeta con su título y filas etiqueta / control separadas por una línea. */
.set-group { margin:0 0 var(--sp-4); padding:var(--sp-1) var(--sp-5); background:var(--surface); border:1px solid var(--line); border-radius:var(--r-lg); }
.set-group h3 { margin:var(--sp-4) 0 var(--sp-1); font-size:var(--fs-lg); font-weight:600; line-height:1.3; overflow-wrap:anywhere; }
.set-row { display:grid; grid-template-columns:minmax(0, 1fr) minmax(0, 260px); gap:var(--sp-1) var(--sp-4); align-items:center; padding:var(--sp-2) 0; border-top:1px solid var(--line); }
.set-row:first-of-type { border-top:0; }
.set-row.wide { grid-template-columns:minmax(0, 1fr); }
/* Etiqueta: se toca para ir a su control (32 px de alto con ratón, 44 en táctil). La ayuda, atenuada debajo. */
.set-row > label { display:block; min-width:0; min-height:32px; padding:var(--sp-1) 0; color:var(--ink); font-size:var(--fs-md); font-weight:500; line-height:1.5; overflow-wrap:anywhere; }
.set-row > label small { display:block; margin-top:var(--sp-0); color:var(--ink-2); font-size:var(--fs-sm); font-weight:400; line-height:1.4; }
.set-tag { display:inline-block; margin-left:var(--sp-2); padding:0 var(--sp-2); color:var(--ink-2); font-size:var(--fs-xs); font-weight:500; line-height:1.5; vertical-align:middle;
  background:var(--surface-soft); border-radius:var(--r-sm); }
/* Campos dentro de la tarjeta: la base común sobre --surface-soft, a todo el ancho de su columna. */
.set-row input:not([type="checkbox"], [type="color"], [type="hidden"]), .set-row select { width:100%; min-width:0; background:var(--surface-soft); }
/* Interruptores: la casilla nativa con el acento al marcarse, dentro de una zona de 32 px (44 en táctil) que también la marca. */
.set-switch { display:inline-grid; place-items:center; justify-self:start; width:32px; height:32px; margin-left:calc(-1 * var(--sp-1)); border-radius:var(--r-md); cursor:pointer; }
.set-switch input { width:22px; height:22px; margin:0; accent-color:var(--accent); cursor:pointer; }
.set-switch input:disabled { cursor:default; }
/* Secretos: el ojo va dentro del campo, a su altura (lo guardado nunca llega a la página). */
.pw { position:relative; display:block; min-width:0; }
.pw input { padding-right:var(--sp-7); }
.pw-eye { position:absolute; top:0; right:0; width:44px; height:100%; min-height:44px; display:grid; place-items:center; padding:0;
  color:var(--ink-2); background:none; border:0; border-radius:var(--r-md); cursor:pointer; transition:color var(--dur-1) var(--ease); }
.pw-eye:focus-visible { outline-offset:-2px; }
.pw-eye:disabled { color:var(--ink-3); opacity:.5; cursor:default; }
.pw-eye[aria-pressed="false"] .eye-off { display:none; }
/* Categorías: chips --surface-soft con el selector de color nativo (E2: el color guardado tal cual), el nombre en neutro y ✕. */
.chips { display:flex; flex-direction:column; gap:var(--sp-3); min-width:0; }
.chip-list { display:flex; flex-wrap:wrap; gap:var(--sp-2); }
.chip { display:inline-flex; align-items:center; gap:0; min-width:0; max-width:100%; min-height:32px; padding:0; color:var(--ink-2); font-size:var(--fs-sm); font-weight:500; line-height:1.4;
  background:var(--surface-soft); border-radius:var(--r-full); }
.chip > span { min-width:0; padding:0 var(--sp-1); overflow-wrap:anywhere; }
.chip > span:last-child { padding-right:var(--sp-3); }
.chip-color { -webkit-appearance:none; appearance:none; flex:none; width:32px; height:32px; padding:var(--sp-1); font-size:var(--fs-sm); background:none; border:0; border-radius:var(--r-full); cursor:pointer; }
.chip-color::-webkit-color-swatch-wrapper { padding:0; }
.chip-color::-webkit-color-swatch { border:1px solid var(--line-strong); border-radius:var(--r-full); }
.chip-color::-moz-color-swatch { border:1px solid var(--line-strong); border-radius:var(--r-full); }
.chip-color:focus-visible { outline-offset:-2px; }
.chip-color:disabled { cursor:default; }
.chip-x { flex:none; display:grid; place-items:center; width:32px; height:32px; padding:0; font:inherit; font-size:var(--fs-sm); line-height:1; color:var(--ink-2);
  background:none; border:0; border-radius:var(--r-full); cursor:pointer; transition:color var(--dur-1) var(--ease), background-color var(--dur-1) var(--ease); }
.chip-x:focus-visible { outline-offset:-2px; }
.chip-x:disabled { color:var(--ink-3); opacity:.5; cursor:default; }
.chip-add { display:flex; gap:var(--sp-2); max-width:420px; }
.chip-add input { flex:1; min-width:0; background:var(--surface-soft); }
.chip-add .ghost { flex:none; min-height:44px; }
.chip-note { color:var(--warn); font-size:var(--fs-sm); line-height:1.4; }
.chip-note:empty { display:none; }
/* Dispositivos con la página abierta: filas como las de Apuntes y, debajo, sus botones secundarios. */
#set-sessions-list > .ap-row:first-child { border-top:0; }
#set-sessions-list > .ap-empty { padding:var(--sp-1) 0 var(--sp-2); }
#set-sessions .set-bar { margin:var(--sp-3) 0; }
/* Barra de Guardar: al pie del formulario, en el flujo (no tapa campos; el aviso emergente queda en el margen reservado de main). */
.set-bar { display:flex; flex-wrap:wrap; align-items:center; gap:var(--sp-2) var(--sp-3); margin:0 0 var(--sp-5); }
.set-bar .primary { margin-left:0; min-height:44px; }
#set-status:empty { display:none; }
/* Carga: el «Cargando…» de hoy y debajo el esqueleto quieto de Tareas (el script lo sustituye por los grupos). */
#set-groups > .empty { margin:0 0 var(--sp-2); color:var(--ink-2); font-size:var(--fs-sm); line-height:1.4; }
#set-groups > .skeleton i { height:96px; }
@media (hover:hover) and (pointer:fine) {
  .set-switch:hover { background:var(--surface-soft); }
  .pw-eye:hover:not(:disabled) { color:var(--ink); }
  .chip-x:hover:not(:disabled) { color:var(--danger); background:var(--surface); }
}
/* Táctil o pantalla estrecha: zonas de 44×44 px (el selector, el ✕ y la casilla crecen; el dibujo no). */
@media (pointer:coarse), (max-width:640px) {
  .set-row > label { min-height:44px; padding:var(--sp-2) 0; }
  .set-switch { width:44px; height:44px; margin-left:calc(-1 * var(--sp-3)); }
  .chip { min-height:44px; }
  .chip-color { width:44px; height:44px; padding:var(--sp-2); }
  .chip-x { width:44px; height:44px; }
}
@media (max-width:640px) {
  .set-group { padding:var(--sp-1) var(--sp-4); }
  .set-row { grid-template-columns:minmax(0, 1fr); }
}
/* Texto al 200 % en el teléfono (~188 px útiles, RF-40): el campo de categoría nueva y «+ Agregar» se apilan, y los
   botones de los avisos y de Dispositivos pueden partir su texto en dos líneas. */
@media (max-width:300px) {
  .chip-add { flex-wrap:wrap; }
  .chip-add input { flex:1 1 100%; }
  .set-note .ghost, .set-bar .ghost { max-width:100%; white-space:normal; text-align:center; }
}
@media (prefers-reduced-motion: reduce) {
  .pw-eye, .chip-x { transition:none; }
}

/* Voz — botón de hablar y panel de voz (docs/design.md, Componentes clave; RF-26, RF-30, RF-31, RF-38).
   Cada estado cambia el icono, no solo el color: reposo micrófono; grabando ■ sobre --danger con pulso;
   pensando, icono de espera girando; hablando ■. El pulso y el giro son la excepción E4. Los dos
   respetan las zonas seguras; con reducir movimiento no hay pulso, giro, escala ni desplazamiento
   (grabando muestra entonces un anillo fijo --danger). */
.talk-btn { position:fixed; right:max(var(--sp-4), env(safe-area-inset-right)); bottom:calc(var(--sp-4) + env(safe-area-inset-bottom)); z-index:15;
  width:60px; height:60px; padding:0; border:0; border-radius:var(--r-full); cursor:pointer; display:grid; place-items:center;
  background:var(--accent); color:var(--accent-ink); box-shadow:var(--shadow-float);
  transition:background-color var(--dur-1) var(--ease), color var(--dur-1) var(--ease), transform var(--dur-1) var(--ease-out); }
.talk-btn[hidden] { display:none; }
.talk-btn:active { transform:scale(.94); }
.talk-btn:focus-visible { outline:2px solid var(--ink); outline-offset:2px; }
.talk-btn svg { width:26px; height:26px; }
.talk-btn .i-stop, .talk-btn .i-wait { display:none; }
.talk-btn[data-state="grabando"] .i-mic, .talk-btn[data-state="hablando"] .i-mic, .talk-btn[data-state="pensando"] .i-mic { display:none; }
.talk-btn[data-state="grabando"] .i-stop, .talk-btn[data-state="hablando"] .i-stop { display:block; }
.talk-btn[data-state="grabando"] { background:var(--danger); color:var(--accent-ink); }
/* Pulso (E4): un anillo del mismo color que crece y se desvanece por detrás del icono (solo transform y opacity). */
.talk-btn::after { content:""; position:absolute; inset:0; z-index:-1; border-radius:var(--r-full); background:var(--danger); opacity:0; pointer-events:none; }
.talk-btn[data-state="grabando"]::after { animation:talk-pulse 1.2s ease-out infinite; }
@keyframes talk-pulse { from { opacity:.4; transform:scale(1); } to { opacity:0; transform:scale(1.35); } }
.talk-btn[data-state="pensando"] { cursor:default; }
.talk-btn[data-state="pensando"] .i-wait { display:block; animation:talk-spin 1s linear infinite; }
@keyframes talk-spin { to { transform:rotate(360deg); } }
@keyframes talk-fade { from { opacity:1; } to { opacity:.45; } }
/* Panel de voz: lo oído y la respuesta, encima del botón; entra como el aviso. */
.talk-panel { position:fixed; right:max(var(--sp-4), env(safe-area-inset-right)); bottom:calc(var(--sp-4) + var(--sp-7) + var(--sp-5) + env(safe-area-inset-bottom)); z-index:15;
  width:min(380px, calc(100% - max(var(--sp-4), env(safe-area-inset-left)) - max(var(--sp-4), env(safe-area-inset-right))));
  max-height:min(60vh, 420px); max-height:min(60dvh, 420px); overflow:auto; overscroll-behavior:contain;
  padding:var(--sp-3) var(--sp-7) var(--sp-3) var(--sp-4); background:var(--surface); color:var(--ink);
  border:1px solid var(--line); border-radius:var(--r-lg); box-shadow:var(--shadow-float); font-size:var(--fs-md); line-height:1.5;
  animation:talk-in var(--dur-2) var(--ease-out); }
@keyframes talk-in { from { opacity:0; transform:translateY(8px); } }
@keyframes talk-in-fade { from { opacity:0; } }
.talk-panel[hidden] { display:none; }
.talk-panel .heard { margin-bottom:var(--sp-1); color:var(--ink-3); font-size:var(--fs-xs); line-height:1.4; }
.talk-panel .heard:empty { display:none; }
.talk-panel .said { white-space:pre-line; overflow-wrap:anywhere; }
.talk-panel.error .said { color:var(--danger); }
.talk-panel .icon-btn { position:absolute; top:var(--sp-1); right:var(--sp-1); margin:0; }
@media (prefers-reduced-motion: reduce) {
  .talk-btn:active { transform:none; }
  /* Sin pulso, «grabando» lleva un anillo fijo --danger separado del botón, para no distinguirse
     de «hablando» (mismo ■) solo por el color (RF-38; decisión del usuario, 2026-11-18). */
  .talk-btn[data-state="grabando"]::after { animation:none; inset:calc(-1 * var(--sp-1)); background:transparent; border:2px solid var(--danger); opacity:1; }
  .talk-btn[data-state="pensando"] .i-wait { animation:talk-fade 1s ease-in-out infinite alternate; }
  .talk-panel { animation-name:talk-in-fade; }
}

/* Diálogos — editor de tarea, confirmación y foto de recibo (docs/design.md, Componentes clave; RF-17).
   Superficie, radio grande, sombra flotante y fondo --scrim. Las acciones van al pie y siempre a la vista:
   en el editor la fila queda fija al pie (sticky) y el contenido se desplaza por encima; en la
   confirmación se desplaza el texto y en la foto se encoge la imagen. En el teléfono el editor es una
   hoja inferior a todo el ancho. Solo `[open]` cambia display: sin él, el diálogo cerrado se vería. */
dialog#editor, dialog#ask, dialog#rc-photo { padding:0; color:var(--ink); background:var(--surface); border:1px solid var(--line);
  border-radius:var(--r-lg); box-shadow:var(--shadow-float); max-height:calc(100vh - 2 * var(--sp-4)); max-height:calc(100dvh - 2 * var(--sp-4)); }
dialog#editor::backdrop, dialog#ask::backdrop, dialog#rc-photo::backdrop { background:var(--scrim); }
dialog#editor[open], dialog#ask[open], dialog#rc-photo[open] { animation:dialog-in var(--dur-3) var(--ease-out); }
@keyframes dialog-in { from { opacity:0; transform:scale(.98); } }
@keyframes sheet-in { from { transform:translateY(100%); } }
@keyframes dialog-fade { from { opacity:0; } }
/* Editor de tarea */
dialog#editor { width:min(560px, calc(100vw - 2 * var(--sp-4))); overflow:auto; overscroll-behavior:contain; }
#ed-form { display:flex; flex-direction:column; gap:var(--sp-4); padding:var(--sp-4) var(--sp-5) 0; }
.ed-head { display:flex; align-items:flex-start; gap:var(--sp-3); }
.ed-head h3 { margin:0; font-size:var(--fs-lg); font-weight:600; line-height:1.3; }
.ed-head .linkish { display:inline-flex; align-items:center; min-height:32px; color:var(--ink-2); font-size:var(--fs-sm); }
.field { display:flex; flex-direction:column; gap:var(--sp-1); min-width:0; margin:0; padding:0; border:0; }
.field > span, .field legend, .field-label { padding:0; color:var(--ink-2); font-size:var(--fs-sm); font-weight:500; line-height:1.4; }
/* La etiqueta de un campo de fecha también se toca: crece hacia el hueco de encima (sin apartar nada) hasta 32 px, o 44 en táctil. */
label.field-label { display:flex; align-items:flex-end; min-height:32px; margin-top:calc(-1 * var(--sp-3)); }
.field input, .field select, .add-step input { width:100%; min-width:0; background:var(--surface-soft); }
.row2 { display:grid; grid-template-columns:1fr 1fr; gap:var(--sp-3); }
/* Urgencia: control segmentado; la opción elegida lleva fondo, borde y más peso (no solo color). */
.seg-ctl { display:grid; grid-template-columns:repeat(3, 1fr); gap:var(--sp-1); padding:var(--sp-1); background:var(--surface-soft); border:1px solid var(--line); border-radius:var(--r-md); }
.seg-ctl label { position:relative; }
.seg-ctl input { position:absolute; inset:0; margin:0; opacity:0; cursor:pointer; }
.seg-ctl span { display:flex; align-items:center; justify-content:center; gap:var(--sp-2); min-height:36px; padding:0 var(--sp-1);
  color:var(--ink-2); font-size:var(--fs-sm); border:1px solid transparent; border-radius:var(--r-sm); transition:background-color var(--dur-1) var(--ease), color var(--dur-1) var(--ease); }
.seg-ctl span::before { content:""; width:8px; height:8px; border-radius:var(--r-full); background:var(--u, var(--u-media)); }
.seg-ctl input:checked + span { color:var(--ink); background:var(--surface); border-color:var(--line-strong); font-weight:600; }
.seg-ctl input:focus-visible + span { outline:2px solid var(--focus); outline-offset:2px; }
.date-row { display:flex; gap:var(--sp-2); }
.date-row input { flex:1; }
#ed-form button:disabled:not(.primary, .ghost, .danger) { opacity:.5; cursor:default; }
.ed-steps { list-style:none; margin:var(--sp-1) 0 var(--sp-2); padding:0; border:1px solid var(--line); border-radius:var(--r-md); }
.ed-steps li { display:flex; align-items:center; gap:var(--sp-3); min-height:44px; padding:0 var(--sp-3); border-top:1px solid var(--line); font-size:var(--fs-sm); }
.ed-steps li:first-child { border-top:0; }
.ed-steps li.done .linkish { color:var(--ink-3); text-decoration:line-through; }
.ed-steps .linkish { flex:1; min-width:0; min-height:36px; }
.ed-steps .icon-btn { margin-left:0; font-size:var(--fs-xs); }
.ed-steps li.empty { color:var(--ink-2); }
.add-step { display:flex; gap:var(--sp-2); }
.ed-error { color:var(--danger); font-size:var(--fs-sm); }
.ed-error:empty { display:none; }
/* Acción principal del editor (Guardar): fila fija al pie del diálogo, por encima del contenido que se desplaza. */
.ed-actions { position:sticky; bottom:0; z-index:1; display:flex; flex-wrap:wrap; align-items:center; gap:var(--sp-2);
  margin:0 calc(-1 * var(--sp-5)); padding:var(--sp-3) var(--sp-5) calc(var(--sp-3) + env(safe-area-inset-bottom)); background:var(--surface); border-top:1px solid var(--line); }
/* Confirmación: el texto se desplaza si es largo; los botones quedan al pie. */
dialog#ask { width:min(400px, calc(100vw - 2 * var(--sp-4))); overflow:hidden; }
dialog#ask[open], dialog#rc-photo[open] { display:flex; flex-direction:column; }
dialog#ask p { flex:0 1 auto; min-height:0; overflow:auto; margin:0; padding:var(--sp-5) var(--sp-5) var(--sp-4); font-size:var(--fs-md); line-height:1.5; overflow-wrap:anywhere; }
.ask-actions { flex:none; display:flex; justify-content:flex-end; flex-wrap:wrap; gap:var(--sp-2); padding:0 var(--sp-5) var(--sp-5); }
.ask-actions button { margin-left:0; margin-right:0; }
/* Foto de recibo: la imagen y la lista se encogen para que «Cerrar» se vea siempre. */
dialog#rc-photo { width:min(560px, calc(100vw - 2 * var(--sp-4))); overflow:hidden; }
#rc-photo-img { flex:0 1 auto; display:block; width:100%; min-height:0; max-height:70vh; max-height:70dvh; margin:var(--sp-3) 0 0; padding:0 var(--sp-3); object-fit:contain; }
#rc-photo-items { flex:0 1 auto; min-height:0; overflow:auto; padding:0 var(--sp-3); }
#rc-photo-items ul { margin:var(--sp-2) 0 0; padding-left:var(--sp-5); color:var(--ink-2); font-size:var(--fs-sm); }
#rc-photo .ask-actions { padding:var(--sp-3); }
@media (hover:hover) and (pointer:fine) {
  .ed-head .linkish:not(:disabled):hover, .ed-steps .linkish:not(:disabled):hover { color:var(--accent); }
  .seg-ctl input:not(:checked):hover + span { color:var(--ink); }
}
@media (pointer:coarse), (max-width:640px) {
  .seg-ctl span, .ed-steps .linkish { min-height:44px; }
  .ed-head .linkish { min-height:44px; }
  label.field-label { min-height:44px; margin-top:calc(-1 * var(--sp-4)); }
}
@media (max-width:480px) { .row2 { grid-template-columns:1fr; } }
/* En el teléfono el editor sube desde abajo como hoja inferior a todo el ancho. */
@media (max-width:640px) {
  dialog#editor { width:100vw; max-width:100vw; max-height:92vh; max-height:92dvh; margin:auto 0 0; border-width:1px 0 0; border-radius:var(--r-lg) var(--r-lg) 0 0; }
  dialog#editor[open] { animation-name:sheet-in; }
  #ed-form { padding:var(--sp-4) var(--sp-4) 0; }
  .ed-actions { margin:0 calc(-1 * var(--sp-4)); padding:var(--sp-3) var(--sp-4) calc(var(--sp-3) + env(safe-area-inset-bottom)); }
  .ed-actions .ghost { margin-left:auto; }
  .ed-actions .primary { order:3; flex:1 1 100%; margin-left:0; }
  .date-row { flex-wrap:wrap; }
  .date-row input { flex:1 1 190px; }
}
/* Texto al 200 % en el teléfono (~188 px útiles, RF-40): la urgencia se apila en una columna y «Marcar como hecha»
   puede partir su texto, para que el editor no se desplace en horizontal. */
@media (max-width:300px) {
  .seg-ctl { grid-template-columns:minmax(0, 1fr); }
  .ed-actions .ghost { max-width:100%; white-space:normal; text-align:center; }
}
/* Reducir movimiento: los diálogos y la hoja solo aparecen, sin escala ni desplazamiento. */
@media (prefers-reduced-motion: reduce) {
  dialog#editor[open], dialog#ask[open], dialog#rc-photo[open] { animation-name:dialog-fade; }
}
</style>
</head>
<body>
<header>
  <div class="bar">
    <div class="brand"><svg class="brand-mark" viewBox="0 0 100 100" aria-hidden="true" focusable="false"><circle class="bm-bg" cx="50" cy="50" r="50"/><g class="bm-fg"><rect x="20" y="22" width="17" height="56" rx="2.5"/><rect x="63" y="22" width="17" height="56" rx="2.5"/><polygon points="28,48.4 72,34.9 72,52.6 28,66.1"/></g></svg>Hermes</div>
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
<div id="offline"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3.5 2.5 20h19L12 3.5z"/><path d="M12 10v4.5M12 17.5v.01"/></svg>Hermes no responde. Revisa que esté encendido.</div>

<div class="view" id="view-tareas" aria-busy="true">
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
  <div class="groups" id="groups"><div class="skeleton" aria-hidden="true"><i></i><i></i><i></i></div><span class="sr-only" role="status">Cargando las tareas</span></div>
</div>

<div class="view" id="view-vivo" aria-busy="true" hidden>
  <div class="stage-wrap">
    <span class="sr-only" role="status">Cargando el estado de la voz</span>
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

<div class="view" id="view-consumo" aria-busy="true" hidden>
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
    <div class="legend"><span><i class="swatch claude"></i>Claude</span><span><i class="swatch local"></i>Modelo local</span></div>
    <div class="chart-box" id="chart-box"><div class="skeleton" aria-hidden="true"><i></i><i></i><i></i></div><span class="sr-only" role="status">Cargando el consumo</span></div>
    <details class="table-view"><summary>Ver como tabla</summary><div class="wide" id="daily-table"></div></details>
  </section>
  <div class="grid2">
    <section><div class="label">Este mes por uso</div><div class="wide" id="by-purpose"></div></section>
    <section><div class="label">Últimas llamadas</div><div class="wide" id="recent-calls"></div></section>
  </div>
</div>

<div class="view" id="view-apuntes" aria-busy="true" hidden>
  <h1 id="ap-title">Apuntes</h1>
  <div class="subtitle">También puedes pedírselo a Hermes con tus palabras.</div>
  <nav class="subtabs" id="ap-tabs" aria-label="Apartados de Apuntes">
    <a href="#apuntes/listas" data-sub="listas">Listas<span id="ap-tab-listas"></span></a>
    <a href="#apuntes/habitos" data-sub="habitos">Hábitos<span id="ap-tab-habitos"></span></a>
    <a href="#apuntes/notas" data-sub="notas">Notas<span id="ap-tab-notas"></span></a>
    <a href="#apuntes/fechas" data-sub="fechas">Fechas<span id="ap-tab-fechas"></span></a>
    <a href="#apuntes/seguimientos" data-sub="seguimientos">Seguimientos<span id="ap-tab-seguimientos"></span></a>
    <a href="#apuntes/gastos" data-sub="gastos">Gastos<span id="ap-tab-gastos"></span></a>
    <a href="#apuntes/pagos" data-sub="pagos">Pagos<span id="ap-tab-pagos"></span></a>
    <a href="#apuntes/lecturas" data-sub="lecturas">Lecturas<span id="ap-tab-lecturas"></span></a>
  </nav>
  <div class="set-note" id="ap-quiet" hidden><span id="ap-quiet-text"></span><button type="button" class="ghost" id="ap-quiet-off" style="margin-left:0">Quitar el silencio</button></div>
  <template id="ap-x-icon"><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true" focusable="false"><path d="M6 6l12 12M18 6 6 18"/></svg></template>
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
    <section class="ap-page" data-sub="notas" hidden>
      <h3 class="ap-head">Notas <span id="ap-notes-count"></span></h3>
      <p class="ap-hint">Lo que Hermes recuerda de ti y usa al conversar. Toca una nota para corregirla.</p>
      <form class="ap-form ap-create" id="ap-note-form" autocomplete="off">
        <input id="ap-note-text" maxlength="500" placeholder="Nueva nota" aria-label="Nota">
        <button type="submit" class="primary">Guardar</button>
      </form>
      <div class="ap-list" id="ap-notes"></div>
    </section>
    <section class="ap-page" data-sub="fechas" hidden>
      <h3 class="ap-head">Fechas <span id="ap-dates-count"></span></h3>
      <p class="ap-hint">Hermes avisa un día antes y ese día. Toca un día del calendario para anotar algo en él, o el nombre de una fecha para corregirla. El año es opcional: sirve para saber cuántos cumple.</p>
      <div id="ap-dates-cal"></div>
      <form class="ap-form ap-create" id="ap-date-form" autocomplete="off">
        <select id="ap-date-kind" aria-label="Tipo"><option value="cumpleaños">Cumpleaños</option><option value="aniversario">Aniversario</option></select>
        <input id="ap-date-name" maxlength="80" placeholder="De quién" aria-label="De quién">
        <input id="ap-date-day" class="narrow" type="number" min="1" max="31" placeholder="Día" aria-label="Día">
        <select id="ap-date-month" aria-label="Mes"></select>
        <input id="ap-date-year" class="narrow" type="number" min="1900" placeholder="Año" aria-label="Año (opcional)" title="Año (opcional): para saber cuántos cumple">
        <button type="submit" class="primary">+ Agregar</button>
      </form>
      <div id="ap-dates"></div>
    </section>
    <section class="ap-page" data-sub="lecturas" hidden>
      <form class="ap-form ap-create" id="ln-form" autocomplete="off">
        <input id="ln-url" type="url" inputmode="url" maxlength="2000" placeholder="Pega un enlace (https://…)" aria-label="Enlace para leer después">
        <button type="submit" class="primary">+ Guardar</button>
      </form>
      <p class="ap-hint">También puedes mandarle el enlace a Hermes por Telegram. Lo resume el modelo de tu computadora y los domingos te recuerda lo que falta.</p>
      <div class="ap-list" id="ln-list"></div>
      <details class="ln-done" id="ln-done-box" hidden><summary id="ln-done-title"></summary><div class="ap-list" id="ln-done"></div></details>
    </section>
    <section class="ap-page" data-sub="pagos" hidden>
      <div class="rc-summary bl-summary" id="bl-summary"></div>
      <form class="ap-form ap-create bl-add" id="bl-form" autocomplete="off">
        <input id="bl-name" maxlength="60" placeholder="Qué pagas (luz, internet, Netflix…)" aria-label="Qué pagas">
        <input id="bl-amount" type="number" min="0.01" step="0.01" inputmode="decimal" placeholder="Monto (opcional)" aria-label="Monto; vacío si cambia cada vez">
        <select id="bl-every" aria-label="Cada cuánto"></select>
        <label class="bl-date">Próximo pago <input id="bl-due" type="date" aria-label="Fecha del próximo pago"></label>
        <button type="submit" class="primary">+ Agregar pago</button>
      </form>
      <p class="ap-hint">Hermes te avisa por Telegram 3 días antes y el día que vence. Al marcarlo como pagado queda en Gastos. También puedes decirle «pagué la luz 345».</p>
      <div class="ap-list" id="bl-list"></div>
    </section>
    <section class="ap-page" data-sub="gastos" hidden>
      <div class="rc-head">
        <button type="button" class="rc-nav" id="rc-prev" aria-label="Mes anterior">‹</button>
        <h3 id="rc-month"></h3>
        <button type="button" class="rc-nav" id="rc-next" aria-label="Mes siguiente">›</button>
      </div>
      <div class="rc-summary" id="rc-summary"></div>
      <p class="ap-hint">Para agregar un gasto, mándale a Hermes por Telegram la foto del recibo. La lee el modelo de tu computadora: la foto no sale de ahí. Toca un comercio para corregirlo y la foto para verla.</p>
      <div class="ap-list" id="rc-list"></div>
    </section>
    <section class="ap-page" data-sub="seguimientos" hidden>
      <h3 class="ap-head">Seguimientos <span id="ap-waiting-count"></span></h3>
      <p class="ap-hint">Lo que quedaron de mandarte o hacer otras personas. Hermes te pregunta a los días si ya llegó. Para agregar uno, dile «estoy esperando que…».</p>
      <form class="ap-form ap-create" id="ap-waiting-form" autocomplete="off">
        <input id="ap-waiting-text" maxlength="180" placeholder="Qué esperas (que Juan mande el contrato)" aria-label="Qué estás esperando">
        <input id="ap-waiting-days" class="narrow" type="number" min="1" max="60" value="3" aria-label="En cuántos días te pregunto" title="En cuántos días te pregunto">
        <button type="submit" class="primary">Agregar</button>
      </form>
      <div class="ap-list" id="ap-waiting"></div>
    </section>
    <div class="skeleton ap-loading" aria-hidden="true"><i></i><i></i><i></i></div><span class="sr-only ap-loading" role="status">Cargando los apuntes</span>
  </div>
</div>

<div class="view" id="view-ajustes" aria-busy="true" hidden>
  <h1>Ajustes</h1>
  <div class="subtitle" id="set-subtitle">Lo que cambies se guarda en el archivo de configuración de Hermes.</div>
  <div class="set-note" id="set-restart" hidden>
    <span>Hay cambios que se aplican al reiniciar Hermes.</span>
    <button type="button" class="ghost" id="set-restart-btn">Reiniciar Hermes</button>
  </div>
  <section class="set-group" id="set-sessions" hidden>
    <h3>Dispositivos con la página abierta</h3>
    <div id="set-sessions-list"></div>
    <div class="set-bar">
      <button type="button" class="ghost" id="set-sessions-all" hidden>Cerrar las demás</button>
      <button type="button" class="ghost" id="set-logout" hidden>Cerrar sesión aquí</button>
    </div>
  </section>
  <form id="set-form" autocomplete="off">
    <div id="set-groups"><div class="empty" role="status">Cargando…</div><div class="skeleton" aria-hidden="true"><i></i><i></i><i></i></div></div>
    <div class="set-bar"><button type="submit" class="primary" id="set-save" disabled>Guardar cambios</button><span class="subtitle" id="set-status" style="margin:0"></span></div>
  </form>
</div>

<div class="view" id="view-historial" aria-busy="true" hidden>
  <h2>Historial</h2>
  <div class="subtitle">Tus conversaciones con Hermes por Telegram y por voz, de la más antigua a la más reciente.</div>
  <div class="grid2">
    <div class="thread">
      <input class="search" id="search" type="search" placeholder="Buscar en el historial…" aria-label="Buscar en el historial">
      <div id="messages"><div class="empty" role="status">Cargando…</div><div class="skeleton" aria-hidden="true"><i></i><i></i><i></i></div></div>
    </div>
    <section style="align-self:start">
      <div class="label">Últimas veces que te escuchó por voz (desde el último arranque)</div>
      <div id="events"><div class="empty-state"><b>Di “Hermes” para empezar.</b></div></div>
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
// Diálogos (RF-29): showModal deja el foco dentro y cierra con Escape; al cerrarse, el foco vuelve al
// control que lo abrió. Si la lista se volvió a dibujar mientras tanto, se busca su copia por data-focus.
function openDialog(dialog, from, first) {
  if (dialog.open) return;
  dialog._opener = from || document.activeElement;
  dialog.showModal();
  if (first) first.focus();
}
function returnFocus(dialog) {
  const opener = dialog._opener;
  dialog._opener = null;
  if (!opener || opener === document.body) return;
  const key = opener.dataset && opener.dataset.focus;
  const target = opener.isConnected ? opener : key ? document.querySelector('[data-focus="' + key + '"]') : null;
  if (target) target.focus();
}
for (const id of ["editor", "ask", "rc-photo"]) $(id).addEventListener("close", () => returnFocus($(id)));
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
    openDialog(dialog, null, $("ask-no"));
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
const AP_SUBS = { listas: "Listas", habitos: "Hábitos", notas: "Notas", fechas: "Fechas", seguimientos: "Seguimientos", gastos: "Gastos", pagos: "Pagos", lecturas: "Lecturas" };
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
// Al tocar un día o una flecha, redraw vuelve a pintar el calendario: el foco vuelve a la copia nueva de ese control.
let calRefocus = null;  // { cal, key } del control que se tocó, solo mientras dura el redraw.
function monthGrid(cal, marks, redraw) {
  const today = new Date();
  const box = text("div", "cal", "");
  const head = text("div", "cal-head", "");
  const keep = (el, key) => {
    if (calRefocus && calRefocus.cal === cal && calRefocus.key === key) { calRefocus = null; setTimeout(() => { if (el.isConnected) el.focus(); }, 0); }
  };
  const touched = key => { calRefocus = { cal, key }; try { redraw(); } finally { calRefocus = null; } };
  const nav = (label, aria, step) => {
    const b = text("button", "cal-nav", label); b.type = "button"; b.setAttribute("aria-label", aria);
    const key = step < 0 ? "prev" : "next";
    b.onclick = () => { const d = new Date(cal.year, cal.month + step, 1); cal.year = d.getFullYear(); cal.month = d.getMonth(); cal.picked = null; touched(key); };
    keep(b, key);
    return b;
  };
  const now = text("button", "cal-nav", "Hoy"); now.type = "button";
  now.onclick = () => { cal.year = today.getFullYear(); cal.month = today.getMonth(); cal.picked = today.getDate(); touched("today"); };
  keep(now, "today");
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
    cell.onclick = () => { cal.picked = day; touched("day:" + day); };
    keep(cell, "day:" + day);
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
  // La casilla dibuja su círculo (::before) en una zona de 44 px; el ✓ va en su propio span, que solo se ve al marcar.
  const b = text("button", "tick", "");
  b.append(text("span", "", "✓"));
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
  // El título se corta a dos líneas (su span); completo, en el editor.
  const title = text("button", "task-title linkish", "");
  title.append(text("span", "", t.title));
  title.type = "button";
  title.setAttribute("aria-label", "Editar: " + t.title);
  title.dataset.focus = "t" + t.id;
  main.addEventListener("click", e => { if (!e.target.closest(".steps button, .tick")) openEditor(t.id, title); });
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
      name.dataset.focus = "t" + s.id;
      name.onclick = e => { e.stopPropagation(); openEditor(s.id, name); };
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
  const row = text("div", "task ended", "");  // Terminada o cancelada: título tachado, además de su etiqueta.
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
  $("view-tareas").setAttribute("aria-busy", "false");  // Ya hay datos: se quitan el esqueleto y el anuncio de carga.
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
function openEditor(id, from) {
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
  openDialog($("editor"), from);
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
  const before = document.activeElement;
  const buttons = [...$("ed-form").querySelectorAll("button")];
  buttons.forEach(b => b.disabled = true);
  $("ed-error").textContent = "";
  try { await work(); } catch (e) { $("ed-error").textContent = e.message; }
  buttons.forEach(b => b.disabled = false);
  $("ed-parent").disabled = !$("ed-parent").onclick;
  renderEditorSteps();
  // Un botón desactivado no recibe el foco: si la confirmación se cerró mientras esperaba, se le devuelve ahora.
  if ($("editor").open && !$("editor").contains(document.activeElement) && before && before.isConnected && !before.disabled) before.focus();
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
  if (!events.length) { const empty = text("div", "empty-state", ""); empty.append(text("b", "", "Di “Hermes” para empezar.")); box.append(empty); return; }
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
        sw.className = "swatch " + key; row.append(sw, document.createTextNode(label + ": " + num(value) + " tokens"));  // Misma muestra que la leyenda (--data-1 lisa, --data-2 rayada).
        tip.append(row);
      }
      if (d.cost) tip.append(text("div", "", "Costo equivalente: " + usd(d.cost)));
      tip.style.display = "block";
      const boxRect = box.getBoundingClientRect(), colRect = col.getBoundingClientRect();
      const left = colRect.left - boxRect.left + colRect.width / 2 - tip.offsetWidth / 2;
      tip.style.left = Math.max(0, Math.min(left, box.clientWidth - tip.offsetWidth)) + "px";
      tip.style.top = "0px";
    };
    col.addEventListener("mouseenter", show); col.addEventListener("focus", show); col.addEventListener("click", show);  // Ratón, teclado o toque.
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
    $("view-consumo").setAttribute("aria-busy", "false");  // Ya hay datos: el gráfico sustituyó al esqueleto y al anuncio de carga.
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
  if (!messages.length) {
    const empty = text("div", "empty-state card", "");
    empty.append(text("b", "", query ? "Nada coincide con tu búsqueda." : "Todavía no hay conversaciones."));
    box.append(empty);
  }
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
    $("view-historial").setAttribute("aria-busy", "false");  // Ya hay datos: la conversación sustituyó al «Cargando…» y al esqueleto.
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
  if (onRemove) { const x = apX(); x.type = "button"; x.setAttribute("aria-label", removeLabel); x.onclick = onRemove; row.appendChild(x); }
  return row;
}
function apCheck(on, label, onClick) {
  const b = text("button", "ap-check" + (on ? " on" : ""), ""); b.type = "button"; b.setAttribute("aria-label", label); b.onclick = onClick; return b;
}
// Botón ✕ de Apuntes: el dibujo es el SVG de la plantilla (trazo currentColor = --ink-2), no el carácter de la fuente.
function apX() {
  const b = text("button", "ap-x", "");
  b.appendChild($("ap-x-icon").content.firstElementChild.cloneNode(true));
  return b;
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
    apRefocus("item:" + item.id, name);
    name.onclick = () => { editingItem = item.id; editingText = item.text; renderLists(lists); };
    const remove = apX(); remove.type = "button"; remove.setAttribute("aria-label", "Quitar " + item.text);
    remove.onclick = () => apunte({ action: "list_remove", id: item.id }, true);
    row.append(check, name, remove);
    return row;
  }
  const row = text("form", "ap-row ap-editing", ""); row.autocomplete = "off";
  const input = document.createElement("input");
  input.maxLength = 100; input.value = editingText; input.setAttribute("aria-label", "Nuevo texto del elemento"); input.enterKeyHint = "done";
  input.oninput = () => { editingText = input.value; };
  const stop = () => { editingItem = null; editingText = ""; apFocusBack = "item:" + item.id; };
  input.onkeydown = event => { if (event.key === "Escape") { stop(); renderLists(lists); } };
  const save = text("button", "primary", "Guardar"); save.type = "submit";
  const cancel = apX(); cancel.type = "button"; cancel.setAttribute("aria-label", "Cancelar la edición");
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
      const add = text("button", "ghost", "Agregar"); add.type = "submit";
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
let apFocusBack = null;  // Al cerrar un editor de Listas, Notas, Fechas, Seguimientos, Gastos o Pagos, el foco vuelve al elemento que se corrigió.
function apRefocus(key, el) { if (apFocusBack === key) { apFocusBack = null; setTimeout(() => { if (el.isConnected) el.focus(); }, 0); } }
function noteRow(n) {
  const redraw = () => { if (lastApuntes) renderApuntes(lastApuntes); };
  if (editingNote !== n.id) {
    const row = text("div", "ap-row", "");
    const body = text("button", "grow ap-item", n.text); body.type = "button";
    apRefocus("note:" + n.id, body);
    body.setAttribute("aria-label", "Editar la nota: " + n.text); body.title = "Tocar para editar";
    body.onclick = () => { editingNote = n.id; editingNoteText = n.text; redraw(); };
    const remove = apX(); remove.type = "button"; remove.setAttribute("aria-label", "Borrar la nota");
    remove.onclick = async () => { if (await ask("¿Borrar esta nota? «" + n.text + "»")) apunte({ action: "note_delete", id: n.id }); };
    row.append(body, remove);
    return row;
  }
  const row = text("form", "ap-row ap-editing ap-editing-note", ""); row.autocomplete = "off";
  const input = document.createElement("textarea");
  input.maxLength = 500; input.rows = 3; input.value = editingNoteText; input.setAttribute("aria-label", "Nuevo texto de la nota"); input.enterKeyHint = "done";
  input.oninput = () => { editingNoteText = input.value; };
  const stop = () => { editingNote = null; editingNoteText = ""; apFocusBack = "note:" + n.id; };
  const save = text("button", "primary", "Guardar"); save.type = "submit";
  const cancel = apX(); cancel.type = "button"; cancel.setAttribute("aria-label", "Cancelar la edición");
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
    apRefocus("waiting:" + w.id, body);
    body.setAttribute("aria-label", "Editar el seguimiento: " + w.title); body.title = "Tocar para editar";
    if (w.due_at) body.appendChild(text("small", "", "Te pregunto el " + new Date(w.due_at * 1000).toLocaleDateString("es", { weekday: "long", day: "numeric", month: "short" })));
    body.onclick = () => { editingWaiting = w.id; editingWaitingText = w.title; editingWaitingDate = w.due_at ? isoDay(w.due_at) : ""; redraw(); };
    const remove = apX(); remove.type = "button"; remove.setAttribute("aria-label", "Borrar el seguimiento");
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
  const stop = () => { editingWaiting = null; editingWaitingText = ""; editingWaitingDate = ""; apFocusBack = "waiting:" + w.id; };
  const onKey = event => { if (event.key === "Escape") { stop(); redraw(); } };
  input.onkeydown = onKey; date.onkeydown = onKey;
  const save = text("button", "primary", "Guardar"); save.type = "submit";
  const cancel = apX(); cancel.type = "button"; cancel.setAttribute("aria-label", "Cancelar la edición");
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
    const cancel = apX(); cancel.type = "button"; cancel.setAttribute("aria-label", "Cancelar la edición");
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
    const actions = text("div", "hb-edit-actions", ""); actions.append(save, cancel);
    form.append(title, time, actions);
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
    const cell = text("button", "hb-day" + (d.done ? " on" : "") + (i === h.week.length - 1 ? " today" : ""), ""); cell.type = "button";
    cell.title = day + "/" + m + (d.done ? ": hecho · toca para desmarcar" : ": sin marcar · toca para marcar");
    cell.setAttribute("aria-pressed", String(d.done));
    cell.setAttribute("aria-label", (d.done ? "Desmarcar " : "Marcar hecho ") + (label === "hoy" ? "hoy" : "el " + day + "/" + m) + ": " + h.title);
    cell.onclick = () => apunte({ action: "habit_day", id: h.id, day: d.day, done: !d.done });
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
    const form = text("form", "ap-row ap-editing dt-edit", ""); form.autocomplete = "off";
    const fields = dateFields(editingDateFields, v => { editingDateFields = v; });
    const stop = () => { editingDate = null; editingDateFields = null; apFocusBack = "date:" + x.id; };
    const save = text("button", "primary", "Guardar"); save.type = "submit";
    const cancel = apX(); cancel.type = "button"; cancel.setAttribute("aria-label", "Cancelar la edición");
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
  const row = text("div", "ap-row dt-row" + (x.in_days === 0 ? " today" : x.in_days <= 7 ? " soon" : ""), "");
  const badge = text("div", "dt-badge", "");
  badge.append(text("b", "", String(Number(x.next.slice(8)))), text("span", "", AP_MONTHS[Number(x.next.slice(5, 7)) - 1].slice(0, 3)));
  const body = text("div", "dt-body", "");
  const title = text("button", "ap-item", dateTitle(x)); title.type = "button";
  apRefocus("date:" + x.id, title);
  title.title = "Tocar para corregir"; title.setAttribute("aria-label", "Corregir: " + x.label);
  title.onclick = () => { editingDate = x.id; editingDateFields = { kind: x.kind, name: x.name, day: x.day, month: x.month, year: x.year }; redraw(); };
  const when = dateWhen(x);
  const small = text("small", "", "");
  small.append(text("span", "when", when[0]), document.createTextNode(when.length > 1 ? " · " + when.slice(1).join(" · ") : ""));
  body.append(title, small);
  const remove = apX(); remove.type = "button"; remove.setAttribute("aria-label", "Borrar: " + x.label);
  remove.onclick = async () => { if (await ask("¿Borrar el " + x.label + "? Hermes dejará de avisarte.", "Borrar")) apunte({ action: "date_delete", id: x.id }); };
  row.append(badge, body, remove);
  return row;
}
// Las fechas en el orden en que llegan, agrupadas por mes, empezando por el actual: cada mes, su título y una tarjeta con sus filas.
function renderDates(dates) {
  const box = $("ap-dates"); box.textContent = "";
  if (!dates.length) {
    const list = text("div", "ap-list", "");
    list.appendChild(text("div", "ap-empty", "Todavía no hay fechas. Anota cumpleaños y aniversarios aquí arriba y Hermes te avisa un día antes y ese día."));
    box.appendChild(list);
    return;
  }
  const thisYear = new Date().getFullYear();
  let list = null, key = "";
  for (const x of dates) {
    const [y, m] = x.next.split("-").map(Number);
    if (y + "-" + m !== key) {
      key = y + "-" + m;
      const group = text("div", "dt-group", "");
      list = text("div", "ap-list", "");
      group.append(text("h4", "", capital(AP_MONTHS[m - 1]) + (y !== thisYear ? " " + y : "")), list);
      box.appendChild(group);
    }
    list.appendChild(dateRow(x));
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
// Un apartado de Apuntes cuya función está apagada en Ajustes no se muestra; si estabas en él, vuelves a Listas.
function featureTab(sub, enabled) {
  const link = document.querySelector('#ap-tabs a[data-sub="' + sub + '"]');
  if (link) link.hidden = !enabled;
  if (!enabled && currentView() === "apuntes" && currentSub() === sub) location.hash = "#apuntes/listas";
}
/* ---------- Lecturas: enlaces para leer después ---------- */
let linksSerialized = "";
function linkAgo(ts) {
  const days = Math.floor((Date.now() / 1000 - ts) / 86400);
  return days <= 0 ? "hoy" : days === 1 ? "ayer" : "hace " + days + " días";
}
function linkRow(l) {
  const row = text("div", "ap-row ln-row" + (l.read_at ? " read" : ""), "");
  const body = text("div", "ln-body", "");
  const a = document.createElement("a");
  a.href = /^https?:/.test(l.url) ? l.url : "#"; a.target = "_blank"; a.rel = "noopener noreferrer"; a.textContent = l.title;
  a.className = "ln-title"; a.title = l.title;  // Un título largo se corta con …: completo al pasar el ratón y al abrirlo.
  const meta = l.site + " · " + linkAgo(l.saved_at);
  const small = text("small", "", meta); small.title = meta;
  body.append(a, small);
  if (l.summary) body.appendChild(text("p", "ln-summary", l.summary));
  const actions = text("div", "bl-actions", "");
  const toggle = text("button", "ghost bl-paid", l.read_at ? "↩ No leído" : "✓ Leído"); toggle.type = "button";
  toggle.setAttribute("aria-label", (l.read_at ? "Volver a para leer: " : "Marcar como leído: ") + l.title);
  toggle.dataset.focus = "ln" + l.id;
  toggle.onclick = async () => {
    try {
      toast((await send("/links", { action: l.read_at ? "unread" : "read", id: l.id })).message);
      await loadLinks(true);
      // El foco sigue al enlace en su lista nueva; si quedó dentro de «Leídos» cerrado, va a «Leídos (n)».
      const moved = document.querySelector('[data-focus="ln' + l.id + '"]');
      if (moved && !moved.closest("details:not([open])")) moved.focus(); else if (!$("ln-done-box").hidden) $("ln-done-title").focus();
    } catch (e) { toast(e.message); }
  };
  const remove = apX(); remove.type = "button"; remove.setAttribute("aria-label", "Quitar: " + l.title);
  remove.onclick = async () => {
    if (!(await ask("¿Quitar «" + l.title + "»?", "Quitar"))) return;
    try { toast((await send("/links", { action: "delete", id: l.id })).message); await loadLinks(true); } catch (e) { toast(e.message); }
  };
  actions.append(toggle, remove);
  row.append(body, actions);
  return row;
}
async function loadLinks(force) {
  try {
    const res = await fetch("/links", { cache: "no-store" });
    if (!res.ok) return;
    const data = await res.json();
    if (!data.links) return;
    featureTab("lecturas", data.enabled);
    const unread = data.links.filter(l => !l.read_at), read = data.links.filter(l => l.read_at);
    $("ap-tab-lecturas").textContent = unread.length || "";
    const serialized = JSON.stringify(data);
    if (!force && serialized === linksSerialized) return;
    linksSerialized = serialized;
    const box = $("ln-list"); box.textContent = "";
    if (!unread.length) box.appendChild(text("div", "ap-empty", read.length ? "Ya leíste todo lo que guardaste. 🎉" : "Todavía no tienes enlaces. Pega uno aquí arriba o mándaselo a Hermes."));
    unread.forEach(l => box.appendChild(linkRow(l)));
    $("ln-done-box").hidden = !read.length;
    $("ln-done-title").textContent = "Leídos (" + read.length + ")";
    const done = $("ln-done"); done.textContent = "";
    read.forEach(l => done.appendChild(linkRow(l)));
  } catch {}
}
$("ln-form").addEventListener("submit", async event => {
  event.preventDefault();
  const url = $("ln-url").value.trim();
  if (!url) { $("ln-url").focus(); return; }
  const button = $("ln-form").querySelector("button"); button.disabled = true; button.textContent = "Leyendo…";
  try { toast((await send("/links", { action: "add", url })).message); $("ln-url").value = ""; await loadLinks(true); }
  catch (e) { toast(e.message); }
  finally { button.disabled = false; button.textContent = "+ Guardar"; }
});
/* ---------- Pagos que se repiten ---------- */
let billsData = null, billsSerialized = "", editingBill = null, editingBillFields = null, payingBill = null;
function billsMoney(total, currency) {
  const sign = (billsData && billsData.currencies[currency]) || currency;
  return sign + " " + Number(total).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
function billSelect(options, value, label) {
  const select = document.createElement("select"); select.setAttribute("aria-label", label);
  options.forEach(([v, t]) => { const o = document.createElement("option"); o.value = v; o.textContent = t; select.appendChild(o); });
  select.value = String(value);
  return select;
}
function billRow(b) {
  const redraw = () => renderBills();
  if (editingBill === b.id) {
    const v = editingBillFields;
    const form = text("form", "ap-row ap-editing rc-edit", ""); form.autocomplete = "off";
    const name = document.createElement("input"); name.maxLength = 60; name.value = v.name; name.setAttribute("aria-label", "Qué pagas");
    const amount = document.createElement("input"); amount.type = "number"; amount.min = "0.01"; amount.step = "0.01"; amount.value = v.amount || "";
    amount.placeholder = "Variable"; amount.setAttribute("aria-label", "Monto; vacío si cambia cada vez");
    const currency = billSelect(Object.entries(billsData.currencies), v.currency, "Moneda");
    const every = billSelect(Object.entries(billsData.frequencies), v.every_months, "Cada cuánto");
    const category = billSelect(billsData.categories.map(c => [c, capital(c)]), v.category, "Categoría");
    const dueLabel = text("label", "rc-warranty", "Próximo pago ");
    const due = document.createElement("input"); due.type = "date"; due.value = v.next_due; due.setAttribute("aria-label", "Fecha del próximo pago");
    dueLabel.appendChild(due);
    const remindLabel = text("label", "rc-warranty", "Avisarme ");
    const remind = billSelect([[0, "solo el día"], [1, "1 día antes"], [2, "2 días antes"], [3, "3 días antes"], [5, "5 días antes"], [7, "una semana antes"]], v.remind_days, "Cuándo avisarte");
    remindLabel.appendChild(remind);
    const read = () => ({ name: name.value, amount: amount.value, currency: currency.value, every_months: every.value, category: category.value, next_due: due.value, remind_days: remind.value });
    [name, amount, currency, every, category, due, remind].forEach(el => { el.oninput = () => { editingBillFields = read(); }; });
    const stop = () => { editingBill = null; editingBillFields = null; apFocusBack = "bill:" + b.id; };
    const save = text("button", "primary", "Guardar"); save.type = "submit";
    const cancel = apX(); cancel.type = "button"; cancel.setAttribute("aria-label", "Cancelar la edición");
    cancel.onclick = () => { stop(); redraw(); };
    form.onkeydown = event => { if (event.key === "Escape") { stop(); redraw(); } };
    form.onsubmit = async event => {
      event.preventDefault();
      const f = read();
      if (!f.name.trim()) { name.focus(); return; }
      save.disabled = true;
      try {
        toast((await send("/bills", { action: "edit", id: b.id, name: f.name.trim(), amount: parseFloat(f.amount) || null, currency: f.currency,
          every_months: parseInt(f.every_months, 10), category: f.category, next_due: f.next_due, remind_days: parseInt(f.remind_days, 10) })).message);
        stop();
        await loadBills(true);
      } catch (e) { toast(e.message); save.disabled = false; }
    };
    form.append(name, amount, currency, every, category, dueLabel, remindLabel, save, cancel);
    setTimeout(() => { if (editingBill === b.id && !form.contains(document.activeElement)) name.focus(); }, 0);
    return form;
  }
  const row = text("div", "ap-row dt-row bl-row" + (b.left < 0 ? " late" : b.left <= 3 ? " soon" : ""), "");
  const [y, m, d] = b.next_due.split("-").map(Number);
  const badge = text("div", "dt-badge", "");
  badge.append(text("b", "", String(d)), text("span", "", AP_MONTHS[m - 1].slice(0, 3)));
  const body = text("div", "dt-body", "");
  const title = text("button", "ap-item", b.name); title.type = "button"; title.title = "Tocar para corregir";
  title.setAttribute("aria-label", "Corregir el pago " + b.name);
  apRefocus("bill:" + b.id, title);
  title.onclick = () => { editingBill = b.id; payingBill = null; editingBillFields = { name: b.name, amount: b.amount, currency: b.currency, every_months: b.every_months, category: b.category, next_due: b.next_due, remind_days: b.remind_days }; redraw(); };
  const small = text("small", "", "");
  const amount = b.amount ? billsMoney(b.amount, b.currency) : "monto variable";
  small.append(text("span", "when", capital(b.when)), document.createTextNode(" · " + amount + " · " + billsData.frequencies[b.every_months]));
  body.append(title, small);
  if (b.last) {
    const [ly, lm, ld] = b.last.day.split("-").map(Number);
    body.appendChild(text("small", "", "Último pago: " + ld + " " + AP_MONTHS[lm - 1].slice(0, 3) + ", " + billsMoney(b.last.total, b.currency)));
  }
  const actions = text("div", "bl-actions", "");
  if (payingBill === b.id) {
    const form = text("form", "bl-pay", ""); form.autocomplete = "off";
    const input = document.createElement("input"); input.type = "number"; input.min = "0.01"; input.step = "0.01"; input.inputMode = "decimal";
    input.value = b.expected || ""; input.placeholder = "Monto"; input.setAttribute("aria-label", "Cuánto pagaste de " + b.name);
    const ok = text("button", "primary", "Anotar"); ok.type = "submit";
    const no = apX(); no.type = "button"; no.setAttribute("aria-label", "Cancelar");
    no.onclick = () => { payingBill = null; apFocusBack = "pay:" + b.id; redraw(); };
    form.onsubmit = async event => {
      event.preventDefault();
      const value = parseFloat(input.value);
      if (!(value > 0)) { input.focus(); return; }
      ok.disabled = true;
      try { toast((await send("/bills", { action: "pay", id: b.id, amount: value })).message); payingBill = null; apFocusBack = "pay:" + b.id; await loadBills(true); loadReceipts(true); }
      catch (e) { toast(e.message); ok.disabled = false; }
    };
    form.append(input, ok, no);
    actions.appendChild(form);
    setTimeout(() => { if (payingBill === b.id && document.activeElement !== input) { input.focus(); input.select(); } }, 0);
  } else {
    const pay = text("button", "ghost", "✅ Pagado"); pay.type = "button"; pay.setAttribute("aria-label", "Anotar que pagué " + b.name);
    apRefocus("pay:" + b.id, pay);
    pay.onclick = () => { payingBill = b.id; editingBill = null; redraw(); };
    const remove = apX(); remove.type = "button"; remove.setAttribute("aria-label", "Quitar el pago " + b.name);
    remove.onclick = async () => {
      if (!(await ask("¿Quitar " + b.name + "? Hermes deja de avisarte. Lo que ya pagaste sigue en Gastos.", "Quitar"))) return;
      try { toast((await send("/bills", { action: "delete", id: b.id })).message); await loadBills(true); } catch (e) { toast(e.message); }
    };
    actions.append(pay, remove);
  }
  row.append(badge, body, actions);
  return row;
}
function renderBills() {
  if (!billsData) return;
  const summary = $("bl-summary"); summary.textContent = "";
  const top = text("div", "rc-total", "");
  const n = billsData.bills.length;
  top.append(text("b", "", billsMoney(billsData.monthly, "GTQ")), text("span", "", "al mes en " + (n === 1 ? "1 pago" : n + " pagos")));
  summary.appendChild(top);
  const next = billsData.bills[0];
  if (next) summary.appendChild(text("div", "bl-next", "Próximo: " + next.name + ", " + next.when + "."));
  else summary.appendChild(text("div", "bl-next", "Agrega aquí abajo lo que pagas cada mes o cada año."));
  const box = $("bl-list"); box.textContent = "";
  if (!n) { box.appendChild(text("div", "ap-empty", "Todavía no tienes pagos. Agrega la luz, el agua, el internet, el teléfono o tus suscripciones.")); }
  billsData.bills.forEach(b => box.appendChild(billRow(b)));
}
async function loadBills(force) {
  try {
    const res = await fetch("/bills", { cache: "no-store" });
    if (!res.ok) return;
    const data = await res.json();
    if (!data.bills) return;
    const serialized = JSON.stringify(data);
    $("ap-tab-pagos").textContent = data.bills.filter(b => b.left <= 3).length || "";
    featureTab("pagos", data.enabled);
    if (!$("bl-every").options.length) {
      Object.entries(data.frequencies).forEach(([v, t]) => { const o = document.createElement("option"); o.value = v; o.textContent = capital(t); $("bl-every").appendChild(o); });
    }
    if (!force && (serialized === billsSerialized || editingBill !== null || payingBill !== null)) return;  // No pisa lo que estás escribiendo.
    billsSerialized = serialized; billsData = data;
    renderBills();
  } catch {}
}
$("bl-form").addEventListener("submit", async event => {
  event.preventDefault();
  const name = $("bl-name").value.trim();
  if (!name) { $("bl-name").focus(); return; }
  if (!$("bl-due").value) { $("bl-due").focus(); toast("Elige la fecha del próximo pago."); return; }
  try {
    toast((await send("/bills", { action: "add", name, amount: parseFloat($("bl-amount").value) || null,
      every_months: parseInt($("bl-every").value, 10), next_due: $("bl-due").value })).message);
    $("bl-name").value = ""; $("bl-amount").value = ""; $("bl-due").value = ""; $("bl-every").value = "1";
    await loadBills(true);
  } catch (e) { toast(e.message); }
});
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
function rcPhoto(r, from) {
  $("rc-photo-img").src = "/recibo/" + r.id + ".jpg";
  const items = $("rc-photo-items"); items.textContent = "";
  if (r.items.length) { const ul = document.createElement("ul"); r.items.forEach(i => ul.appendChild(text("li", "", i))); items.appendChild(ul); }
  openDialog($("rc-photo"), from);
}
$("rc-photo-close").addEventListener("click", () => $("rc-photo").close());
$("rc-photo").addEventListener("click", event => { if (event.target === $("rc-photo")) $("rc-photo").close(); });
function receiptRow(r) {
  const redraw = () => renderReceipts();
  if (editingReceipt === r.id) {
    const v = editingReceiptFields;
    const form = text("form", "ap-row ap-editing rc-edit", ""); form.autocomplete = "off";
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
    const stop = () => { editingReceipt = null; editingReceiptFields = null; apFocusBack = "receipt:" + r.id; };
    const save = text("button", "primary", "Guardar"); save.type = "submit";
    const cancel = apX(); cancel.type = "button"; cancel.setAttribute("aria-label", "Cancelar la edición");
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
  const row = text("div", "ap-row rc-row", "");
  const thumb = text("button", "rc-thumb", r.photo ? "" : "🧾"); thumb.type = "button";
  if (r.photo) { const img = document.createElement("img"); img.src = "/recibo/" + r.id + ".jpg"; img.alt = ""; img.loading = "lazy"; thumb.appendChild(img); }
  thumb.setAttribute("aria-label", "Ver la foto del recibo de " + r.merchant);
  thumb.disabled = !r.photo;
  thumb.dataset.focus = "rc" + r.id;
  thumb.onclick = () => rcPhoto(r, thumb);
  const body = text("div", "rc-body", "");
  const name = text("button", "ap-item", r.merchant); name.type = "button"; name.title = "Tocar para corregir";
  apRefocus("receipt:" + r.id, name);
  name.setAttribute("aria-label", "Corregir el recibo de " + r.merchant);
  name.onclick = () => { editingReceipt = r.id; editingReceiptFields = { merchant: r.merchant, total: r.total, currency: r.currency, day: r.day, category: r.category, warranty_until: r.warranty_until }; redraw(); };
  const detail = rcDay(r.day) + " · " + r.category + (r.warranty_until && r.warranty_until >= receiptsData.today ? " · 🛡 hasta " + rcDay(r.warranty_until) : "");
  body.append(name, text("small", "", detail));
  const amount = text("div", "rc-amount", rcMoney(r.total, r.currency));
  const remove = apX(); remove.type = "button"; remove.setAttribute("aria-label", "Borrar el recibo de " + r.merchant);
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
    if (Object.keys(inputs).length === 1) apRefocus("budgets:first", input);
    row.append(text("span", "", capital(c)), input);
    form.appendChild(row);
  });
  const buttons = text("div", "rc-budget-buttons", "");
  const save = text("button", "primary", "Guardar"); save.type = "submit";
  const cancel = text("button", "ghost", "Cancelar"); cancel.type = "button";
  cancel.onclick = () => { editingBudgets = false; apFocusBack = "budgets"; renderReceipts(); };  buttons.append(cancel, save);
  form.appendChild(buttons);
  form.onsubmit = async event => {
    event.preventDefault();
    const budgets = {};
    for (const c in inputs) { const v = parseFloat(inputs[c].value); budgets[c] = v > 0 ? v : null; }
    save.disabled = true;
    try {
      toast((await send("/receipts", { action: "budgets", budgets })).message);
      editingBudgets = false; apFocusBack = "budgets";
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
  if (receiptsData.budget_enabled) {
    const edit = text("button", "ap-link", budgetTotal ? "Cambiar presupuestos" : "Poner presupuestos"); edit.type = "button";
    edit.onclick = () => { editingBudgets = !editingBudgets; apFocusBack = editingBudgets ? "budgets:first" : "budgets"; renderReceipts(); };
    apRefocus("budgets", edit);
    top.appendChild(edit);
  }
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
    box.appendChild(text("div", "ap-empty", key === today.slice(0, 7)
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
    featureTab("gastos", data.enabled);
    if (!force && (serialized === receiptsSerialized || editingReceipt !== null || editingBudgets)) return;  // No pisa lo que estás corrigiendo.
    receiptsSerialized = serialized; receiptsData = data;
    renderReceipts();
  } catch {}
}
// Si el botón que se usó queda desactivado (primer o último mes a la vista), el foco pasa al otro para no perderse.
function rcStep(step) {
  rcMonth.month += step;
  if (rcMonth.month < 0) { rcMonth.month = 11; rcMonth.year--; } else if (rcMonth.month > 11) { rcMonth.month = 0; rcMonth.year++; }
  editingReceipt = null; renderReceipts();
  const used = $(step < 0 ? "rc-prev" : "rc-next"), other = $(step < 0 ? "rc-next" : "rc-prev");
  if (used.disabled && document.activeElement !== other) other.focus();
}
$("rc-prev").addEventListener("click", () => rcStep(-1));
$("rc-next").addEventListener("click", () => rcStep(1));
async function loadApuntes(force) {
  loadReceipts(force);
  loadBills(force);
  loadLinks(force);
  try {
    const res = await fetch("/extras", { cache: "no-store" });
    if (res.status === 401) { location.href = "/login"; return; }
    const data = await res.json();
    $("view-apuntes").setAttribute("aria-busy", "false");  // Ya hay datos: se quitan el esqueleto y el anuncio de carga.
    document.querySelectorAll("#view-apuntes .ap-loading").forEach(el => el.remove());
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
// Interruptor: la casilla va dentro de una etiqueta vacía que es su zona de 32 px (44 en táctil); sigue siendo la misma casilla.
function withZone(control) {
  if (control.type !== "checkbox") return control;
  const zone = document.createElement("label");
  zone.className = "set-switch";
  zone.append(control);
  return zone;
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
      row.appendChild(label); row.appendChild(withZone(withEye(settingControl(s)))); card.appendChild(row);
    }
    box.appendChild(card);
  }
  $("set-restart").hidden = !data.restart_needed || !data.can_restart;
  $("set-save").disabled = !Object.keys(settingChanges()).length;
  $("view-ajustes").setAttribute("aria-busy", "false");  // Ya hay datos: los grupos sustituyeron al «Cargando…» y al esqueleto.
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
    if (res.status === 404) { $("set-groups").textContent = ""; $("set-groups").appendChild(text("div", "empty", "Los ajustes no están disponibles.")); $("view-ajustes").setAttribute("aria-busy", "false"); return; }
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
    $("pill").classList.remove("off");
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
      $("view-vivo").setAttribute("aria-busy", "false");  // Ya hay datos: el disco muestra el logo y se quita el anuncio de carga.
    }
    if (s.version !== shown && currentView() === "historial") { shown = s.version; loadHistory(); }
  } catch {
    $("offline").style.display = restarting ? "none" : "block";
    $("pill").classList.remove("on");
    $("pill").classList.add("off");
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
                "img-src 'self' data:; manifest-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'; "
                "font-src 'self'",
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
            elif path in FONT_FILES and (FONTS / FONT_FILES[path]).exists():
                self._send(200, "font/woff2", (FONTS / FONT_FILES[path]).read_bytes())
            elif path == "/status":
                self._send(200, "application/json", json.dumps(status.snapshot()).encode("utf-8"))
            elif path == "/settings" and status.settings is not None:
                self._json(200, status.settings.snapshot(not self._is_remote()))
            elif path in ("/tasks", "/usage", "/history", "/extras", "/receipts", "/bills", "/links"):
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
            if path not in ("/voice", "/tasks", "/speak", "/extras", "/receipts", "/bills", "/links") or (path != "/voice" and not status.has_action(path[1:])):
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
