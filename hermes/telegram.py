"""Cliente mínimo de la API de bots de Telegram, por long polling (sin abrir puertos)."""
from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from typing import Any, Callable

log = logging.getLogger(__name__)

MAX_MESSAGE_LENGTH = 4000
OFFSET_KEY = "telegram_offset"


class TelegramError(Exception):
    pass


class TelegramClient:
    def __init__(self, token: str):
        self._base = f"https://api.telegram.org/bot{token}"

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

    def answer_button(self, callback_id: str) -> None:
        self.call("answerCallbackQuery", {"callback_query_id": callback_id})

    def clear_buttons(self, chat_id: int, message_id: int) -> None:
        self.call(
            "editMessageReplyMarkup",
            {"chat_id": chat_id, "message_id": message_id, "reply_markup": {"inline_keyboard": []}},
        )


class TelegramBot:
    """Recibe mensajes y los entrega al asistente, solo si vienen del usuario autorizado."""

    def __init__(self, client: Any, assistant: Any, store: Any, allowed_chat_id: int | None):
        self.client = client
        self.assistant = assistant
        self.store = store
        self.allowed_chat_id = allowed_chat_id

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
        if "text" not in message:
            self.client.send_message(chat["id"], "Por ahora solo entiendo texto. Las notas de voz llegan pronto.")
            return
        reply = self.assistant.handle_text(message["text"])
        self.client.send_message(chat["id"], reply.text, reply.buttons)

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
