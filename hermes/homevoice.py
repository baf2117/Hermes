"""Voz en casa: escucha "Hermes" en el micrófono, procesa lo que digas y responde por las bocinas.

Todo ocurre en esta computadora. Hasta oír la palabra de activación, el audio solo pasa por Vosk
y no se guarda ni se transcribe.
"""
from __future__ import annotations

import json
import logging
import math
import queue
import re
import threading
import time
from array import array
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .status import VoiceStatus

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000
FRAME_SAMPLES = 1600  # 0,1 segundos
MAX_SPOKEN_CHARS = 500

_NOT_SPEAKABLE = re.compile(r"[^\w\s.,;:¿?¡!%/()-]", re.UNICODE)
_TASK_NUMBER = re.compile(r"#\d+\s*")


def speakable(text: str) -> str:
    """Quita lo que no debe leerse en voz alta: emojis, números de tarea y la coletilla de corrección."""
    text = text.split("\n\nSi algo está mal", 1)[0].split("\n\nFuente:", 1)[0]
    text = _TASK_NUMBER.sub("", text).replace("·", ",")
    text = _NOT_SPEAKABLE.sub(" ", text)
    text = re.sub(r"\s*\n\s*", ". ", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"([.,:;])(\s*[.,:;])+", r"\1", text)
    if len(text) > MAX_SPOKEN_CHARS:
        text = text[:MAX_SPOKEN_CHARS].rsplit(" ", 1)[0] + ". El resto te lo dejo en Telegram."
    return text


def rms(frame: bytes) -> float:
    samples = array("h", frame[: len(frame) - len(frame) % 2])
    if not samples:
        return 0.0
    return math.sqrt(sum(s * s for s in samples) / len(samples))


@dataclass(frozen=True)
class RecordSettings:
    min_threshold: float = 250.0
    noise_factor: float = 2.5
    start_timeout_frames: int = 50  # 5 s para empezar a hablar
    end_silence_frames: int = 8  # 0,8 s de silencio para terminar
    max_frames: int = 150  # 15 s como máximo
    min_speech_frames: int = 3


def speech_threshold(noise: float, settings: RecordSettings = RecordSettings()) -> float:
    return max(settings.min_threshold, noise * settings.noise_factor)


def strip_wake_word(text: str, word: str) -> str:
    """Quita el nombre si la orden empieza con él: "Hermes, ¿qué hora es?" -> "¿qué hora es?"."""
    return re.sub(rf"^\W*{re.escape(word)}\b[\s,.:;!¡-]*", "", text, count=1, flags=re.IGNORECASE).strip()


def record_utterance(read: Callable[[], bytes], noise: float, settings: RecordSettings = RecordSettings()) -> bytes | None:
    """Graba hasta que termines de hablar. Devuelve None si no dijiste nada."""
    threshold = speech_threshold(noise, settings)
    captured: list[bytes] = []
    speech_frames = silent_frames = waited = 0
    while len(captured) < settings.max_frames:
        frame = read()
        if rms(frame) >= threshold:
            speech_frames += 1
            silent_frames = 0
        elif speech_frames == 0:
            waited += 1
            if waited >= settings.start_timeout_frames:
                return None
            continue
        else:
            silent_frames += 1
        captured.append(frame)
        if silent_frames >= settings.end_silence_frames:
            break
    return b"".join(captured) if speech_frames >= settings.min_speech_frames else None


class WakeWordDetector:
    def __init__(self, model_dir: Path, word: str = "hermes"):
        import vosk

        vosk.SetLogLevel(-1)
        self.word = word
        self._recognizer = vosk.KaldiRecognizer(
            vosk.Model(str(model_dir)), SAMPLE_RATE, json.dumps([word, "[unk]"])
        )

    def feed(self, frame: bytes) -> bool:
        if self._recognizer.AcceptWaveform(frame):
            text = json.loads(self._recognizer.Result()).get("text", "")
        else:
            text = json.loads(self._recognizer.PartialResult()).get("partial", "")
        if self.word in text.split():
            self.reset()
            return True
        return False

    def reset(self) -> None:
        self._recognizer.Reset()


class PiperSpeaker:
    def __init__(self, voice_path: Path):
        from piper import PiperVoice

        self._voice = PiperVoice.load(str(voice_path))

    def speak(self, text: str) -> None:
        import numpy as np
        import sounddevice as sd

        chunks = list(self._voice.synthesize(text))
        if chunks:
            audio = np.frombuffer(b"".join(c.audio_int16_bytes for c in chunks), dtype=np.int16)
            sd.play(audio, samplerate=chunks[0].sample_rate, blocking=True)

    def chime(self) -> None:
        import numpy as np
        import sounddevice as sd

        rate = 22050
        moment = np.arange(int(rate * 0.12)) / rate
        fade = np.minimum(1.0, np.minimum(moment, 0.12 - moment) / 0.01)
        sd.play((np.sin(2 * np.pi * 880 * moment) * fade * 0.25).astype(np.float32), samplerate=rate, blocking=True)


