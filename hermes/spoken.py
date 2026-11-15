"""Cómo dice Hermes las cosas en voz alta: frases naturales en vez de la ficha que se manda por Telegram."""
from __future__ import annotations

import random
from datetime import datetime
from typing import Sequence

from .store import Task

DAYS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
MONTHS = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
    "noviembre", "diciembre",
)
CREATED = ("Listo", "Anotado", "Claro", "Va", "Hecho")
DONE = ("Perfecto", "Muy bien", "Excelente", "Genial")
MAX_LISTED = 5
MAX_STEPS_NAMED = 4

_rng = random.Random()


def pick(options: Sequence[str]) -> str:
    """Varía el arranque de la frase para que no suene siempre igual."""
    return _rng.choice(options)


def in_sentence(title: str) -> str:
    """El título a media frase: "Pagar la luz" -> "pagar la luz". Respeta siglas como "IVA"."""
    title = title.strip().rstrip(".")
    if len(title) > 1 and title[0].isupper() and title[1].islower():
        return title[0].lower() + title[1:]
    return title


def spoken_time(moment: datetime) -> str:
    hour, minute = moment.hour, moment.minute
    if hour < 6:
        period = "de la madrugada"
    elif hour < 12:
        period = "de la mañana"
    elif hour == 12 and minute == 0:
        period = "del mediodía"
    elif hour < 19:
        period = "de la tarde"
    else:
        period = "de la noche"
    hour12 = hour % 12 or 12
    article = "a la" if hour12 == 1 else "a las"
    minutes = {0: "", 15: " y cuarto", 30: " y media"}.get(minute, f":{minute:02d}")
    return f"{article} {hour12}{minutes} {period}"


def spoken_day(moment: datetime, now: datetime) -> str:
    days = (moment.date() - now.date()).days
    if days in (-1, 0, 1, 2):
        return {-1: "ayer", 0: "hoy", 1: "mañana", 2: "pasado mañana"}[days]
    if 2 < days < 7:
        return f"el {DAYS[moment.weekday()]}"
    return f"el {DAYS[moment.weekday()]} {moment.day} de {MONTHS[moment.month - 1]}"


def spoken_moment(timestamp: int, now: datetime) -> str:
    moment = datetime.fromtimestamp(timestamp, now.tzinfo)
    return f"{spoken_day(moment, now)} {spoken_time(moment)}"


def spoken_interval(minutes: int) -> str:
    if minutes % 60 == 0:
        hours = minutes // 60
        return "cada hora" if hours == 1 else f"cada {hours} horas"
    return "cada media hora" if minutes == 30 else f"cada {minutes} minutos"


def step_names(titles: Sequence[str]) -> str:
    """Los pasos dichos de corrido: "empacar, contratar el camión y limpiar"."""
    names = [in_sentence(title) for title in titles[:MAX_STEPS_NAMED]]
    rest = len(titles) - len(names)
    if rest:
        return ", ".join(names) + (" y uno más" if rest == 1 else f" y {rest} más")
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " y " + names[-1]


def _extras(task: Task, steps: Sequence[str]) -> str:
    text = ""
    if task.repeat_minutes:
        text += f" Te lo voy a repetir {spoken_interval(task.repeat_minutes)} hasta que lo hagas."
    if steps:
        text += f" Le puse un paso: {step_names(steps)}." if len(steps) == 1 else f" Le puse {len(steps)} pasos: {step_names(steps)}."
    if task.urgency == "alta":
        text += " Quedó como urgente."
    return text


def _when(task: Task, now: datetime) -> str:
    """Las fechas de la tarea dichas de corrido, o cadena vacía si no tiene."""
    start = spoken_moment(task.due_at, now) if task.due_at is not None else ""
    deadline = f"vence {spoken_moment(task.deadline_at, now)}" if task.deadline_at is not None else ""
    return f"{start}, y {deadline}" if start and deadline else start or deadline


def created(task: Task, now: datetime, steps: Sequence[str] = ()) -> str:
    title = in_sentence(task.title)
    if task.due_at is not None:
        body = f"te recuerdo {title} {_when(task, now)}."
    elif task.deadline_at is not None:
        body = f"anoté {title}; {_when(task, now)}."
    else:
        body = f"anoté {title}, sin fecha por ahora."
    return f"{pick(CREATED)}, {body}{_extras(task, steps)}"


def edited(task: Task, now: datetime) -> str:
    when = _when(task, now) or "sin fecha"
    return f"{pick(CREATED)}, ya la cambié: {in_sentence(task.title)}, {when}.{_extras(task, ())}"


def steps_added(task: Task, steps: Sequence[str]) -> str:
    what = "un paso" if len(steps) == 1 else f"{len(steps)} pasos"
    return f"{pick(CREATED)}, le agregué {what} a {in_sentence(task.title)}: {step_names(steps)}."


def finished(task: Task, status: str, extra_lines: Sequence[str]) -> str:
    title = in_sentence(task.title)
    first = f"{pick(DONE)}, ya marqué como hecho {title}." if status == "done" else f"Listo, borré {title}."
    return " ".join([first, *extra_lines])


def task_list(roots: Sequence[Task], pending_steps: dict[int, Sequence[str]], now: datetime) -> str:
    if not roots:
        return "No tienes pendientes. Estás al día."
    items = []
    for task in roots[:MAX_LISTED]:
        item = in_sentence(task.title)
        overdue = task.overdue_from is not None and task.overdue_from < now.timestamp()
        if overdue:
            item += ", que ya está atrasada"
        elif when := _when(task, now):
            item += f", {when}"
        if steps := pending_steps.get(task.id):
            item += ", le falta " if len(steps) == 1 else f", le faltan {len(steps)} pasos: "
            item += step_names(steps)
        items.append(item)
    head = "Tienes un pendiente: " if len(roots) == 1 else f"Tienes {len(roots)} pendientes: "
    body = "; ".join(items[:-1]) + ("; y " if len(items) > 1 else "") + items[-1] + "."
    rest = len(roots) - len(items)
    if rest:
        body += " Y uno más." if rest == 1 else f" Y {rest} más."
    return head + body
