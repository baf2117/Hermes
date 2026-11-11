"""Cliente de Ollama. El modelo solo interpreta: devuelve datos que el código valida."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from typing import Any, Sequence

from .store import Task

INTENTS = ("create_task", "edit_task", "complete_task", "cancel_task", "list_tasks", "remember_fact", "chat")
DAY_NAMES = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
MAX_OUTPUT_TOKENS = 400  # Evita que una respuesta desbocada bloquee a Hermes.

_NULLABLE_STRING = {"type": ["string", "null"]}
_NULLABLE_INT = {"type": ["integer", "null"]}
INTENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "intent": {"type": "string", "enum": list(INTENTS)},
        "title": _NULLABLE_STRING,
        "date": _NULLABLE_STRING,
        "time": _NULLABLE_STRING,
        "relative_minutes": _NULLABLE_INT,
        "category": _NULLABLE_STRING,
        "urgency": {"type": ["string", "null"], "enum": ["baja", "media", "alta", None]},
        "task_id": _NULLABLE_INT,
    },
    "required": [
        "intent", "title", "date", "time", "relative_minutes", "category", "urgency", "task_id",
    ],
}

CHAT_SYSTEM = (
    "Eres Hermes, el asistente personal local de tu usuario. Responde siempre en español, "
    "breve y amable. En esta conversación no creas, cambias ni borras tareas: nunca digas "
    "que guardaste, programaste o completaste algo. Si te doy datos recordados, úsalos para "
    "responder. Si la respuesta no está ahí y es sobre la vida del usuario, di que no lo sabes; "
    "nunca inventes datos personales."
)
MAX_CONTEXT_CHARS = 1500  # El modelo trabaja con un contexto de 4096 tokens.


class LLMError(Exception):
    pass


def _calendar(now: datetime, days: int = 14) -> str:
    lines = []
    for offset in range(days):
        day = now.date() + timedelta(days=offset)
        suffix = " (hoy)" if offset == 0 else " (mañana)" if offset == 1 else ""
        lines.append(f"- {DAY_NAMES[day.weekday()]} {day.isoformat()}{suffix}")
    return "\n".join(lines)


def build_intent_prompt(
    now: datetime,
    pending: Sequence[Task],
    last_task: Task | None,
    categories: Sequence[str],
    facts: Sequence[str] = (),
) -> str:
    tomorrow = (now.date() + timedelta(days=1)).isoformat()
    task_lines = "\n".join(f"- id {t.id}: {t.title}" for t in pending[:20]) or "(ninguna)"
    last_line = f"id {last_task.id}: {last_task.title}" if last_task else "(ninguna)"
    fact_lines = "\n".join(f"- {fact}" for fact in facts) or "(ninguno)"
    return f"""Convierte el mensaje del usuario en JSON para un gestor de tareas. No respondas al usuario.

Ahora: {DAY_NAMES[now.weekday()]} {now:%Y-%m-%d %H:%M}.
Calendario, úsalo para resolver días de la semana:
{_calendar(now)}

Categorías válidas: {", ".join(categories)}.
Urgencia: alta (grave o con consecuencias si se olvida), media (normal), baja (cuando se pueda).

Tareas pendientes:
{task_lines}
Última tarea tocada: {last_line}

Datos conocidos del usuario, solo como referencia:
{fact_lines}

Intenciones:
- create_task: quiere que le recuerden o anotar algo. Da title corto sin la fecha, category y urgency.
- edit_task: corrige o pospone una tarea. Llena SOLO lo que cambia. task_id null si se refiere a la última.
- complete_task: dice que ya hizo una tarea. Da task_id de la lista.
- cancel_task: quiere borrar o cancelar una tarea. Da task_id de la lista.
- list_tasks: pregunta qué tareas tiene.
- remember_fact: te cuenta un dato para que lo sepas (nombres, gustos, datos personales), sin pedir un aviso. Pon el dato completo en title.
- chat: cualquier otra cosa, incluidas las preguntas sobre datos que te contó.