class HomeVoice:
    def __init__(
        self,
        detector: Any,
        transcriber: Any,
        assistant: Any,
        speaker: Any,
        read: Callable[[], bytes],
        flush: Callable[[], None],
        status: VoiceStatus | None = None,
        wake_word: str = "hermes",
    ):
        self.detector = detector
        self.transcriber = transcriber
        self.assistant = assistant
        self.speaker = speaker
        self.read = read
        self.flush = flush
        self.status = status or VoiceStatus()
        self.wake_word = wake_word
        self.noise = 100.0
        self._peak = 0.0
        self.status.set_state("escuchando")

    def _read_measured(self) -> bytes:
        frame = self.read()
        level = rms(frame)
        self._peak = max(self._peak, level)
        self.status.set_level(level, speech_threshold(self.noise))
        return frame

    def step(self) -> None:
        frame = self._read_measured()
        if self.detector.feed(frame):
            self._conversation()
        else:
            self.noise = 0.98 * self.noise + 0.02 * rms(frame)

    def _conversation(self) -> None:
        log.info("Palabra de activación detectada")
        timings: dict[str, float] = {}
        heard = answer = ""
        outcome = "error"
        started = time.perf_counter()

        def stage(name: str, state: str, action: Callable[[], Any]) -> Any:
            self.status.set_state(state)
            begin = time.perf_counter()
            try:
                return action()
            finally:
                timings[name] = time.perf_counter() - begin

        try:
            self.status.set_state("pitido")
            self.speaker.chime()
            self.flush()
            self._peak = 0.0
            pcm = stage("grabar", "grabando", lambda: record_utterance(self._read_measured, self.noise))
            if pcm is None:
                outcome = "sin_voz"  # Falsa activación o silencio: se vuelve a escuchar sin decir nada.
                return
            heard = stage("transcribir", "transcribiendo", lambda: self.transcriber.transcribe_pcm(pcm))
            if not heard:
                outcome = "sin_texto"
                return
            order = strip_wake_word(heard, self.wake_word)
            if not order:
                outcome = "solo_nombre"
                return
            reply = stage("pensar", "pensando", lambda: self.assistant.handle_text(order))
            answer = speakable(reply.text)
            stage("hablar", "hablando", lambda: self.speaker.speak(answer))
            outcome = "ok"
        except Exception:
            log.exception("Error durante la conversación por voz")
            try:
                self.speaker.speak("Perdón, tuve un problema. ¿Me lo repites?")
            except Exception:
                log.exception("Tampoco se pudo reproducir el aviso de error")
        finally:
            timings["total"] = time.perf_counter() - started
            self.flush()  # Descarta lo que el micrófono oyó mientras Hermes hablaba.
            self.detector.reset()
            self.status.add_event(outcome, heard, answer, timings, self._peak, speech_threshold(self.noise))
            self.status.set_state("escuchando")


def wait_while_paused(status: VoiceStatus, stop: threading.Event) -> None:
    """Con la pausa, el micrófono queda cerrado: Windows ni siquiera muestra que se esté usando."""
    if status.paused and not stop.is_set():
        log.info("Voz en casa en pausa: micrófono cerrado")
        status.set_state("pausada")
        status.set_level(0, 0)
        while status.paused and not stop.is_set():
            stop.wait(0.5)
        if not stop.is_set():
            log.info("Voz en casa reactivada")
            status.set_state("escuchando")


def run_microphone_loop(build: Callable[[Callable[[], bytes], Callable[[], None]], HomeVoice], stop: threading.Event) -> None:
    """Mantiene abierto el micrófono, lo cierra durante la pausa y se recupera si el dispositivo falla."""
    import sounddevice as sd

    while not stop.is_set():
        frames: queue.Queue[bytes] = queue.Queue(maxsize=600)

        def on_audio(data: Any, _frames: int, _time: Any, status: Any) -> None:
            if status:
                log.debug("Estado del micrófono: %s", status)
            try:
                frames.put_nowait(bytes(data))
            except queue.Full:
                pass  # Hermes está ocupado; ese audio se descarta.

        def read() -> bytes:
            while True:
                try:
                    return frames.get(timeout=1)
                except queue.Empty:
                    if stop.is_set():
                        raise InterruptedError from None

        def flush() -> None:
            while True:
                try:
                    frames.get_nowait()
                except queue.Empty:
                    return

        try:
            voice = build(read, flush)
            while not stop.is_set():
                wait_while_paused(voice.status, stop)
                if stop.is_set():
                    return
                flush()
                voice.detector.reset()
                with sd.RawInputStream(
                    samplerate=SAMPLE_RATE, blocksize=FRAME_SAMPLES, channels=1, dtype="int16", callback=on_audio
                ):
                    log.info("Voz en casa activa: escuchando la palabra de activación")
                    voice.status.set_state("escuchando")
                    while not stop.is_set() and not voice.status.paused:
                        voice.step()
        except InterruptedError:
            return
        except Exception:
            log.exception("La voz en casa falló; reintento en 30 s")
            stop.wait(30)
