"""Órdenes habladas desde la página: el navegador graba, Hermes transcribe aquí y responde con texto y voz.

El audio recibido no se conserva: se transcribe y se borra. La respuesta hablada viaja como un audio corto
que el navegador reproduce; si no hay voz instalada, la respuesta llega solo escrita.
"""
from __future__ import annotations

import base64
import io
import logging
import threading
import time
import uuid
import wave
from pathlib import Path
from typing import Any, Callable

from .homevoice import speakable
from .speakers import fetch_microsoft, parse_voice
from .status import VoiceStatus
from .voice import AudioTooLong

log = logging.getLogger(__name__)

MAX_SECONDS = 90  # La página corta la grabación antes; esto es el tope que se hace cumplir aquí.
BUSY = "Estoy atendiendo otra orden. Intenta de nuevo en un momento."
NOTHING_HEARD = "No logré escuchar nada. Intenta de nuevo, más cerca del micrófono."
TOO_LONG = "Ese audio es muy largo. Dilo en menos de un minuto."
UNREADABLE = "No pude procesar ese audio. Intenta de nuevo."
UNAVAILABLE = "La voz no está disponible en este momento."


def wav_bytes(pcm: bytes, rate: int) -> bytes:
    """Muestras de 16 bits mono a un archivo WAV en memoria."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(pcm)
    return buffer.getvalue()


class VoiceRenderer:
    """Convierte la respuesta en audio para el navegador, con la voz elegida en /voz cuando se puede.

    Microsoft entrega un MP3 listo; Piper se sintetiza aquí. Kokoro no se carga una segunda vez para
    la página (pesa demasiado): en ese caso se responde con Piper.
    """

    def __init__(
        self,
        current_setting: Callable[[], str],
        piper: Callable[[], Any],
        fetch: Callable[[str, str], bytes] = fetch_microsoft,
    ):
        self._setting, self._piper, self._fetch = current_setting, piper, fetch

    def __call__(self, text: str) -> tuple[bytes, str] | None:
        if not text:
            return None
        engine, name = parse_voice(self._setting())
        if engine == "microsoft":
            try:
                return self._fetch(text, name), "audio/mpeg"
            except Exception as exc:
                log.warning("La voz elegida falló para la página (%s); uso la voz local", exc)
        piper = self._piper()
        if piper is None:
            return None
        pcm, rate = piper.synthesize(text)
        return (wav_bytes(pcm, rate), "audio/wav") if pcm else None


class PageVoice:
    def __init__(
        self,
        transcriber: Any,
        assistant: Any,
        tmp_dir: Path,
        render: Callable[[str], tuple[bytes, str] | None] | None = None,
        status: VoiceStatus | None = None,
    ):
        self.transcriber = transcriber
        self.assistant = assistant
        self.tmp_dir = tmp_dir
        self.render = render
        self.status = status
        self._busy = threading.Lock()

    def handle(self, audio: bytes) -> dict[str, Any]:
        """Atiende una orden grabada. Devuelve lo que se entendió, la respuesta y, si hay voz, su audio."""
        if self.transcriber is None:
            raise ValueError(UNAVAILABLE)
        if not self._busy.acquire(blocking=False):
            raise ValueError(BUSY)
        timings: dict[str, float] = {}
        heard = answer = ""
        outcome = "error"
        started = time.perf_counter()
        try:
            heard = self._timed(timings, "transcribir", lambda: self._transcribe(audio))
            if not heard:
                outcome = "sin_texto"
                raise ValueError(NOTHING_HEARD)
            reply = self._timed(timings, "pensar", lambda: self.assistant.handle_text(heard, spoken=True))
            answer = speakable(getattr(reply, "spoken", None) or reply.text)
            result: dict[str, Any] = {"heard": heard, "reply": reply.text}
            rendered = self._timed(timings, "hablar", lambda: self._render(answer))
            if rendered:
                result["audio"] = base64.b64encode(rendered[0]).decode("ascii")
                result["mime"] = rendered[1]
            outcome = "ok"
            return result
        finally:
            timings["total"] = time.perf_counter() - started
            self._busy.release()
            if self.status is not None and outcome != "error":
                self.status.add_event(outcome, heard, answer, timings, 0, 0)

    @staticmethod
    def _timed(timings: dict[str, float], name: str, action: Callable[[], Any]) -> Any:
        begin = time.perf_counter()
        try:
            return action()
        finally:
            timings[name] = time.perf_counter() - begin

    def _transcribe(self, audio: bytes) -> str:
        self.tmp_dir.mkdir(parents=True, exist_ok=True)
        path = self.tmp_dir / f"{uuid.uuid4().hex}.audio"
        try:
            path.write_bytes(audio)
            return self.transcriber.transcribe(path, max_seconds=MAX_SECONDS)
        except AudioTooLong:
            raise ValueError(TOO_LONG) from None
        except Exception as exc:
            log.warning("No se pudo transcribir el audio de la página: %s", exc)
            raise ValueError(UNREADABLE) from None
        finally:
            path.unlink(missing_ok=True)  # El audio no se conserva; solo su transcripción.

    def _render(self, text: str) -> tuple[bytes, str] | None:
        if self.render is None:
            return None
        try:
            return self.render(text)
        except Exception:
            log.exception("No se pudo generar la voz para la página")
            return None  # La respuesta escrita llega igual.
