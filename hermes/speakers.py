"""Voces alternativas para Hermes. Piper sigue siendo la base y el respaldo: siempre funciona sin internet.

HERMES_VOICE elige la voz:
  piper                         la voz local de siempre
  kokoro o kokoro:em_alex       voz local más natural (más lenta en CPU)
  microsoft o microsoft:es-MX-JorgeNeural
                                voz neural en línea: la más natural, pero el texto de cada respuesta
                                se envía a Microsoft y necesita internet
"""
from __future__ import annotations

import io
import logging
import queue
import re
import threading
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger(__name__)

DEFAULT_VOICES = {"piper": "", "kokoro": "ef_dora", "microsoft": "es-MX-DaliaNeural"}
VOICE_KEY = "voice"  # Elección guardada con /voz; tiene prioridad sobre HERMES_VOICE.
VOICE_HELP = (
    "Voces disponibles:\n"
    "/voz piper: la voz local de siempre\n"
    "/voz kokoro: local y más natural (mujer). Otras: /voz kokoro:em_alex, /voz kokoro:em_santa\n"
    "/voz microsoft: la más natural, en línea (Dalia). Otras: /voz microsoft:es-MX-JorgeNeural\n"
    "Con Microsoft, el texto de cada respuesta hablada se envía a Microsoft; sin internet uso la voz local."
)
MICROSOFT_TIMEOUT = 12.0
_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+")
_VOICE_NAME = re.compile(r"[A-Za-z0-9_-]{1,60}")


def parse_voice(setting: str) -> tuple[str, str]:
    """"microsoft:es-MX-JorgeNeural" -> ("microsoft", "es-MX-JorgeNeural"). Lo desconocido vuelve a Piper."""
    engine, _, name = setting.strip().partition(":")
    engine = engine.strip().lower()
    if engine not in DEFAULT_VOICES:
        if engine:
            log.warning("Voz desconocida en HERMES_VOICE (%s); uso Piper", engine)
        return "piper", ""
    name = name.strip()
    if name and not _VOICE_NAME.fullmatch(name):
        log.warning("Nombre de voz inválido en HERMES_VOICE; uso la voz por defecto de %s", engine)
        name = ""
    return engine, name or DEFAULT_VOICES[engine]


def split_sentences(text: str) -> list[str]:
    return [part.strip() for part in _SENTENCE_END.split(text) if part.strip()]


def play_audio(samples: Any, rate: int) -> None:
    import sounddevice as sd

    sd.play(samples, samplerate=rate, blocking=True)


def decode_mp3(data: bytes) -> tuple[Any, int]:
    """MP3 a muestras de 16 bits mono, con PyAV (ya instalado para la transcripción)."""
    import av
    import numpy as np

    rate = 24000
    resampler = av.AudioResampler(format="s16", layout="mono", rate=rate)
    chunks = []
    with av.open(io.BytesIO(data)) as container:
        for frame in container.decode(audio=0):
            chunks.extend(r.to_ndarray().ravel() for r in resampler.resample(frame))
        chunks.extend(r.to_ndarray().ravel() for r in resampler.resample(None))
    if not chunks:
        raise ValueError("audio vacío")
    return np.concatenate(chunks).astype(np.int16), rate


def fetch_microsoft(text: str, voice: str, timeout: float = MICROSOFT_TIMEOUT) -> bytes:
    import asyncio

    import edge_tts

    async def collect() -> bytes:
        audio = bytearray()
        async for chunk in edge_tts.Communicate(text, voice).stream():
            if chunk["type"] == "audio":
                audio.extend(chunk["data"])
        return bytes(audio)

    return asyncio.run(asyncio.wait_for(collect(), timeout))


class MicrosoftSpeaker:
    def __init__(
        self,
        voice: str,
        fetch: Callable[[str, str], bytes] = fetch_microsoft,
        decode: Callable[[bytes], tuple[Any, int]] = decode_mp3,
        play: Callable[[Any, int], None] = play_audio,
    ):
        self.voice, self._fetch, self._decode, self._play = voice, fetch, decode, play

    def speak(self, text: str) -> None:
        samples, rate = self._decode(self._fetch(text, self.voice))
        self._play(samples, rate)


class KokoroSpeaker:
    """Sintetiza frase por frase en segundo plano para empezar a hablar antes de tener todo el audio."""

    def __init__(self, engine: Any, voice: str, play: Callable[[Any, int], None] = play_audio, speed: float = 1.0):
        self._engine, self.voice, self._play, self.speed = engine, voice, play, speed

    @classmethod
    def load(cls, model_path: Path, voices_path: Path, voice: str) -> "KokoroSpeaker":
        from kokoro_onnx import Kokoro

        return cls(Kokoro(str(model_path), str(voices_path)), voice)

    def speak(self, text: str) -> None:
        sentences = split_sentences(text)
        ready: queue.Queue[Any] = queue.Queue()

        def synthesize() -> None:
            try:
                for sentence in sentences:
                    ready.put(self._engine.create(sentence, voice=self.voice, speed=self.speed, lang="es"))
            except Exception as exc:
                ready.put(exc)
            ready.put(None)

        threading.Thread(target=synthesize, daemon=True, name="kokoro").start()
        while (item := ready.get()) is not None:
            if isinstance(item, Exception):
                raise item
            self._play(*item)


class FallbackSpeaker:
    """Usa la voz elegida y, si falla (sin internet, por ejemplo), dice lo mismo con Piper."""

    def __init__(self, primary: Any, backup: Any):
        self.primary, self.backup = primary, backup

    def chime(self) -> None:
        self.backup.chime()

    def speak(self, text: str) -> None:
        try:
            self.primary.speak(text)
        except Exception as exc:
            log.warning("La voz elegida falló (%s); uso la voz local", exc)
            self.backup.speak(text)


def describe_voice(setting: str) -> str:
    engine, name = parse_voice(setting)
    return engine if engine == "piper" else f"{engine}:{name}"


class SwitchableSpeaker:
    """Permite cambiar de voz sin reiniciar: revisa la elección antes de hablar y prepara esa voz."""

    def __init__(self, current_setting: Callable[[], str], piper: Any, kokoro_dir: Path, build: Callable[..., Any] | None = None):
        self._setting_source, self._piper, self._kokoro_dir = current_setting, piper, kokoro_dir
        self._build = build or build_speaker
        self._setting: str | None = None
        self._speaker: Any = piper

    def chime(self) -> None:
        self._piper.chime()

    def speak(self, text: str) -> None:
        setting = describe_voice(self._setting_source())
        if setting != self._setting:
            self._speaker = self._build(setting, self._piper, self._kokoro_dir)
            self._setting = setting
        self._speaker.speak(text)


def build_speaker(setting: str, piper: Any, kokoro_dir: Path) -> Any:
    engine, name = parse_voice(setting)
    try:
        if engine == "microsoft":
            import edge_tts  # noqa: F401  Si falta el paquete, se sabe desde el arranque.

            log.info("Voz: Microsoft %s (en línea), con Piper de respaldo", name)
            return FallbackSpeaker(MicrosoftSpeaker(name), piper)
        if engine == "kokoro":
            speaker = KokoroSpeaker.load(kokoro_dir / "kokoro-v1.0.onnx", kokoro_dir / "voices-v1.0.bin", name)
            log.info("Voz: Kokoro %s (local), con Piper de respaldo", name)
            return FallbackSpeaker(speaker, piper)
    except Exception as exc:
        log.warning("No se pudo preparar la voz %s (%s); uso Piper", engine, exc)
    return piper
