"""Acceso a la página desde fuera de esta computadora (por un túnel), siempre con contraseña.

Apagado por defecto. Se enciende solo si en .env están las dos cosas:
  HERMES_PUBLIC_HOST     el dominio del túnel, por ejemplo baf.hola-hermes.com
  HERMES_PAGE_PASSWORD   la contraseña de la página (se guarda cifrada de un solo sentido)

Cómo se protege:
- Cada dispositivo que entra recibe una llave al azar. Hermes guarda solo su huella, así que una llave
  robada no sirve para adivinar la contraseña, y cada sesión se puede cerrar por separado.
- Un dispositivo nuevo, además de la contraseña, necesita que el dueño lo apruebe desde Telegram.
- Los intentos fallidos se cuentan por origen y sobreviven a un reinicio: un extraño no bloquea al dueño.

Desde esta computadora (127.0.0.1) la página sigue abriendo sin contraseña.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
import logging
import os
import secrets
import threading
import time
from typing import Any, Callable
from urllib.parse import urlsplit

log = logging.getLogger(__name__)

MIN_PASSWORD = 12
SESSION_SECONDS = 30 * 24 * 3600
PENDING_SECONDS = 300  # Tiempo para aprobar en Telegram un dispositivo nuevo.
TOUCH_SECONDS = 60  # «Visto por última vez» se actualiza como mucho una vez por minuto.
COOKIE = "hermes_session"
FREE_ATTEMPTS = 5  # Fallos seguidos permitidos antes de empezar a bloquear.
MAX_LOCK_SECONDS = 3600
LOCKOUT_KEY = "page_lockouts"
MAX_TRACKED_ORIGINS = 200
HASH_PREFIX = "scrypt$"
# Un túnel agrega estos encabezados; una petición hecha directamente en esta computadora no los trae.
FORWARD_HEADERS = ("X-Forwarded-For", "X-Forwarded-Host", "X-Forwarded-Proto", "Forwarded", "X-Real-Ip")


class ApprovalUnavailable(Exception):
    """La contraseña era correcta, pero no se pudo pedir la aprobación por Telegram."""


def clean_host(raw: str) -> str:
    """"https://Mi-Nombre.ngrok-free.app/" -> "mi-nombre.ngrok-free.app"."""
    raw = raw.strip().lower()
    if not raw:
        return ""
    return (urlsplit(raw if "//" in raw else "//" + raw).netloc or "").strip("/")


def is_hashed(stored: str) -> bool:
    return stored.startswith(HASH_PREFIX)


def hash_password(password: str) -> str:
    """Huella de la contraseña con scrypt y sal propia: del archivo no se puede sacar la contraseña."""
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return HASH_PREFIX + base64.b64encode(salt).decode("ascii") + "$" + base64.b64encode(digest).decode("ascii")


def verify_password(stored: str, given: str) -> bool:
    if is_hashed(stored):
        try:
            _, raw_salt, raw_digest = stored.split("$")
            salt, expected = base64.b64decode(raw_salt), base64.b64decode(raw_digest)
            digest = hashlib.scrypt(given.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=len(expected))
        except (ValueError, TypeError):
            return False
        return hmac.compare_digest(digest, expected)
    # Contraseña todavía en texto claro (configuración anterior): se compara sin filtrar el largo.
    return hmac.compare_digest(hashlib.sha256(given.encode("utf-8")).digest(), hashlib.sha256(stored.encode("utf-8")).digest())


def device_label(agent: str) -> str:
    """«Chrome en Android», a partir de lo que el navegador dice de sí mismo. Es solo una ayuda para reconocerlo."""
    agent = agent or ""
    system = next(
        (name for mark, name in (("iPhone", "iPhone"), ("iPad", "iPad"), ("Android", "Android"), ("Windows", "Windows"),
                                 ("Mac OS", "Mac"), ("Linux", "Linux")) if mark in agent),
        "",
    )
    browser = next(
        (name for mark, name in (("Edg/", "Edge"), ("OPR/", "Opera"), ("Firefox/", "Firefox"), ("Chrome/", "Chrome"),
                                 ("CriOS/", "Chrome"), ("Safari/", "Safari")) if mark in agent),
        "",
    )
    if browser and system:
        return f"{browser} en {system}"
    return browser or system or "Dispositivo desconocido"


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8", "replace")).hexdigest()


class MemorySessions:
    """Guarda las sesiones en memoria. Lo usa la página cuando no hay base de datos (por ejemplo en pruebas)."""

    def __init__(self) -> None:
        self._rows: dict[int, dict[str, Any]] = {}
        self._kv: dict[str, str] = {}
        self._next = 1

    def session_add(self, hashed: str, now: int, expires_at: int, label: str, ip: str, approved: bool) -> int:
        session_id, self._next = self._next, self._next + 1
        self._rows[session_id] = {
            "id": session_id, "token_hash": hashed, "created_at": now, "last_seen": now, "expires_at": expires_at,
            "label": label, "ip": ip, "approved": int(approved), "revoked_at": None,
        }
        return session_id

    def session_find(self, hashed: str) -> dict[str, Any] | None:
        return next((dict(row) for row in self._rows.values() if row["token_hash"] == hashed), None)

    def session_get(self, session_id: int) -> dict[str, Any] | None:
        row = self._rows.get(session_id)
        return dict(row) if row else None

    def session_update(self, session_id: int, **fields: Any) -> None:
        if session_id in self._rows:
            self._rows[session_id].update(fields)

    def sessions_open(self, now: int) -> list[dict[str, Any]]:
        rows = [dict(r) for r in self._rows.values() if r["revoked_at"] is None and r["expires_at"] > now and r["approved"]]
        return sorted(rows, key=lambda r: -r["last_seen"])

    def kv_get(self, key: str) -> str | None:
        return self._kv.get(key)

    def kv_set(self, key: str, value: str) -> None:
        self._kv[key] = value


class RemoteAccess:
    def __init__(
        self,
        host: str = "",
        password: str = "",
        clock: Callable[[], float] = time.time,
        store: Any = None,
        approver: Callable[[int, str, str], None] | None = None,
    ):
        self.host = clean_host(host)
        self._secret = password
        self._clock = clock
        self._store = store if store is not None else MemorySessions()
        # Pide por Telegram la aprobación de un dispositivo nuevo: (número de sesión, dispositivo, origen).
        # Sin él (no hay chat de Telegram configurado), la contraseña basta, como antes.
        self.approver = approver
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return bool(self.host) and (is_hashed(self._secret) or len(self._secret) >= MIN_PASSWORD)

    @property
    def problem(self) -> str:
        """Por qué está apagado aunque se intentó encender, o cadena vacía."""
        if self.host and not self.enabled:
            return f"falta HERMES_PAGE_PASSWORD de al menos {MIN_PASSWORD} caracteres"
        if self._secret and not self.host:
            return "falta HERMES_PUBLIC_HOST con el dominio del túnel"
        return ""

    @property
    def origin(self) -> str:
        return f"https://{self.host}"

    @staticmethod
    def is_forwarded(headers: Any) -> bool:
        return any(headers.get(name) for name in FORWARD_HEADERS)

    @staticmethod
    def client_ip(headers: Any) -> str:
        """De dónde viene la visita, según el túnel. Solo para contar intentos y mostrárselo al dueño."""
        raw = headers.get("Cf-Connecting-Ip") or (headers.get("X-Forwarded-For") or "").split(",")[0]
        cleaned = "".join(char for char in raw.strip() if char.isalnum() or char in ".:")
        return cleaned[:45]

    # --- Intentos fallidos, por origen ---

    def _lockouts(self) -> dict[str, list[float]]:
        try:
            data = json.loads(self._store.kv_get(LOCKOUT_KEY) or "{}")
        except ValueError:
            data = {}
        return data if isinstance(data, dict) else {}

    def _save_lockouts(self, data: dict[str, list[float]], now: float) -> None:
        # Se olvidan los orígenes sin fallos pendientes ni bloqueo vigente, y se limita cuántos se recuerdan.
        kept = {ip: entry for ip, entry in data.items() if entry[0] > 0 and (entry[1] > now or now - entry[2] < MAX_LOCK_SECONDS)}
        if len(kept) > MAX_TRACKED_ORIGINS:
            kept = dict(sorted(kept.items(), key=lambda item: item[1][2])[-MAX_TRACKED_ORIGINS:])
        self._store.kv_set(LOCKOUT_KEY, json.dumps(kept))

    def locked_for(self, ip: str = "") -> int:
        with self._lock:
            entry = self._lockouts().get(ip)
            return max(0, int(entry[1] - self._clock() + 0.999)) if entry else 0

    # --- Entrar ---

    def login(self, password: str, ip: str = "", agent: str = "") -> str | None:
        """Devuelve la llave de la sesión (el valor de la cookie), o None si la contraseña es incorrecta o hay bloqueo.

        Con aprobación por Telegram, la sesión nace pendiente y no sirve hasta que el dueño la apruebe.
        """
        if not self.enabled:
            return None
        with self._lock:
            now = self._clock()
            lockouts = self._lockouts()
            failures, locked_until, _ = lockouts.get(ip, [0, 0.0, 0.0])
            if now < locked_until:
                return None
            if not verify_password(self._secret, password):
                failures += 1
                if failures >= FREE_ATTEMPTS:
                    locked_until = now + min(MAX_LOCK_SECONDS, 60 * 2 ** (failures - FREE_ATTEMPTS))
                lockouts[ip] = [failures, locked_until, now]
                self._save_lockouts(lockouts, now)
                log.warning("Página: contraseña incorrecta en acceso remoto desde %s (%d seguidas)", ip or "origen desconocido", failures)
                return None
            if ip in lockouts:
                del lockouts[ip]
                self._save_lockouts(lockouts, now)
            token = secrets.token_urlsafe(32)
            label = device_label(agent)
            needs_approval = self.approver is not None
            expires = int(now) + (PENDING_SECONDS if needs_approval else SESSION_SECONDS)
            session_id = self._store.session_add(token_hash(token), int(now), expires, label, ip, not needs_approval)
        if needs_approval:
            try:
                self.approver(session_id, label, ip)  # type: ignore[misc]
            except Exception as exc:
                self._store.session_update(session_id, revoked_at=int(self._clock()))
                log.warning("Página: no se pudo pedir la aprobación por Telegram: %s", exc)
                raise ApprovalUnavailable(str(exc)) from exc
            log.info("Página: %s desde %s espera aprobación por Telegram", label, ip or "origen desconocido")
        else:
            log.info("Página: sesión remota iniciada (%s, %s)", label, ip or "origen desconocido")
        return token

    def _session(self, cookie_header: str | None) -> dict[str, Any] | None:
        if not self.enabled or not cookie_header:
            return None
        for part in cookie_header.split(";"):
            name, _, value = part.strip().partition("=")
            if name != COOKIE or not value:
                continue
            row = self._store.session_find(token_hash(value))
            if row is None or row["revoked_at"] is not None or row["expires_at"] <= self._clock():
                return None
            return row
        return None

    def state(self, cookie_header: str | None) -> str:
        """"ok" (puede pasar), "pending" (falta aprobarla en Telegram) o "none"."""
        row = self._session(cookie_header)
        if row is None:
            return "none"
        if not row["approved"]:
            return "pending"
        now = int(self._clock())
        if now - row["last_seen"] >= TOUCH_SECONDS:
            self._store.session_update(row["id"], last_seen=now)
        return "ok"

    def valid(self, cookie_header: str | None) -> bool:
        return self.state(cookie_header) == "ok"

    # --- Aprobar, rechazar y cerrar ---

    def approve(self, session_id: int) -> bool:
        row = self._store.session_get(session_id)
        now = int(self._clock())
        if row is None or row["revoked_at"] is not None or row["approved"] or row["expires_at"] <= now:
            return False
        self._store.session_update(session_id, approved=1, expires_at=now + SESSION_SECONDS, last_seen=now)
        log.info("Página: sesión %d aprobada por Telegram (%s)", session_id, row["label"])
        return True

    def revoke(self, session_id: int) -> bool:
        row = self._store.session_get(session_id)
        if row is None or row["revoked_at"] is not None:
            return False
        self._store.session_update(session_id, revoked_at=int(self._clock()))
        log.info("Página: sesión %d cerrada (%s)", session_id, row["label"])
        return True

    def logout(self, cookie_header: str | None) -> bool:
        row = self._session(cookie_header)
        return self.revoke(row["id"]) if row else False

    def revoke_all(self, keep_cookie: str | None = None) -> int:
        """Cierra todas las sesiones abiertas, salvo la del dispositivo que lo pide. Devuelve cuántas cerró."""
        keep = self._session(keep_cookie)
        count = 0
        for row in self._store.sessions_open(int(self._clock())):
            if keep is None or row["id"] != keep["id"]:
                count += int(self.revoke(row["id"]))
        return count

    def sessions(self, current_cookie: str | None = None) -> list[dict[str, Any]]:
        """Las sesiones abiertas, para mostrárselas al dueño. Nunca incluye las llaves."""
        current = self._session(current_cookie)
        return [
            {
                "id": row["id"], "label": row["label"], "ip": row["ip"], "created_at": row["created_at"],
                "last_seen": row["last_seen"], "current": current is not None and row["id"] == current["id"],
            }
            for row in self._store.sessions_open(int(self._clock()))
        ]

    def cookie(self, value: str) -> str:
        return f"{COOKIE}={value}; Max-Age={SESSION_SECONDS}; Path=/; HttpOnly; Secure; SameSite=Lax"

    @staticmethod
    def clear_cookie() -> str:
        return f"{COOKIE}=; Max-Age=0; Path=/; HttpOnly; Secure; SameSite=Lax"


_PAGE_HEAD = """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#0a0c0f">
<meta name="robots" content="noindex">
<title>Hermes</title>
<style>
* { box-sizing:border-box; }
body { margin:0; min-height:100vh; min-height:100dvh; display:grid; place-items:center; padding:24px; color-scheme:dark;
  background:#0a0c0f; color:#eeece6; font:16px/1.5 "Segoe UI",system-ui,sans-serif; }
form, .box { width:min(360px, 100%); display:flex; flex-direction:column; gap:14px; }
h1 { font-size:22px; margin:0; display:flex; align-items:center; gap:10px; }
h1 i { width:11px; height:11px; border-radius:50%; background:#f2c230; }
label { color:#a19f96; font-size:14px; display:flex; flex-direction:column; gap:6px; }
input { font:inherit; color:inherit; background:#14171b; border:1px solid #262a30; border-radius:10px; padding:12px 14px; }
input:focus { outline:none; border-color:#f2c230; }
button, a.button { font:inherit; font-weight:600; color:#14110a; background:#f2c230; border:0; border-radius:10px; padding:12px; cursor:pointer;
  text-align:center; text-decoration:none; }
p { margin:0; color:#a19f96; font-size:15px; }
p.error { color:#ef7a63; font-size:14px; min-height:1.5em; }
</style>
</head>
<body>
"""

LOGIN_PAGE = _PAGE_HEAD + """<form method="post" action="/login">
  <h1><i></i>Hermes</h1>
  <label>Contraseña de la página
    <input type="password" name="password" autocomplete="current-password" required autofocus maxlength="200">
  </label>
  <button type="submit">Entrar</button>
  <p class="error" role="alert">__ERROR__</p>
</form>
</body>
</html>
"""

WAIT_PAGE = _PAGE_HEAD + """<div class="box">
  <h1><i></i>Hermes</h1>
  <p id="message" role="status">La contraseña es correcta. Ahora abre Telegram y toca <b>«Sí, soy yo»</b> en el mensaje que te acabo de mandar.</p>
  <p>Esta página avanza sola en cuanto lo apruebes. Tienes 5 minutos.</p>
  <a class="button" href="/login" id="again" hidden>Volver a intentar</a>
</div>
<script>
async function check() {
  try {
    const state = (await (await fetch("/login/state", { cache: "no-store" })).json()).state;
    if (state === "ok") { location.replace("/"); return; }
    if (state === "none") {
      document.getElementById("message").textContent = "La solicitud se rechazó o venció. Vuelve a entrar con tu contraseña.";
      document.getElementById("again").hidden = false;
      return;
    }
  } catch {}
  setTimeout(check, 2000);
}
setTimeout(check, 1500);
</script>
</body>
</html>
"""


def login_page(error: str = "") -> bytes:
    return LOGIN_PAGE.replace("__ERROR__", html.escape(error)).encode("utf-8")


def wait_page() -> bytes:
    return WAIT_PAGE.encode("utf-8")