Fechas: date en AAAA-MM-DD y time en HH:MM de 24 horas; null si el usuario no las dijo. Nunca inventes.
Para "en 20 minutos" o "en 2 horas" usa relative_minutes y deja date y time en null.

Ejemplos:
"recuérdame pagar la luz mañana a las 3 de la tarde" -> {{"intent":"create_task","title":"Pagar la luz","date":"{tomorrow}","time":"15:00","relative_minutes":null,"category":"finanzas","urgency":"media","task_id":null}}
"en 20 minutos sacar la ropa" -> {{"intent":"create_task","title":"Sacar la ropa","date":null,"time":null,"relative_minutes":20,"category":"casa","urgency":"media","task_id":null}}
"renovar la licencia de conducir" -> {{"intent":"create_task","title":"Renovar la licencia de conducir","date":null,"time":null,"relative_minutes":null,"category":"personal","urgency":"media","task_id":null}}
"mejor ponlo en trabajo y que sea urgente" -> {{"intent":"edit_task","title":null,"date":null,"time":null,"relative_minutes":null,"category":"trabajo","urgency":"alta","task_id":null}}
"qué tengo pendiente" -> {{"intent":"list_tasks","title":null,"date":null,"time":null,"relative_minutes":null,"category":null,"urgency":null,"task_id":null}}
"mi veterinaria se llama Ana" -> {{"intent":"remember_fact","title":"Mi veterinaria se llama Ana","date":null,"time":null,"relative_minutes":null,"category":null,"urgency":null,"task_id":null}}
"cuándo es el cumpleaños de mi mamá" -> {{"intent":"chat","title":null,"date":null,"time":null,"relative_minutes":null,"category":null,"urgency":null,"task_id":null}}
"cómo estás" -> {{"intent":"chat","title":null,"date":null,"time":null,"relative_minutes":null,"category":null,"urgency":null,"task_id":null}}"""


class OllamaClient:
    def __init__(self, base_url: str, model: str, timeout: float = 120.0):
        self.base_url = base_url
        self.model = model
        self.timeout = timeout

    def _chat(self, messages: list[dict[str, str]], format_schema: dict | None, temperature: float) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "think": False,
            "keep_alive": "30m",
            "options": {"temperature": temperature, "num_predict": MAX_OUTPUT_TOKENS},
        }
        if format_schema is not None:
            payload["format"] = format_schema
        request = urllib.request.Request(
            f"{self.base_url}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
            return str(body["message"]["content"])
        except (urllib.error.URLError, TimeoutError, OSError, KeyError, ValueError) as exc:
            raise LLMError(str(exc)) from exc

    def interpret(
        self,
        text: str,
        now: datetime,
        pending: Sequence[Task],
        last_task: Task | None,
        categories: Sequence[str],
        facts: Sequence[str] = (),
    ) -> dict[str, Any]:
        content = self._chat(
            [
                {"role": "system", "content": build_intent_prompt(now, pending, last_task, categories, facts)},
                {"role": "user", "content": text},
            ],
            INTENT_SCHEMA,
            0.0,
        )
        try:
            data = json.loads(content)
        except ValueError as exc:
            raise LLMError("el modelo no devolvió JSON válido") from exc
        if not isinstance(data, dict) or data.get("intent") not in INTENTS:
            raise LLMError("el modelo devolvió una intención inválida")
        return data

    def reply(self, text: str, history: Sequence[tuple[str, str]], memory: str = "") -> str:
        system = CHAT_SYSTEM
        if memory:
            system += f"\n\nDatos recordados:\n{memory[:MAX_CONTEXT_CHARS]}"
        messages = [{"role": "system", "content": system}]
        for role, content in history:
            messages.append({"role": "user" if role == "user" else "assistant", "content": content})
        messages.append({"role": "user", "content": text})
        return self._chat(messages, None, 0.5).strip()
