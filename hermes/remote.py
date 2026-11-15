"""Acceso a la página desde fuera de esta computadora (por un túnel como ngrok), siempre con contraseña.

Apagado por defecto. Se enciende solo si en .env están las dos cosas:
  HERMES_PUBLIC_HOST     el dominio del túnel, por ejemplo mi-nombre.ngrok-free.app
  HERMES_PAGE_PASSWORD   una contraseña de al menos 12 caracteres, solo para esta página

Desde esta computadora (127.0.0.1) la página sigue abriendo sin contraseña.
"""
from __future__ import annotations

import hashlib
import hmac
import html
import logging
import threading
import time
from typing import Any, Callable
from urllib.parse import urlsplit

log = logging.getLogger(__name__)

MIN_PASSWORD = 12
SESSION_SECONDS = 30 * 24 * 3600
COOKIE = "hermes_session"
FREE_ATTEMPTS = 5  # Fallos seguidos permitidos antes de empezar a bloquear.
MAX_LOCK_SECONDS = 3600
# Un túnel agrega estos encabezados; una petición hecha directamente en esta computadora no los trae.
FORWARD_HEADERS = ("X-Forwarded-For", "X-Forwarded-Host", "X-Forwarded-Proto", "Forwarded", "X-Real-Ip")


def clean_host(raw: str) -> str:
    """"https://Mi-Nombre.ngrok-free.app/" -> "mi-nombre.ngrok-free.app"."""
    raw = raw.strip().lower()
    if not raw:
        return ""
    return (urlsplit(raw if "//" in raw else "//" + raw).netloc or "").strip("/")


class RemoteAccess:
    def __init__(self, host: str = "", password: str = "", clock: Callable[[], float] = time.time):
        self.host = clean_host(host)
        self._password = password
        self._clock = clock
        self._lock = threading.Lock()
        self._failures = 0
        self._locked_until = 0.0
        self._key = hashlib.sha256(b"hermes-session:" + password.encode("utf-8")).digest()

    @property
    def enabled(self) -> bool:
        return bool(self.host) and len(self._password) >= MIN_PASSWORD

    @property
    def problem(self) -> str:
        """Por qué está apagado aunque se intentó encender, o cadena vacía."""
        if self.host and len(self._password) < MIN_PASSWORD:
            return f"falta HERMES_PAGE_PASSWORD de al menos {MIN_PASSWORD} caracteres"
        if self._password and not self.host:
            return "falta HERMES_PUBLIC_HOST con el dominio del túnel"
        return ""

    @property
    def origin(self) -> str:
        return f"https://{self.host}"

    @staticmethod
    def is_forwarded(headers: Any) -> bool:
        return any(headers.get(name) for name in FORWARD_HEADERS)

    def locked_for(self) -> int:
        with self._lock:
            return max(0, int(self._locked_until - self._clock() + 0.999))

    def login(self, password: str) -> str | None:
        """Devuelve el valor de la cookie de sesión, o None si la contraseña es incorrecta o hay bloqueo."""
        if not self.enabled:
            return None
        with self._lock:
            now = self._clock()
            if now < self._locked_until:
                return None
            if hmac.compare_digest(
                hashlib.sha256(password.encode("utf-8")).digest(), hashlib.sha256(self._password.encode("utf-8")).digest()
            ):
                self._failures = 0
                log.info("Página: sesión remota iniciada")
                return self._sign(int(now) + SESSION_SECONDS)
            self._failures += 1
            if self._failures >= FREE_ATTEMPTS:
                self._locked_until = now + min(MAX_LOCK_SECONDS, 60 * 2 ** (self._failures - FREE_ATTEMPTS))
            log.warning("Página: contraseña incorrecta en acceso remoto (%d seguidas)", self._failures)
            return None

    def _sign(self, expires: int) -> str:
        return f"{expires}.{hmac.new(self._key, str(expires).encode('ascii'), hashlib.sha256).hexdigest()}"

    def valid(self, cookie_header: str | None) -> bool:
        if not self.enabled or not cookie_header:
            return False
        for part in cookie_header.split(";"):
            name, _, value = part.strip().partition("=")
            if name != COOKIE:
                continue
            expires, _, _ = value.partition(".")
            if not expires.isdigit() or int(expires) < self._clock():
                return False
            return hmac.compare_digest(value.encode("latin-1", "replace"), self._sign(int(expires)).encode("ascii"))
        return False

    def cookie(self, value: str) -> str:
        return f"{COOKIE}={value}; Max-Age={SESSION_SECONDS}; Path=/; HttpOnly; Secure; SameSite=Lax"


LOGIN_PAGE = """<!doctype html>
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
form { width:min(360px, 100%); display:flex; flex-direction:column; gap:14px; }
h1 { font-size:22px; margin:0; display:flex; align-items:center; gap:10px; }
h1 i { width:11px; height:11px; border-radius:50%; background:#f2c230; }
label { color:#a19f96; font-size:14px; display:flex; flex-direction:column; gap:6px; }
input { font:inherit; color:inherit; background:#14171b; border:1px solid #262a30; border-radius:10px; padding:12px 14px; }
input:focus { outline:none; border-color:#f2c230; }
button { font:inherit; font-weight:600; color:#14110a; background:#f2c230; border:0; border-radius:10px; padding:12px; cursor:pointer; }
p { margin:0; color:#ef7a63; font-size:14px; min-height:1.5em; }
</style>
</head>
<body>
<form method="post" action="/login">
  <h1><i></i>Hermes</h1>
  <label>Contraseña de la página
    <input type="password" name="password" autocomplete="current-password" required autofocus maxlength="200">
  </label>
  <button type="submit">Entrar</button>
  <p role="alert">__ERROR__</p>
</form>
</body>
</html>
"""


def login_page(error: str = "") -> bytes:
    return LOGIN_PAGE.replace("__ERROR__", html.escape(error)).encode("utf-8")
