"""Textos visibles, ids y clases de la página frente a la lista de referencia (spec 001, RNF-8).

La referencia (`tests/data/page_reference.json`) se tomó con `extraer(PAGE)` antes del rediseño.
El rediseño no puede quitar textos visibles ni ids o clases que use el script (RF-32, RF-33):
lo que cambie de nombre se registra en `RENAMES` y lo nuevo solo puede ser texto accesible
(`ACCESIBLES`).
"""
from __future__ import annotations

import json
import re
import unittest
from html.parser import HTMLParser
from pathlib import Path

from hermes.status import PAGE

REFERENCE = Path(__file__).parent / "data" / "page_reference.json"

# Tabla «antes → después» (plan, apartado 6): nombre viejo → nombre nuevo (None si se elimina).
# El nombre viejo no puede aparecer en ningún uso de la página (HTML, CSS ni script).
RENAMES: dict[str, str | None] = {
    "stage": None,  # T6: se retira el tema negro y dorado (`body.stage`); el script no la usaba.
    "--s-claude": "--data-1",  # T18: serie Claude del gráfico de Consumo (leyenda y tooltip).
    "--s-local": "--data-2",  # T18: serie Modelo local del gráfico de Consumo (leyenda y tooltip).
    "brand-dot": "brand-mark",  # T22: el punto de la cabecera pasa a ser la marca en SVG en línea.
    # T23: se retiran los alias viejos de `:root` (plan, apartado 6); sus usos ya eran tokens nuevos.
    "--card": "--surface",
    "--muted": "--ink-2",
    "--faint": "--ink-3",
    "--soft": "--surface-soft",
    "--bar": "--surface-soft",
    "--shadow": "--shadow-float",  # Solo en elementos flotantes.
}

# Textos nuevos permitidos: solo para lectores de pantalla (`.sr-only` o `aria-*`), lista cerrada.
ACCESIBLES: set[str] = {
    "Cargando las tareas",  # T10: anuncio de carga de Tareas, solo para lectores de pantalla (RF-21).
    "Cargando los apuntes",  # T11: anuncio de carga de Apuntes, solo para lectores de pantalla (RF-47).
    "Cargando el consumo",  # T18: anuncio de carga de Consumo, solo para lectores de pantalla (RF-47).
    "Cargando el estado de la voz",  # T20: anuncio de carga de En vivo, solo para lectores de pantalla (RF-47).
}

# Atributos del HTML cuyo texto se ve o se lee en voz alta.
TEXT_ATTRS = ("aria-label", "placeholder", "title", "alt")
# Llamadas del script cuyos argumentos de texto son selectores.
SELECTOR_CALLS = ("querySelector", "querySelectorAll", "closest", "matches")
CLASS_NAME = re.compile(r"-?[A-Za-z_][\w-]*")
# Valores de estilo del script (colores y medidas): son geometría o paleta, no textos ni nombres.
STYLE_VALUE = re.compile(r"#[0-9a-fA-F]{3,8}|-?[\d.]*(px|%|ms|s|em|rem|vh|vw|dvh)")
TECH_CHARS = set("-_/.:#[]=()")


# ---------- Lectura del script ----------

def js_literals(source: str) -> list[tuple[int, int, str]]:
    """Literales de cadena del script: (inicio, fin, contenido sin comillas). Salta comentarios y expresiones regulares."""
    found: list[tuple[int, int, str]] = []
    i, n, prev = 0, len(source), ""
    while i < n:
        ch = source[i]
        if source.startswith("//", i):
            end = source.find("\n", i)
            i = n if end < 0 else end
        elif source.startswith("/*", i):
            end = source.find("*/", i + 2)
            i = n if end < 0 else end + 2
        elif ch in "\"'`":
            j = i + 1
            while j < n and source[j] != ch:
                j += 2 if source[j] == "\\" else 1
            found.append((i, j + 1, source[i + 1:j]))
            i, prev = j + 1, ch
        elif ch == "/" and (prev == "" or prev in "(,=:!&|?;{}[+-*%<>~^" or source[max(0, i - 7):i].rstrip().endswith("return")):
            j, in_class = i + 1, False
            while j < n and (in_class or source[j] != "/") and source[j] != "\n":
                if source[j] == "\\":
                    j += 1
                elif source[j] == "[":
                    in_class = True
                elif source[j] == "]":
                    in_class = False
                j += 1
            i, prev = j + 1, "/"
        else:
            if not ch.isspace():
                prev = ch
            i += 1
    return found


