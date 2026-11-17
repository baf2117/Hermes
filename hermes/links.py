"""Enlaces para leer después: mandas un enlace, Hermes lo abre, lo resume y lo guarda en «Para leer».

La página es contenido no confiable. Solo se abren direcciones públicas de internet (nunca esta computadora
ni la red de la casa, tampoco a través de una redirección), con tope de tamaño y de tiempo. El resumen lo
hace el modelo local, tratando el texto como dato; lo que devuelve se limpia y solo se muestra.
"""
from __future__ import annotations

import html
import ipaddress
import logging
import re
import socket
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any, Callable

from .extras import plain
from .mailwatch import clean

log = logging.getLogger(__name__)

TIMEOUT = 15
MAX_BYTES = 1_500_000
MAX_TEXT = 6000
MAX_URL = 2000
URL = re.compile(
    r"^(?:(?:guarda(?:me)?|lee(?:me)?|leer|guardar|para\s+leer)(?:\s+(?:esto|este\s+enlace|para\s+despues|para\s+luego))?\s*:?\s*)?"
    r"(?P<url>https?://\S+)$",
    re.IGNORECASE,
)
READING = re.compile(r"^(?:que\s+tengo\s+(?:para|por)\s+leer|(?:mis\s+)?(?:lecturas|enlaces)(?:\s+(?:pendientes|guardados|sin\s+leer))?|para\s+leer)$")
PAGE_TYPES = ("text/html", "text/plain", "application/xhtml+xml")


class UnsafeURL(ValueError):
    """Dirección que no se abre: no es pública o no es http(s)."""


