"""Transcripción local de notas de voz con faster-whisper, en CPU para dejarle la GPU al modelo."""
from __future__ import annotations

import logging
import re
import threading
import unicodedata
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000
# Orienta a Whisper hacia las frases habituales; sin esto confundía "cuándo" con "cuánto".
# Mezcla órdenes y preguntas: con solo preguntas, convertía las órdenes en preguntas.
VOCABULARY_HINT = (
    "Recuérdame pagar la luz mañana. Cambia la tarea a urgente. Márcala como hecha. "
    "Cancela mis pendientes. ¿Cuándo juega mi equipo?"
)


_HALLUCINATION = re.compile(
    r"(suscribete|suscribanse|suscribite)( al canal| a mi canal| a nuestro canal)?( y dale like)?"
    r"|gracias por ver( el video| este video)?"
    r"|(subtitulos|subtitulado)\b.*",
)


class TranscriptionError(Exception):
    pass


def is_hallucination(text: str) -> bool:
    """Whisper aprendió de videos y ante ruido a veces inventa sus despedidas típicas."""
    plain = "".join(c for c in unicodedata.normalize("NFD", text.lower()) if unicodedata.category(c) != "Mn")
    return _HALLUCINATION.fullmatch(plain.strip(" ¡!¿?.,…")) is not None


def decode_audio(path: Path) -> Any:
    """Decodifica a 16 kHz mono; se hace aquí porque el decodificador de faster-whisper 1.2.1 no admite PyAV 19."""
    import av
    import numpy as np

    resampler = av.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
    chunks = []
    with av.open(str(path)) as container:
        for frame in container.decode(audio=0):
            chunks.extend(resampled.to_ndarray().ravel() for resampled in resampler.resample(frame))
        chunks.extend(resampled.to_ndarray().ravel() for resampled in resampler.resample(None))
    if not chunks:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(chunks).astype(np.float32) / 32768.0


class WhisperTranscriber:
    def __init__(self, model_dir: Path, cpu_threads: int = 4):
        self.model_dir = model_dir
        self.cpu_threads = cpu_threads
        self._model: Any = None
        self._lock = threading.Lock()

    def _load(self) -> Any:
        if self._model is None:
            from faster_whisper import WhisperModel  # Importación tardía: pesa y es opcional.

            log.info("Cargando el modelo de voz")
            self._model = WhisperModel(
                str(self.model_dir),
                device="cpu",
                compute_type="int8",
                cpu_threads=self.cpu_threads,
                local_files_only=True,
            )
        return self._model

    def preload(self) -> None:
        with self._lock:
            self._load()

    def _run(self, audio: Any) -> str:
        if audio.size == 0:
            return ""
        with self._lock:
            segments, _ = self._load().transcribe(
                audio,
                language="es",
                vad_filter=True,
                condition_on_previous_text=False,
                initial_prompt=VOCABULARY_HINT,
            )
            text = " ".join(segment.text.strip() for segment in segments).strip()
        if is_hallucination(text):
            log.info("Transcripción descartada por parecer inventada")
            return ""
        return text

    def transcribe(self, audio_path: Path) -> str:
        try:
            return self._run(decode_audio(audio_path))
        except Exception as exc:
            raise TranscriptionError(str(exc)) from exc

    def transcribe_pcm(self, pcm: bytes) -> str:
        """Transcribe audio crudo de 16 bits, mono y 16 kHz, directo del micrófono."""
        import numpy as np

        try:
            return self._run(np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0)
        except Exception as exc:
            raise TranscriptionError(str(exc)) from exc
