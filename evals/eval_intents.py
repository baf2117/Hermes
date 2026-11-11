"""Mide qué tan bien interpreta el modelo real frases en español.

Uso: python evals/eval_intents.py [url_de_ollama] [modelo]
"""
from __future__ import annotations

import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hermes.config import DEFAULT_CATEGORIES  # noqa: E402
from hermes.llm import LLMError, OllamaClient  # noqa: E402
from hermes.store import Task  # noqa: E402

NOW = datetime(2026, 11, 10, 18, 30).astimezone()  # martes
PENDING = [
    Task(4, "Pagar la luz", "finanzas", "media", None, "pending", None),
    Task(7, "Llamar al contador", "negocios", "media", None, "pending", None),
    Task(9, "Limpiar terrario", "reptiles", "baja", None, "pending", None),
]
LAST = PENDING[1]


def day(offset: int) -> str:
    return (NOW.date() + timedelta(days=offset)).isoformat()


# (frase, campos esperados)
CASES = [
    ("recuérdame pagar el internet mañana a las 10 de la mañana", dict(intent="create_task", date=day(1), time="10:00", category="finanzas")),
    ("tengo que llamar al cliente el viernes a las 3 de la tarde", dict(intent="create_task", date=day(3), time="15:00")),
    ("el lunes a las 8 reunión con el equipo de trabajo", dict(intent="create_task", date=day(6), time="08:00", category="trabajo")),
    ("en 45 minutos apagar el horno", dict(intent="create_task", relative_minutes=45, category="casa")),
    ("en dos horas tomar la medicina", dict(intent="create_task", relative_minutes=120)),
    ("comprar grillos para los geckos", dict(intent="create_task", date=None, time=None, category="reptiles")),
    ("urgente: entregar la declaración de impuestos pasado mañana a las 5 de la tarde", dict(intent="create_task", date=day(2), time="17:00", urgency="alta")),
    ("recuérdame cuando puedas revisar lo del jardín, no corre prisa", dict(intent="create_task", urgency="baja", category="casa")),
    ("a las 9 de la noche sacar la basura", dict(intent="create_task", time="21:00", category="casa")),
    ("mañana cita con el dentista a las 4 pm", dict(intent="create_task", date=day(1), time="16:00", category="salud")),
    ("mejor ponlo en casa", dict(intent="edit_task", category="casa", date=None, time=None)),
    ("cámbialo para el jueves a las 11", dict(intent="edit_task", date=day(2), time="11:00")),
    ("no es urgente, bájale la prioridad", dict(intent="edit_task", urgency="baja")),
    ("ya pagué la luz", dict(intent="complete_task", task_id=4)),
    ("listo lo del contador", dict(intent="complete_task", task_id=7)),
    ("borra lo de limpiar el terrario", dict(intent="cancel_task", task_id=9)),
    ("qué tareas tengo", dict(intent="list_tasks")),
    ("cuáles son mis pendientes", dict(intent="list_tasks")),
    ("hola hermes, cómo estás", dict(intent="chat")),
    ("cuál es la capital de Francia", dict(intent="chat")),
]


def main() -> int:
    url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:11434"
    model = sys.argv[2] if len(sys.argv) > 2 else "hermes"
    client = OllamaClient(url, model, timeout=180)
    passed = 0
    durations = []
    for phrase, expected in CASES:
        start = time.perf_counter()
        try:
            got = client.interpret(phrase, NOW, PENDING, LAST, DEFAULT_CATEGORIES)
        except LLMError as exc:
            print(f"ERROR  {phrase}: {exc}")
            continue
        durations.append(time.perf_counter() - start)
        wrong = {k: (v, got.get(k)) for k, v in expected.items() if got.get(k) != v}
        if wrong:
            print(f"FALLA  {phrase}\n       esperado/obtenido: {wrong}")
        else:
            passed += 1
            print(f"ok     {phrase}")
    if durations:
        ordered = sorted(durations)
        print(f"\n{passed}/{len(CASES)} correctas. Mediana {ordered[len(ordered) // 2]:.1f} s, máximo {ordered[-1]:.1f} s")
    return 0 if passed == len(CASES) else 1


if __name__ == "__main__":
    raise SystemExit(main())