def check_url(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password or len(url) > MAX_URL:
        raise UnsafeURL("solo direcciones http(s) públicas")
    if parts.port not in (None, 80, 443):
        raise UnsafeURL("puerto no permitido")
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(parts.hostname, parts.port or 443, proto=socket.IPPROTO_TCP)}
    except OSError as exc:
        raise UnsafeURL("no existe esa dirección") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address.split("%")[0])
        if not ip.is_global or ip.is_multicast:
            raise UnsafeURL("dirección privada o local")
    return url


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    """Cada redirección se revisa igual que la primera dirección."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_page(url: str) -> tuple[str, str]:
    """(dirección final, html) de una página pública."""
    check_url(url)
    opener = urllib.request.build_opener(_SafeRedirect)
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Hermes)", "Accept": "text/html,text/plain"})
    with opener.open(request, timeout=TIMEOUT) as response:
        kind = response.headers.get_content_type()
        if kind not in PAGE_TYPES:
            raise UnsafeURL(f"no es una página ({kind})")
        data = response.read(MAX_BYTES + 1)[:MAX_BYTES]
        charset = response.headers.get_content_charset() or "utf-8"
        return response.geturl(), data.decode(charset, "replace")


def page_text(raw: str) -> tuple[str, str]:
    """(título, texto visible) de un html."""
    title = ""
    if match := re.search(r'(?is)<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)', raw):
        title = match.group(1)
    elif match := re.search(r"(?is)<title[^>]*>(.*?)</title>", raw):
        title = match.group(1)
    text = re.sub(r"(?is)<(head|script|style|noscript|svg|nav|footer|header|form|title)\b.*?</\1>", " ", raw)
    text = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</h\d>|</li>", "\n", text)
    text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r" *\n[\s]*", "\n", text).strip()
    return " ".join(html.unescape(title).split())[:200], text[:MAX_TEXT]


def _whole_sentences(text: str, limit: int) -> str:
    """Si el resumen llegó al tope, se corta en la última frase completa en vez de a media palabra."""
    if len(text) < limit:
        return text
    end = text.rfind(". ")
    return text[: end + 1] if end > limit // 3 else text.rstrip() + "…"


def _site(url: str) -> str:
    host = urllib.parse.urlsplit(url).hostname or ""
    return host.removeprefix("www.")


def _ago(ts: int, now: datetime) -> str:
    days = (now.date() - datetime.fromtimestamp(ts, now.tzinfo).date()).days
    return "hoy" if days <= 0 else "ayer" if days == 1 else f"hace {days} días"


class Links:
    def __init__(
        self,
        store: Any,
        summarize: Callable[[str, str], dict[str, Any]] | None,
        config: Any,
        now: Callable[[], datetime],
        reply: Callable[..., Any],
        fetch: Callable[[str], tuple[str, str]] = fetch_page,
    ):
        self.store, self.summarize, self.config, self._now, self.R, self.fetch = store, summarize, config, now, reply, fetch
        self.send: Callable[[str, list], None] | None = None  # Con Telegram, el resumen llega aparte.

    @property
    def enabled(self) -> bool:
        return getattr(self.config, "links_enabled", True)

    # --- Guardar ---

    def handle(self, text: str, reference: datetime) -> Any:
        if not self.enabled:
            return None
        if READING.match(plain(text).strip().strip(" .!?¡¿…")):
            return self.report()
        original = text.strip()
        match = URL.match(plain(original))  # Sin tildes («guárdame»); plain() conserva el largo.
        if not match:
            return None
        url = original[match.start("url"):match.end("url")].rstrip(").,;»\"'")  # La dirección tal cual, con sus mayúsculas.
        if self.send is None:
            return self.save(url)
        # Abrir y resumir tarda unos segundos: se hace aparte y el resultado llega en otro mensaje.
        threading.Thread(target=self._save_and_send, args=(url,), daemon=True, name="enlace").start()
        return self.R("📚 Lo leo y te mando el resumen en un momento…")

    def _save_and_send(self, url: str) -> None:
        try:
            reply = self.save(url)
            self.send(reply.text, reply.buttons)
        except Exception as exc:
            log.warning("Enlace: no pude guardarlo: %s", exc)

    def save(self, url: str) -> Any:
        url = urllib.parse.urldefrag(url.strip())[0]
        if existing := self.store.link_by_url(url):
            return self.R(f"Ese enlace ya lo tenías guardado: «{existing['title']}».", self._buttons(existing["id"]))
        try:
            final, raw = self.fetch(url)
            title, text = page_text(raw)
        except UnsafeURL as exc:
            log.info("Enlace rechazado: %s", exc)
            return self.R("No abro esa dirección: solo páginas públicas de internet.")
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            log.info("Enlace: no pude abrir la página: %s", exc)
            final, title, text = url, "", ""
        summary = ""
        if text and self.summarize is not None:
            try:
                data = self.summarize(title, text)
                title = clean(data.get("title"), 120) or title
                summary = _whole_sentences(clean(data.get("summary"), 400), 400)
            except Exception as exc:  # Sin resumen, se guarda igual.
                log.warning("Enlace: el modelo no pudo resumir: %s", exc)
        title = clean(title, 120) or _site(final) or url[:80]
        link_id = self.store.add_link(url, title, summary, _site(final), int(self._now().timestamp()))
        lines = [f"📚 Guardado para leer: «{title}» ({_site(final)})"]
        if summary:
            lines.append(summary)
        elif not text:
            lines.append("No pude abrir la página para resumirla, pero quedó guardada.")
        return self.R("\n".join(lines), self._buttons(link_id))

    @staticmethod
    def _buttons(link_id: int) -> list[list[tuple[str, str]]]:
        return [[("✓ Ya lo leí", f"linkread:{link_id}"), ("🗑 Quitar", f"linkdel:{link_id}")]]

    # --- Botones y frases ---

    def mark_read(self, link_id: int) -> Any:
        link = self.store.get_link(link_id)
        if link is None:
            return self.R("Ese enlace ya no está.")
        self.store.set_link_read(link_id, int(self._now().timestamp()))
        return self.R(f"✓ Marcado como leído: «{link['title']}».")

    def remove(self, link_id: int) -> Any:
        link = self.store.get_link(link_id)
        if link is None or not self.store.delete_link(link_id):
            return self.R("Ese enlace ya no está.")
        return self.R(f"Quité «{link['title']}».")

    def report(self) -> Any:
        if not self.enabled:
            return self.R("Enlaces para leer está apagado. Lo enciendes en Ajustes → Funciones.")
        unread = [l for l in self.store.links() if not l["read_at"]]
        if not unread:
            return self.R("No tienes enlaces pendientes. Mándame uno y lo guardo con su resumen.")
        now = self._now()
        lines = [f"📚 Para leer ({len(unread)}):"] + [f"• {l['title']} ({l['site']}, {_ago(l['saved_at'], now)})" for l in unread[:10]]
        return self.R("\n".join(lines))

    def sunday_lines(self, today: Any) -> list[str]:
        """En el resumen de los domingos: cuántos enlaces quedan sin leer."""
        if not self.enabled or today.weekday() != 6:
            return []
        unread = [l for l in self.store.links() if not l["read_at"]]
        if not unread:
            return []
        oldest = min(unread, key=lambda l: l["saved_at"])
        now = self._now()
        return [f"📚 Tienes {len(unread)} {'enlace' if len(unread) == 1 else 'enlaces'} sin leer; el más viejo es "
                f"«{oldest['title']}», de {_ago(oldest['saved_at'], now)}. Míralos con /leer."]

    # --- Página ---

    def snapshot(self) -> dict[str, Any]:
        return {"links": [{k: l[k] for k in ("id", "url", "title", "summary", "site", "saved_at", "read_at")} for l in self.store.links()],
                "enabled": self.enabled}

    def apply(self, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("Solicitud inválida.")
        if not self.enabled:
            raise ValueError("Enlaces para leer está apagado. Lo enciendes en Ajustes → Funciones.")
        action = payload.get("action")
        if action == "add":
            url = payload.get("url")
            if not isinstance(url, str) or not re.fullmatch(r"https?://\S+", url.strip()) or len(url) > MAX_URL:
                raise ValueError("Pega una dirección que empiece con http:// o https://.")
            return {"ok": True, "message": self.save(url.strip()).text.split("\n")[0]}
        link_id = payload.get("id")
        link = self.store.get_link(link_id) if isinstance(link_id, int) and not isinstance(link_id, bool) else None
        if link is None:
            raise ValueError("Ese enlace ya no está. Recarga la página.")
        if action == "read":
            self.store.set_link_read(link_id, int(self._now().timestamp()))
            return {"ok": True, "message": "Marcado como leído."}
        if action == "unread":
            self.store.set_link_read(link_id, None)
            return {"ok": True, "message": "Vuelve a «para leer»."}
        if action == "delete":
            self.store.delete_link(link_id)
            return {"ok": True, "message": "Enlace quitado."}
        raise ValueError("Acción desconocida.")
