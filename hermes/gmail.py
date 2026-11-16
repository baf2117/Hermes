"""Lectura de Gmail con permiso de solo lectura. Hermes nunca envía, cambia ni borra correos.

La autorización se hace una vez con `python -m hermes gmail-auth`: abre el navegador, el dueño
acepta, y Google entrega una llave de renovación que se guarda en la carpeta de datos (fuera del
repositorio). El permiso pedido es únicamente gmail.readonly.
"""
from __future__ import annotations

import base64
import hashlib
import html
import json
import logging
import re
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from email.utils import parseaddr
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger(__name__)

SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://gmail.googleapis.com/gmail/v1/users/me"
# Solo la bandeja principal: sin promociones, redes sociales, notificaciones ni foros.
INBOX_QUERY = "in:inbox category:primary -from:me"
MAX_BODY_CHARS = 2500
MAX_LISTED = 25
TIMEOUT = 20.0
AUTH_WAIT_SECONDS = 300

DEFAULT_ACCOUNT = "personal"
_ACCOUNT_NAME = re.compile(r"[a-z0-9]{1,20}")

Fetch = Callable[[urllib.request.Request], bytes]


def valid_account(name: str) -> bool:
    return bool(_ACCOUNT_NAME.fullmatch(name))


def token_path(folder: Path, account: str) -> Path:
    """La cuenta «personal» usa google-token.json; las demás, google-token-<nombre>.json."""
    return Path(folder) / ("google-token.json" if account == DEFAULT_ACCOUNT else f"google-token-{account}.json")


def find_accounts(folder: Path) -> list[tuple[str, Path]]:
    """Las cuentas ya autorizadas, la personal primero."""
    found = []
    for path in sorted(Path(folder).glob("google-token*.json")):
        name = DEFAULT_ACCOUNT if path.name == "google-token.json" else path.stem.removeprefix("google-token-")
        if valid_account(name) and path == token_path(folder, name):
            found.append((name, path))
    return sorted(found, key=lambda item: item[0] != DEFAULT_ACCOUNT)


class GmailError(Exception):
    """Fallo temporal: sin red, Google caído, respuesta inesperada. Se reintenta."""


class GmailAuthError(GmailError):
    """El permiso ya no sirve (caducó o fue retirado): hay que volver a autorizar."""


@dataclass(frozen=True)
class Email:
    id: str
    sender: str  # "Nombre <direccion>" tal como viene; se muestra siempre la dirección real.
    subject: str
    ts: int
    body: str
    unread: bool = True


