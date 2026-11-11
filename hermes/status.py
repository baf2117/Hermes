"""Página local que muestra en vivo qué oye Hermes. Solo acepta conexiones de esta computadora."""
from __future__ import annotations

import json
import logging
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

log = logging.getLogger(__name__)

MAX_EVENTS = 25


class VoiceStatus:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state = "inactiva"
        self._level = 0.0
        self._threshold = 0.0
        self._events: deque[dict[str, Any]] = deque(maxlen=MAX_EVENTS)
        self._version = 0

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
            }


PAGE = """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Hermes en vivo</title>
<style>
:root { --bg:#f6f5f1; --card:#fff; --ink:#20201d; --muted:#6c6a62; --line:#e2dfd6; --accent:#2f6f5e; --warn:#b4532a; --bar:#d9d5c9; }
@media (prefers-color-scheme: dark) { :root { --bg:#16171a; --card:#212327; --ink:#ecebe6; --muted:#a09e96; --line:#34363b; --accent:#62b8a0; --warn:#e58a63; --bar:#3a3c42; } }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--ink); font:16px/1.45 system-ui,"Segoe UI",sans-serif; }
main { max-width:760px; margin:0 auto; padding:24px 16px 48px; }
h1 { font-size:20px; margin:0 0 16px; font-weight:600; }
section { background:var(--card); border:1px solid var(--line); border-radius:12px; padding:18px; margin-bottom:14px; }
.label { color:var(--muted); font-size:13px; margin-bottom:6px; }
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
#offline { display:none; color:var(--warn); margin-bottom:12px; }
.empty { color:var(--muted); }
</style>
</head>
<body>
<main>
<h1>Hermes en vivo</h1>
<div id="offline">Hermes no responde. Revisa que esté encendido.</div>
<section>
  <div class="label">Estado</div>
  <div id="state">Conectando…</div>
  <div id="hint"></div>
</section>
<section>
  <div class="label">Micrófono</div>
  <div class="meter"><div id="fill"></div><div id="mark"></div></div>
  <div class="nums"><span id="level">Nivel: 0</span><span id="threshold">Mínimo para contar como voz: 0</span></div>
</section>
<section>
  <div class="label">Últimas veces que te escuchó</div>
  <div id="events"><div class="empty">Di “Hermes” para empezar.</div></div>
</section>
</main>
<script>
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
const NAMES = { grabar: "grabar", transcribir: "transcribir", pensar: "pensar", hablar: "hablar", total: "total" };
const SCALE = 3000;
const $ = id => document.getElementById(id);
let shown = -1;
function text(tag, cls, value) { const el = document.createElement(tag); if (cls) el.className = cls; el.textContent = value; return el; }
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
      times.append(text("span", "chip" + (name === "total" ? " total" : ""), (NAMES[name] || name) + " " + seconds + " s"));
    }
    item.append(times);
    box.append(item);
  }
}
async function tick() {
  try {
    const res = await fetch("/status", { cache: "no-store" });
    const s = await res.json();
    $("offline").style.display = "none";
    const [title, hint] = STATES[s.state] || [s.state, ""];
    $("state").textContent = title; $("hint").textContent = hint;
    $("fill").style.width = pct(s.level) + "%";
    $("fill").classList.toggle("voice", s.level >= s.threshold && s.threshold > 0);
    $("mark").style.left = pct(s.threshold) + "%";
    $("level").textContent = "Nivel: " + s.level;
    $("threshold").textContent = "Mínimo para contar como voz: " + s.threshold;
    if (s.version !== shown) { shown = s.version; renderEvents(s.events); }
  } catch { $("offline").style.display = "block"; }
  setTimeout(tick, 200);
}
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
                "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'",
            )
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            # Valida el Host para que una web externa no pueda leer esto mediante DNS rebinding.
            if self.headers.get("Host") not in allowed_hosts:
                self._send(403, "text/plain; charset=utf-8", b"Solo desde esta computadora.")
            elif self.path == "/":
                self._send(200, "text/html; charset=utf-8", PAGE.encode("utf-8"))
            elif self.path == "/status":
                self._send(200, "application/json", json.dumps(status.snapshot()).encode("utf-8"))
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