def call_args(source: str, start: int) -> list[tuple[int, int]]:
    """Tramos (inicio, fin) de cada argumento de la llamada cuyo paréntesis abre en `start`."""
    spans, depth, i, begin = [], 0, start, start + 1
    literal_at = {a: b for a, b, _ in js_literals(source[start:start + 2000])}
    while i < len(source):
        if i - start in literal_at:
            i = start + literal_at[i - start]
            continue
        ch = source[i]
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
            if depth == 0:
                spans.append((begin, i))
                return spans
        elif ch == "," and depth == 1:
            spans.append((begin, i))
            begin = i + 1
        i += 1
    return spans


def is_token(value: str) -> bool:
    """Cadena técnica de una palabra (eventos, atributos, claves, rutas): solo se vigila que no desaparezca."""
    if not value.isascii() or any(c.isspace() for c in value):
        return False
    return value == value.lower() or value == value.upper() or any(c in TECH_CHARS for c in value)


def script_parts(script: str) -> tuple[set[str], set[str], set[str], set[str]]:
    """Del script: (textos, fichas técnicas, ids, clases)."""
    literals = js_literals(script)
    ids: set[str] = set()
    classes: set[str] = set()
    used: set[int] = set()  # Inicio de los literales que son ids, clases o selectores.

    def literals_in(a: int, b: int) -> list[tuple[int, int, str]]:
        return [lit for lit in literals if a <= lit[0] and lit[1] <= b]

    def add_classes(a: int, b: int) -> None:
        for start, _, value in literals_in(a, b):
            used.add(start)
            classes.update(word for word in value.split() if CLASS_NAME.fullmatch(word))

    for match in re.finditer(r"(?<![\w.$])\$\(|\bgetElementById\(", script):
        args = call_args(script, match.end() - 1)
        if args:
            first = literals_in(*args[0])
            if len(first) == 1 and script[args[0][0]:args[0][1]].strip() == script[first[0][0]:first[0][1]]:
                used.add(first[0][0])
                ids.add(first[0][2])
    for match in re.finditer(r"\.(%s)\(" % "|".join(SELECTOR_CALLS), script):
        args = call_args(script, match.end() - 1)
        if args:
            for start, _, value in literals_in(*args[0]):
                used.add(start)
                ids.update(re.findall(r"#(-?[A-Za-z_][\w-]*)", value))
                classes.update(re.findall(r"\.(-?[A-Za-z_][\w-]*)", value))
    for match in re.finditer(r"\.classList\.(?:add|remove|toggle|contains|replace)\(", script):
        args = call_args(script, match.end() - 1)
        for a, b in args[:1] if "toggle" in match.group() else args:
            add_classes(a, b)
    for match in re.finditer(r"\.className\s*\+?=", script):
        end = script.find(";", match.end())
        add_classes(match.end(), len(script) if end < 0 else end)
    for match in re.finditer(r"(?<![\w.$])text\(", script):
        args = call_args(script, match.end() - 1)
        if len(args) >= 2:
            add_classes(*args[1])

    texts: set[str] = set()
    tokens: set[str] = set()
    for start, _, value in literals:
        if start in used or "var(--" in value or STYLE_VALUE.fullmatch(value) or not any(c.isalpha() for c in value):
            continue
        (tokens if is_token(value) else texts).add(value)
    return texts, tokens, ids, classes


# ---------- Lectura del HTML ----------

