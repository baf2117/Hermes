"""Transcripción local de notas de voz con faster-whisper, en CPU para dejarle la GPU al modelo."""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000


class TranscriptionError(Exception):
    pass


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

    def transcribe(self, audio_path: Path) -> str:
        try:
            with self._lock:
                audio = decode_audio(audio_path)
                if audio.size == 0:
                    return ""
                segments, _ = self._load().transcribe(
                    audio,
                    language="es",
                    vad_filter=True,
                    condition_on_previous_text=False,
                )
                return " ".join(segment.text.strip() for segment in segments).strip()
        except Exception as exc:
            raise TranscriptionError(str(exc)) from exc
