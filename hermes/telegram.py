"""Cliente mínimo de la API de bots de Telegram, por long polling (sin abrir puertos)."""
from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger(__name__)

MAX_MESSAGE_LENGTH = 4000
MAX_AUDIO_BYTES = 20_000_000  # Límite de descarga de la API de bots.
MAX_AUDIO_SECONDS = 300
OFFSET_KEY = "telegram_offset"


class TelegramError(Exception):
    pass


class TelegramClient:
    def __init__(self, token: str):
        self._base = f"https://api.telegram.org/bot{token}"
        self._file_base = f"https://api.telegram.org/file/bot{token}"

    def call(self, method: str, payload: dict[str, Any], timeout: float = 30.0) -> Any:
        request = urllib.request.Request(
            f"{self._base}/{method}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise TelegramError(f"{method}: HTTP {exc.code}") from None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            # El mensaje de la excepción nunca incluye la URL, que contiene el token.
            raise TelegramError(f"{method}: {type(exc).__name__}") from None
        if not body.get("ok"):
            raise TelegramError(f"{method}: {body.get('description')}")
        return body["result"]

    def get_updates(self, offset: int | None, wait_seconds: int = 30) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {
            "timeout": wait_seconds,
            "allowed_updates": ["message", "callback_query"],
        }
        if offset is not None:
            payload["offset"] = offset
        return self.call("getUpdates", payload, timeout=wait_seconds + 10)

    def send_message(
        self, chat_id: int, text: str, buttons: list[list[tuple[str, str]]] | None = None
    ) -> None:
        chunks = [text[i : i + MAX_MESSAGE_LENGTH] for i in range(0, len(text), MAX_MESSAGE_LENGTH)] or [""]
        for index, chunk in enumerate(chunks):
            payload: dict[str, Any] = {"chat_id": chat_id, "text": chunk}
            if buttons and index == len(chunks) - 1:
                payload["reply_markup"] = {
                    "inline_keyboard": [
                        [{"text": label, "callback_data": data} for label, data in row] for row in buttons
                    ]
                }
            self.call("sendMessage", payload)

    def send_typing(self, chat_id: int) -> None:
        self.call("sendChatAction", {"chat_id": chat_id, "action": "typing"})

    def download_file(self, file_id: str, destination: Path) -> None:
        info = self.call("getFile", {"file_id": file_id})
        if int(info.get("file_size") or 0) > MAX_AUDIO_BYTES:
            raise TelegramError("getFile: archivo demasiado grande")
        try:
            with urllib.request.urlopen(f"{self._file_base}/{info['file_path']}", timeout=60) as response:
                data = response.read(MAX_AUDIO_BYTES + 1)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise TelegramError(f"descarga: {type(exc).__name__}") from None
        if len(data) > MAX_AUDIO_BYTES:
            raise TelegramError("descarga: archivo demasiado grande")
        destination.write_bytes(data)

    def answer_button(self, callback_id: str) -> None:
        self.call("answerCallbackQuery", {"callback_query_id": callback_id})

    def clear_buttons(self, chat_id: int, message_id: int) -> None:
        self.call(
            "editMessageReplyMarkup",
            {"chat_id": chat_id, "message_id": message_id, "reply_markup": {"inline_keyboard": []}},
        )


class TelegramBot:
    """Recibe mensajes y los entrega al asistente, solo si vienen del usuario autorizado."""

    def __init__(
        self,
        client: Any,
        assistant: Any,
        store: Any,
        allowed_chat_id: int | None,
        transcriber: Any = None,
        tmp_dir: Path | None = None,
    ):
        self.client = client
        self.assistant = assistant
        self.store = store
        self.allowed_chat_id = allowed_chat_id
        self.transcriber = transcriber
        self.tmp_dir = tmp_dir

    def _is_allowed(self, user_id: Any, chat: dict[str, Any]) -> bool:
        return (
            self.allowed_chat_id is not None
            and chat.get("type") == "private"
            and chat.get("id") == self.allowed_chat_id
            and user_id == self.allowed_chat_id
        )

    def handle_update(self, update: dict[str, Any]) -> None:
        if "callback_query" in update:
            self._handle_button(update["callback_query"])
        elif "message" in update:
            self._handle_message(update["message"])

    def _handle_message(self, message: dict[str, Any]) -> None:
        chat = message.get("chat", {})
        user_id = message.get("from", {}).get("id")
        if self.allowed_chat_id is None and chat.get("type") == "private":
            # Emparejamiento inicial: solo revela el propio número de chat de quien escribe.
            self.client.send_message(chat["id"], f"Tu número de chat es: {chat['id']}")
            return
        if not self._is_allowed(user_id, chat):
            log.warning("Mensaje ignorado de un chat no autorizado")
            return
        sent_at = datetime.fromtimestamp(message["date"]).astimezone() if "date" in message else None
        audio = message.get("voice") or message.get("audio")
        if audio:
            self._handle_audio(chat["id"], audio, sent_at)
        elif "text" in message:
            reply = self.assistant.handle_text(message["text"], sent_at)
            self.client.send_message(chat["id"], reply.text, reply.buttons)
        else:
            self.client.send_message(chat["id"], "Solo entiendo texto y notas de voz.")

    def _transcribe(self, audio: dict[str, Any]) -> str:
        self.tmp_dir.mkdir(parents=True, exist_ok=True)
        path = self.tmp_dir / f"{uuid.uuid4().hex}.audio"
        try:
            self.client.download_file(audio["file_id"], path)
            return self.transcriber.transcribe(path)
        finally:
            path.unlink(missing_ok=True)  # El audio no se conserva; solo su transcripción.

    def _handle_audio(self, chat_id: int, audio: dict[str, Any], sent_at: datetime | None) -> None:
        if self.transcriber is None or self.tmp_dir is None:
            self.client.send_message(chat_id, "Las notas de voz no están disponibles en este momento.")
            return
        if int(audio.get("duration") or 0) > MAX_AUDIO_SECONDS:
            self.client.send_message(chat_id, "Ese audio es muy largo. Mándame uno de menos de 5 minutos.")
            return
        self.client.send_typing(chat_id)
        try:
            text = self._transcribe(audio)
        except Exception as exc:
            log.warning("No se pudo transcribir el audio: %s", exc)
            self.client.send_message(chat_id, "No pude procesar ese audio. ¿Me lo escribes o lo intentas de nuevo?")
            return
        if not text:
            self.client.send_message(chat_id, "No logré escuchar nada en ese audio.")
            return
        reply = self.assistant.handle_text(text, sent_at)
        self.client.send_message(chat_id, f"🎙️ Entendí: «{text}»\n\n{reply.text}", reply.buttons)

    def _handle_button(self, query: dict[str, Any]) -> None:
        message = query.get("message", {})
        chat = message.get("chat", {})
        if not self._is_allowed(query.get("from", {}).get("id"), chat):
            log.warning("Botón ignorado de un chat no autorizado")
            return
        self.client.answer_button(query["id"])
        reply = self.assistant.handle_button(query.get("data", ""))
        self.client.clear_buttons(chat["id"], message["message_id"])
        self.client.send_message(chat["id"], reply.text, reply.buttons)

    def poll_once(self) -> None:
        raw_offset = self.store.kv_get(OFFSET_KEY)
        updates = self.client.get_updates(int(raw_offset) if raw_offset else None)
        for update in updates:
            try:
                self.handle_update(update)
            except Exception:
                log.exception("Error al procesar un mensaje de Telegram")
            self.store.kv_set(OFFSET_KEY, str(update["update_id"] + 1))

    def run_forever(self, should_stop: Callable[[], bool]) -> None:
        backoff = 5
        while not should_stop():
            try:
                self.poll_once()
                backoff = 5
            except TelegramError as exc:
                log.warning("Telegram no disponible: %s", exc)
                time.sleep(backoff)
                backoff = min(backoff * 2, 120)
