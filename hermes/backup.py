"""Respaldo diario de la base de datos: copia, comprime, cifra, verifica y sube a Azure Blob Storage."""
from __future__ import annotations

import gzip
import hashlib
import logging
import os
import sqlite3
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, time
from pathlib import Path
from typing import Any, Callable

from .store import Store

log = logging.getLogger(__name__)

MAGIC = b"HERMESBK1\n"
SALT_BYTES = 16
NONCE_BYTES = 12
MIN_PASSWORD_LENGTH = 12
RETRY_SECONDS = 3600
LAST_BACKUP_KEY = "last_backup_date"
NEXT_TRY_KEY = "backup_next_try"
LAST_ALERT_KEY = "backup_last_alert_date"


class BackupError(Exception):
    pass


def _derive_key(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=2**15, r=8, p=1, maxmem=128 * 1024 * 1024, dklen=32
    )


def encrypt(data: bytes, password: str) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    salt, nonce = os.urandom(SALT_BYTES), os.urandom(NONCE_BYTES)
    header = MAGIC + salt + nonce
    return header + AESGCM(_derive_key(password, salt)).encrypt(nonce, data, header)


def decrypt(blob: bytes, password: str) -> bytes:
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    header_size = len(MAGIC) + SALT_BYTES + NONCE_BYTES
    if blob[: len(MAGIC)] != MAGIC or len(blob) <= header_size:
        raise BackupError("El archivo no es un respaldo de Hermes.")
    salt = blob[len(MAGIC) : len(MAGIC) + SALT_BYTES]
    nonce = blob[len(MAGIC) + SALT_BYTES : header_size]
    try:
        return AESGCM(_derive_key(password, salt)).decrypt(nonce, blob[header_size:], blob[:header_size])
    except InvalidTag:
        raise BackupError("Contraseña incorrecta o archivo dañado.") from None


def snapshot_database(db_path: Path, work_dir: Path) -> bytes:
    """Devuelve una copia coherente y comprimida, aunque Hermes esté escribiendo."""
    work_dir.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(suffix=".tmp", dir=work_dir)
    os.close(handle)
    copy_path = Path(name)
    try:
        source = sqlite3.connect(db_path)
        target = sqlite3.connect(copy_path)
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()
        return gzip.compress(copy_path.read_bytes())
    finally:
        copy_path.unlink(missing_ok=True)  # Esta copia temporal no está cifrada.


def check_database(data: bytes, work_dir: Path) -> None:
    """Comprueba que unos bytes comprimidos sean una base de datos SQLite íntegra."""
    work_dir.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(suffix=".tmp", dir=work_dir)
    os.close(handle)
    path = Path(name)
    try:
        path.write_bytes(gzip.decompress(data))
        connection = sqlite3.connect(path)
        try:
            result = connection.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            connection.close()
        if result != "ok":
            raise BackupError("La copia no pasó la verificación de integridad.")
    except (OSError, EOFError, sqlite3.DatabaseError) as exc:
        raise BackupError("La copia no es una base de datos válida.") from exc
    finally:
        path.unlink(missing_ok=True)


def blob_url(sas_url: str, blob_name: str) -> str:
    parts = urllib.parse.urlsplit(sas_url)
    if parts.scheme != "https" or not parts.query:
        raise BackupError("La URL de Azure debe ser una Blob SAS URL con https.")
    path = f"{parts.path.rstrip('/')}/{urllib.parse.quote(blob_name)}"
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, path, parts.query, ""))


def upload_to_azure(sas_url: str, blob_name: str, data: bytes) -> None:
    request = urllib.request.Request(
        blob_url(sas_url, blob_name),
        data=data,
        headers={
            "x-ms-blob-type": "BlockBlob",
            "x-ms-version": "2023-11-03",
            "Content-Type": "application/octet-stream",
        },
        method="PUT",
    )
    try:
        with urllib.request.urlopen(request, timeout=120):
            pass
    except urllib.error.HTTPError as exc:
        # Nunca se incluye la URL: lleva el permiso de escritura.
        raise BackupError(f"Azure respondió HTTP {exc.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise BackupError(f"No se pudo conectar con Azure ({type(exc).__name__})") from None


def restore_backup(backup_file: Path, destination: Path, password: str) -> None:
    if destination.exists():
        raise BackupError(f"Ya existe {destination}; elige otro destino para no sobrescribirlo.")
    data = decrypt(backup_file.read_bytes(), password)
    check_database(data, destination.parent)
    destination.write_bytes(gzip.decompress(data))


class BackupService:
    def __init__(
        self,
        store: Store,
        db_path: Path,
        work_dir: Path,
        password: str,
        backup_time: time,
        send: Callable[[str, list], Any],
        upload: Callable[[str, bytes], None],
        now: Callable[[], datetime] | None = None,
    ):
        self.store = store
        self.db_path = db_path
        self.work_dir = work_dir
        self.password = password
        self.backup_time = backup_time
        self.send = send
        self.upload = upload
        self._now = now or (lambda: datetime.now().astimezone())

    def backup(self) -> tuple[str, int]:
        name = f"hermes-{self._now():%Y-%m-%d}.db.gz.enc"
        compressed = snapshot_database(self.db_path, self.work_dir)
        encrypted = encrypt(compressed, self.password)
        check_database(decrypt(encrypted, self.password), self.work_dir)
        self.upload(name, encrypted)
        return name, len(encrypted)

    def tick(self) -> None:
        now = self._now()
        today = now.date().isoformat()
        if now.time() < self.backup_time or self.store.kv_get(LAST_BACKUP_KEY) == today:
            return
        if int(now.timestamp()) < int(self.store.kv_get(NEXT_TRY_KEY) or 0):
            return
        try:
            name, size = self.backup()
        except Exception as exc:
            log.warning("El respaldo falló: %s", exc)
            self.store.kv_set(NEXT_TRY_KEY, str(int(now.timestamp()) + RETRY_SECONDS))
            self._alert_once(today, exc)
            return
        log.info("Respaldo subido: %s (%d bytes)", name, size)
        self.store.kv_set(LAST_BACKUP_KEY, today)
        self.store.kv_set(NEXT_TRY_KEY, "0")

    def _alert_once(self, today: str, exc: Exception) -> None:
        if self.store.kv_get(LAST_ALERT_KEY) == today:
            return
        reason = exc if isinstance(exc, BackupError) else type(exc).__name__
        try:
            self.send(f"⚠️ No pude hacer el respaldo de hoy: {reason}. Lo reintento cada hora.", [])
        except Exception as send_exc:
            log.warning("No se pudo avisar del respaldo fallido: %s", send_exc)
            return
        self.store.kv_set(LAST_ALERT_KEY, today)

    def run_forever(self, stop: threading.Event, interval: float = 60.0) -> None:
        while not stop.is_set():
            try:
                self.tick()
            except Exception:
                log.exception("Error en el ciclo de respaldo")
            stop.wait(interval)