class _PageHTML(HTMLParser):
    """Textos visibles, ids y clases del HTML (sin el CSS ni el script)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.texts: set[str] = set()
        self.ids: set[str] = set()
        self.classes: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for name, value in attrs:
            value = (value or "").strip()
            if name == "id" and value:
                self.ids.add(value)
            elif name == "class":
                self.classes.update(value.split())
            elif name in TEXT_ATTRS and value:
                self.texts.add(" ".join(value.split()))

    handle_startendtag = handle_starttag

    def handle_data(self, data: str) -> None:
        data = " ".join(data.split())
        if data:
            self.texts.add(data)


def split_page(page: str) -> tuple[str, str]:
    """(HTML sin <style> ni <script>, contenido de los <script>)."""
    scripts = re.findall(r"<script>(.*?)</script>", page, re.S)
    html = re.sub(r"<(style|script)>.*?</\1>", "", page, flags=re.S)
    return html, "\n".join(scripts)


def extraer(page: str) -> dict[str, list[str]]:
    """Textos visibles, fichas técnicas del script, ids y clases que usa el script (plan 3.4)."""
    html, script = split_page(page)
    parser = _PageHTML()
    parser.feed(html)
    parser.close()
    texts, tokens, ids, classes = script_parts(script)
    return {
        "textos": sorted(parser.texts | texts),
        "fichas": sorted(tokens - parser.texts - texts),
        "ids": sorted(parser.ids | ids),
        "clases_script": sorted(classes),
    }


# ---------- Comparación ----------

def name_pattern(name: str) -> re.Pattern[str]:
    """El nombre como palabra entera de un id, una clase o una propiedad CSS (`stage` no casa con `stage-wrap`)."""
    return re.compile(r"(?<![\w-])%s(?![\w-])" % re.escape(name.lstrip(".#")))


def comparar(ref: dict, ahora: dict, page: str, renames: dict[str, str | None], accesibles: set[str]) -> list[str]:
    """Diferencias no permitidas entre la referencia y la página actual (vacía = todo bien)."""
    errors: list[str] = []
    old = [name_pattern(name) for name in renames]
    renamed = lambda value: any(p.search(value) for p in old)
    for name, new in renames.items():
        if name_pattern(name).search(page):
            errors.append(f"El nombre viejo {name!r} sigue en la página.")
        if new is not None and not name_pattern(new).search(page):
            errors.append(f"El nombre nuevo {new!r} no aparece en la página.")
    for key, label in (("textos", "el texto"), ("fichas", "la cadena del script"), ("ids", "el id"), ("clases_script", "la clase del script")):
        for value in sorted(set(ref[key]) - set(ahora[key])):
            if not renamed(value):
                errors.append(f"Ya no está {label} {value!r}.")
    for value in sorted(set(ahora["textos"]) - set(ref["textos"]) - accesibles):
        errors.append(f"Texto nuevo que no está en ACCESIBLES: {value!r}")
    return errors


# ---------- Pruebas ----------

class ExtractionTests(unittest.TestCase):
    def test_literals_skip_comments_and_regex(self):
        script = 'a("uno"); // "comentario"\n/* "otro" */ b = x.replace(/["\']/g, \'dos\'); c = `tres`; return /"/.test(y) ? "cuatro" : "";'
        self.assertEqual([v for _, _, v in js_literals(script)], ["uno", "dos", "tres", "cuatro", ""])

    def test_escaped_quote_inside_literal(self):
        self.assertEqual([v for _, _, v in js_literals(r'x = "di \"hola\""; y = "z";')], [r'di \"hola\"', "z"])

    def test_classes_ids_and_texts_from_script(self):
        page = (
            '<body><p id="p1" class="a b" title="Pista">Hola <b>mundo</b></p><style>.x{}</style>'
            '<script>$("ask-text").textContent = "Escribe algo";\n'
            'const cell = text("button", "cal-day" + (isToday ? " today" : ""), "Hoy");\n'
            'el.classList.toggle("show", ok); el.className = calm ? "primary" : "danger";\n'
            'document.querySelectorAll("#view-apuntes .ap-page").forEach(x => x.addEventListener("click", f));\n'
            'el.style.background = "var(--s-" + key + ")"; el.style.top = "0px"; c = "#e05d5d";</script></body>'
        )
        got = extraer(page)
        self.assertEqual(got["textos"], ["Escribe algo", "Hola", "Hoy", "Pista", "mundo"])
        self.assertEqual(got["fichas"], ["button", "click"])
        self.assertEqual(got["ids"], ["ask-text", "p1", "view-apuntes"])
        self.assertEqual(got["clases_script"], ["ap-page", "cal-day", "danger", "primary", "show", "today"])

    def test_known_cases_of_the_real_page(self):
        got = extraer(PAGE)
        self.assertIn("Escribe una tarea o una orden…", got["textos"])  # Texto del HTML.
        self.assertIn("La sesión terminó; entra de nuevo.", got["textos"])  # Texto que genera el script.
        self.assertIn("ask-text", got["ids"])  # Id que usa el script con $("…").
        self.assertIn("cal-nav", got["clases_script"])  # Clase que pone el script con text(tag, "clase", …).
        self.assertIn("show", got["clases_script"])  # Clase de classList.
        self.assertNotIn("stage", got["clases_script"])  # Solo la usa el CSS.


class CompareTests(unittest.TestCase):
    REF = {"textos": ["Hola", "Usa la .old-x"], "fichas": ["click"], "ids": ["a"], "clases_script": ["old-x", "keep"]}

    def now(self, **change):
        data = {"textos": ["Hola", "Usa la .new-x"], "fichas": ["click"], "ids": ["a"], "clases_script": ["new-x", "keep"]}
        data.update(change)
        return data

    def test_registered_rename_is_accepted(self):
        page = '<b class="new-x keep" id="a">Hola</b>'
        self.assertEqual(comparar(self.REF, self.now(), page, {"old-x": "new-x"}, set()), ["Texto nuevo que no está en ACCESIBLES: 'Usa la .new-x'"])
        self.assertEqual(comparar(self.REF, self.now(), page, {"old-x": "new-x"}, {"Usa la .new-x"}), [])

    def test_old_name_still_used_is_reported(self):
        page = '<b class="new-x keep" id="a">Hola</b><script>el.className = "old-x";</script>'
        errors = comparar(self.REF, self.now(), page, {"old-x": "new-x"}, {"Usa la .new-x"})
        self.assertEqual(errors, ["El nombre viejo 'old-x' sigue en la página."])

    def test_old_name_is_a_whole_word(self):
        self.assertIsNone(name_pattern("stage").search('<div class="stage-wrap"></div>'))
        self.assertIsNotNone(name_pattern("stage").search('<body class="stage">'))
        self.assertIsNotNone(name_pattern("--s-claude").search("background:var(--s-claude)"))

    def test_missing_new_name_and_unregistered_changes(self):
        errors = comparar(self.REF, self.now(ids=[], clases_script=["keep"], fichas=[]), "", {"old-x": "new-x"}, {"Usa la .new-x"})
        self.assertEqual(errors, ["El nombre nuevo 'new-x' no aparece en la página.", "Ya no está la cadena del script 'click'.", "Ya no está el id 'a'."])

    def test_removed_name_without_replacement(self):
        self.assertEqual(comparar(self.REF, self.now(), "x", {"old-x": None}, {"Usa la .new-x"}), [])


class PageReferenceTests(unittest.TestCase):
    def test_page_matches_reference(self):
        ref = json.loads(REFERENCE.read_text(encoding="utf-8"))
        errors = comparar(ref, extraer(PAGE), PAGE, RENAMES, ACCESIBLES)
        self.assertEqual(errors, [], "\n".join(errors))

    def test_tables_are_consistent(self):
        ref = json.loads(REFERENCE.read_text(encoding="utf-8"))
        self.assertTrue(ref["textos"] and ref["ids"] and ref["clases_script"])
        self.assertFalse(ACCESIBLES & set(ref["textos"]), "ACCESIBLES solo admite textos nuevos.")
        self.assertFalse(set(RENAMES) & {v for v in RENAMES.values() if v}, "Un nombre no puede ser viejo y nuevo a la vez.")

    def test_accesibles_are_only_for_screen_readers(self):
        """Cada texto de ACCESIBLES está en la página dentro de un `.sr-only` o de un atributo `aria-*` (no se ve)."""
        html, _ = split_page(PAGE)
        for value in sorted(ACCESIBLES):
            sr_only = re.search(r'<(\w+)[^>]*class="[^"]*\bsr-only\b[^"]*"[^>]*>\s*%s\s*</\1>' % re.escape(value), html)
            aria = re.search(r'\saria-[\w-]+="%s"' % re.escape(value), html)
            self.assertTrue(sr_only or aria, f"{value!r} no está en un .sr-only ni en un aria-*.")


if __name__ == "__main__":
    unittest.main()