def _fetch(request: urllib.request.Request) -> bytes:
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        if exc.code in (400, 401) and ("invalid_grant" in detail or "invalid_client" in detail or exc.code == 401):
            raise GmailAuthError(f"Google rechazó el permiso ({exc.code})") from exc
        raise GmailError(f"Google respondió {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise GmailError(str(exc)) from exc


def load_client(path: Path) -> tuple[str, str]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        client = data.get("installed") or data["web"]
        return str(client["client_id"]), str(client["client_secret"])
    except (OSError, ValueError, KeyError, AttributeError) as exc:
        raise GmailAuthError(f"no pude leer la credencial de Google: {exc}") from exc


def display_sender(raw: str) -> str:
    """"Ana López <ana@x.com>" -> "Ana López <ana@x.com>"; sin nombre, solo la dirección."""
    name, address = parseaddr(raw)
    name = re.sub(r"\s+", " ", name).strip()[:60]
    address = address.strip()[:120]
    if name and address and name.lower() != address.lower():
        return f"{name} <{address}>"
    return address or name or "remitente desconocido"


def _decode(data: str) -> str:
    try:
        return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", "replace")
    except ValueError:
        return ""


def _strip_html(text: str) -> str:
    text = re.sub(r"(?is)<(script|style|head)\b.*?</\1>", " ", text)
    text = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</li>", "\n", text)
    return html.unescape(re.sub(r"<[^>]+>", " ", text))


def _find_part(payload: dict[str, Any], mime: str) -> str:
    if payload.get("mimeType") == mime and (data := payload.get("body", {}).get("data")):
        return _decode(data)
    for part in payload.get("parts") or []:
        if found := _find_part(part, mime):
            return found
    return ""


def body_text(payload: dict[str, Any], snippet: str = "") -> str:
    text = _find_part(payload, "text/plain") or _strip_html(_find_part(payload, "text/html")) or html.unescape(snippet)
    text = re.sub(r"[ \t\r​‌﻿]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text).strip()
    return text[:MAX_BODY_CHARS]


def parse_message(message: dict[str, Any]) -> Email:
    payload = message.get("payload") or {}
    headers = {h.get("name", "").lower(): h.get("value", "") for h in payload.get("headers") or []}
    return Email(
        id=str(message["id"]),
        sender=display_sender(headers.get("from", "")),
        subject=re.sub(r"\s+", " ", headers.get("subject", "")).strip()[:200] or "(sin asunto)",
        ts=int(message.get("internalDate", 0)) // 1000,
        body=body_text(payload, message.get("snippet", "")),
        unread="UNREAD" in (message.get("labelIds") or []),
    )


class GmailClient:
    def __init__(self, client_path: Path, token_path: Path, fetch: Fetch = _fetch, clock: Callable[[], float] = time.time):
        self.client_path, self.token_path = Path(client_path), Path(token_path)
        self._fetch, self._clock = fetch, clock
        self._access = ""
        self._expires = 0.0
        self._lock = threading.Lock()

    @property
    def configured(self) -> bool:
        return self.client_path.exists() and self.token_path.exists()

    def _access_token(self) -> str:
        with self._lock:
            if self._access and self._clock() < self._expires - 60:
                return self._access
            client_id, client_secret = load_client(self.client_path)
            try:
                refresh = json.loads(self.token_path.read_text(encoding="utf-8"))["refresh_token"]
            except (OSError, ValueError, KeyError) as exc:
                raise GmailAuthError("falta autorizar el correo") from exc
            form = urllib.parse.urlencode(
                {"client_id": client_id, "client_secret": client_secret, "refresh_token": refresh, "grant_type": "refresh_token"}
            ).encode("ascii")
            body = self._json(urllib.request.Request(TOKEN_URL, data=form, method="POST"))
            try:
                self._access = str(body["access_token"])
                self._expires = self._clock() + float(body.get("expires_in", 3600))
            except (KeyError, TypeError, ValueError) as exc:
                raise GmailError("Google no entregó la llave de acceso") from exc
            return self._access

    def _json(self, request: urllib.request.Request) -> dict[str, Any]:
        try:
            data = json.loads(self._fetch(request).decode("utf-8"))
        except ValueError as exc:
            raise GmailError("respuesta de Google ilegible") from exc
        if not isinstance(data, dict):
            raise GmailError("respuesta de Google inesperada")
        return data

    def _get(self, path: str, **params: Any) -> dict[str, Any]:
        url = f"{API}/{path}" + ("?" + urllib.parse.urlencode(params) if params else "")
        return self._json(urllib.request.Request(url, headers={"Authorization": f"Bearer {self._access_token()}"}))

    def address(self) -> str:
        """La dirección de la cuenta autorizada, para confirmar que es la que se quería conectar."""
        return str(self._get("profile").get("emailAddress", ""))

    def list_ids(self, after_ts: int) -> list[str]:
        """Los correos de la bandeja principal recibidos después de ese momento, del más viejo al más nuevo."""
        data = self._get("messages", q=f"{INBOX_QUERY} after:{int(after_ts)}", maxResults=MAX_LISTED)
        return [str(m["id"]) for m in reversed(data.get("messages") or []) if "id" in m]

    def get(self, message_id: str) -> Email:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", message_id):
            raise GmailError("identificador de correo inválido")
        return parse_message(self._get(f"messages/{message_id}", format="full"))


def authorize(client_path: Path, token_path: Path, open_browser: Callable[[str], Any], fetch: Fetch = _fetch) -> None:
    """Pide el permiso de solo lectura en el navegador y guarda la llave de renovación."""
    client_id, client_secret = load_client(client_path)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
    state = secrets.token_urlsafe(24)
    result: dict[str, str] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            ok = query.get("state", [""])[0] == state and "code" in query
            if ok:
                result["code"] = query["code"][0]
            elif "error" in query:
                result["error"] = query["error"][0][:100]
            message = "Listo. Ya puedes cerrar esta pestaña y volver a Hermes." if ok else "No se completó la autorización."
            body = f"<!doctype html><meta charset='utf-8'><title>Hermes</title><p style='font:18px sans-serif'>{message}</p>".encode("utf-8")
            self.send_response(200 if ok else 400)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_: Any) -> None:
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    redirect = f"http://127.0.0.1:{server.server_address[1]}"
    server.timeout = 1.0
    url = AUTH_URL + "?" + urllib.parse.urlencode(
        {
            "client_id": client_id, "redirect_uri": redirect, "response_type": "code", "scope": SCOPE,
            "access_type": "offline", "prompt": "consent", "state": state,
            "code_challenge": challenge, "code_challenge_method": "S256",
        }
    )
    try:
        open_browser(url)
        deadline = time.monotonic() + AUTH_WAIT_SECONDS
        while not result and time.monotonic() < deadline:
            server.handle_request()
    finally:
        server.server_close()
    if "code" not in result:
        raise GmailAuthError(result.get("error") or "no llegó la autorización a tiempo")
    form = urllib.parse.urlencode(
        {
            "client_id": client_id, "client_secret": client_secret, "code": result["code"],
            "code_verifier": verifier, "grant_type": "authorization_code", "redirect_uri": redirect,
        }
    ).encode("ascii")
    try:
        body = json.loads(fetch(urllib.request.Request(TOKEN_URL, data=form, method="POST")).decode("utf-8"))
        refresh = body["refresh_token"]
    except (ValueError, KeyError, TypeError) as exc:
        raise GmailAuthError("Google no entregó la llave de renovación") from exc
    if SCOPE not in str(body.get("scope", SCOPE)).split():
        raise GmailAuthError("Google no concedió el permiso de solo lectura")
    token_path = Path(token_path)
    token_path.write_text(json.dumps({"refresh_token": refresh, "scope": SCOPE, "created_at": int(time.time())}), encoding="utf-8")
