"""Tokens de diseño, contraste y daltonismo de la página (spec 001, RNF-6, RF-39, RF-49).

Lee las tablas de `docs/design.md` (tokens, «Contraste» y «Excepciones») y comprueba:
- que los tokens son coherentes (escalas, duraciones ≤ 300 ms, cinco tamaños de letra);
- el contraste WCAG 2.x de cada par de la tabla «Contraste», en claro y en oscuro (los
  `color-mix` se mezclan en Oklab);
- que `--data-1` y `--data-2` se distinguen con protanopía, deuteranopía y tritanopía
  (matrices de Machado et al., 2009, severidad 1,0; ΔE76 en CIELAB D65);
- que `:root` y su `@media (prefers-color-scheme: dark)` coinciden con la tabla;
- que el CSS fuera de `:root` solo usa tokens (plan 3.2), salvo las excepciones aprobadas.

Migración por secciones (plan 3.2 y decisión «@legacy»):
- Cada comentario de primer nivel del `<style>` abre una sección. Si el comentario lleva la
  marca `@legacy <vista>` (p. ej. `/* @legacy tareas */`), la sección no se comprueba. Un
  comentario explicativo de primer nivel dentro de una sección sin migrar también abre
  sección: debe llevar la marca o ir dentro de la regla.
- Un atributo `style="…"` del HTML queda fuera si contiene `/* @legacy <vista> */`.
- Estado inicial (antes de T6): mientras `:root` no declare `--surface` (token nuevo que la
  página anterior no tenía), `:root` está pendiente y todo el CSS y los `style="…"` se tratan
  como `@legacy`, aunque no lleven la marca. En cuanto `:root` se migra, valen solo las marcas.
- Las pruebas pendientes salen como «skipped» con lo que falta. T23 exige que no quede ninguna.
"""
from __future__ import annotations

import math
import re
import unittest
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path

from hermes.status import PAGE

DESIGN = Path(__file__).resolve().parent.parent / "docs" / "design.md"

# Token nuevo cuya presencia en `:root` indica que `:root` ya está migrado (T6).
ROOT_MIGRATION_TOKEN = "--surface"
# Nombres viejos que `:root` puede conservar como alias mientras alguna sección `@legacy` los use
# (plan, apartado 6). Se retiran en T18 (`--s-*`) y T23 (el resto); T23 vacía este conjunto.
ALIAS_VIEJOS = {"--card", "--muted", "--faint", "--soft", "--bar", "--shadow", "--s-claude", "--s-local"}

TOKEN_HEADER = ["Token", "Claro", "Oscuro", "Escala", "Uso"]
CONTRAST_HEADER = ["Color", "Fondo", "Mínimo", "Claro", "Oscuro"]
EXCEPTION_HEADER = ["#", "Selector", "Propiedad"]
SAME = "—"  # En «Oscuro»: mismo valor que en claro.
MODES = ("claro", "oscuro")

# Prefijo que corresponde a cada escala de la tabla de tokens.
SCALE_PREFIX = {"fuente": "--fs-", "espacio": "--sp-", "radio": "--r-", "duración": "--dur-", "curva": "--ease"}
MAX_DURATION_MS = 300
FONT_SIZES = 5
MIN_FONT_PX = 13

# Matrices de Machado, Oliveira y Fernandes (2009), severidad 1,0, en RGB lineal.
MACHADO = {
    "protanopía": ((0.152286, 1.052583, -0.204868), (0.114503, 0.786281, 0.099216), (-0.003882, -0.048116, 1.051998)),
    "deuteranopía": ((0.367322, 0.860646, -0.227968), (0.280085, 0.672501, 0.047413), (-0.011820, 0.042940, 0.968881)),
    "tritanopía": ((1.255528, -0.076749, -0.178779), (-0.078411, 0.930809, 0.147602), (0.004733, 0.691367, 0.303900)),
}

# Colores con nombre de CSS (los que se usan como literal de color). Sin `transparent` ni `currentColor`.
NAMED_COLORS = set("""
aliceblue antiquewhite aqua aquamarine azure beige bisque black blanchedalmond blue blueviolet brown burlywood
cadetblue chartreuse chocolate coral cornflowerblue cornsilk crimson cyan darkblue darkcyan darkgoldenrod darkgray
darkgreen darkgrey darkkhaki darkmagenta darkolivegreen darkorange darkorchid darkred darksalmon darkseagreen
darkslateblue darkslategray darkslategrey darkturquoise darkviolet deeppink deepskyblue dimgray dimgrey dodgerblue
firebrick floralwhite forestgreen fuchsia gainsboro ghostwhite gold goldenrod gray green greenyellow grey honeydew
hotpink indianred indigo ivory khaki lavender lavenderblush lawngreen lemonchiffon lightblue lightcoral lightcyan
lightgoldenrodyellow lightgray lightgreen lightgrey lightpink lightsalmon lightseagreen lightskyblue lightslategray
lightslategrey lightsteelblue lightyellow lime limegreen linen magenta maroon mediumaquamarine mediumblue
mediumorchid mediumpurple mediumseagreen mediumslateblue mediumspringgreen mediumturquoise mediumvioletred
midnightblue mintcream mistyrose moccasin navajowhite navy oldlace olive olivedrab orange orangered orchid
palegoldenrod palegreen paleturquoise palevioletred papayawhip peachpuff peru pink plum powderblue purple
rebeccapurple red rosybrown royalblue saddlebrown salmon sandybrown seagreen seashell sienna silver skyblue
slateblue slategray slategrey snow springgreen steelblue tan teal thistle tomato turquoise violet wheat white
whitesmoke yellow yellowgreen
""".split())
COLOR_FUNCTION = re.compile(r"(?<![\w-])(rgba?|hsla?|hwb|lab|lch|oklab|oklch|color)\(", re.I)
HEX_COLOR = re.compile(r"#[0-9a-fA-F]{3,8}(?![\w-])")
TIME_LITERAL = re.compile(r"(?<![\w.-])-?(\d*\.?\d+)(ms|s)(?![\w-])", re.I)
LENGTH_LITERAL = re.compile(r"(?<![\w.-])\d*\.?\d+(px|r?em|pt|vh|vw|%)(?![\w-])", re.I)
CSS_WIDE = {"inherit", "initial", "unset", "revert", "revert-layer"}
EASINGS = {"ease", "ease-in", "ease-out", "ease-in-out", "linear", "step-start", "step-end"}
INSET_PROPS = {"inset", "inset-inline", "inset-block", "inset-inline-start", "inset-inline-end",
               "inset-block-start", "inset-block-end", "top", "right", "bottom", "left"}
SPACING_PROPS = {"gap", "row-gap", "column-gap"}
# Propiedades que el script calcula con datos: geometría, no espaciado (plan 3.2).
JS_GEOMETRY = {"width", "height", "top", "left", "right", "bottom", "display", "transform"}


# ---------- docs/design.md ----------

def md_tables(text: str) -> list[tuple[list[str], list[list[str]]]]:
    """Tablas Markdown del texto: (cabecera, filas), con las celdas sin espacios de los bordes."""
    tables: list[tuple[list[str], list[list[str]]]] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("|") and i + 1 < len(lines) and re.fullmatch(r"\|[\s:|-]+\|", lines[i + 1].strip()):
            header = [c.strip() for c in line.strip("|").split("|")]
            rows: list[list[str]] = []
            i += 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            tables.append((header, rows))
        else:
            i += 1
    return tables


def unquote(cell: str) -> str:
    """Valor de una celda entre comillas invertidas (o la celda tal cual)."""
    match = re.fullmatch(r"`([^`]*)`", cell.strip())
    return match.group(1) if match else cell.strip()


@dataclass
class Token:
    name: str
    light: str
    dark: str | None  # None = mismo valor que en claro.
    scale: str


def parse_tokens(text: str) -> dict[str, Token]:
    """Tokens de todas las tablas `Token | Claro | Oscuro | Escala | Uso`."""
    tokens: dict[str, Token] = {}
    for header, rows in md_tables(text):
        if header != TOKEN_HEADER:
            continue
        for row in rows:
            name, light, dark, scale = (unquote(c) for c in row[:4])
            if name in tokens:
                raise ValueError(f"Token repetido en docs/design.md: {name}")
            tokens[name] = Token(name, light, None if dark == SAME else dark, scale)
    return tokens


def parse_contrast(text: str) -> list[tuple[str, str, float, float, float]]:
    """Filas de la tabla «Contraste»: (color, fondo, mínimo, claro declarado, oscuro declarado)."""
    for header, rows in md_tables(text):
        if header == CONTRAST_HEADER:
            return [(unquote(r[0]), unquote(r[1]), float(r[2]), float(r[3]), float(r[4])) for r in rows]
    return []


@dataclass
class Exception_:
    key: str
    selectors: list[str]
    prop: str
    approval: str


def parse_exceptions(text: str) -> list[Exception_]:
    """Filas de la tabla «Excepciones» (solo las de CSS: las de archivos no tienen propiedad)."""
    found: list[Exception_] = []
    for header, rows in md_tables(text):
        if header[:3] != EXCEPTION_HEADER:
            continue
        approval_col = header.index("Aprobación")
        for row in rows:
            if row[1].startswith("archivos"):
                continue
            selectors = [norm_selector(s) for s in re.findall(r"`([^`]+)`", row[1])]
            found.append(Exception_(row[0], selectors, unquote(row[2]).lower(), row[approval_col]))
    return found


def parse_daltonism(text: str) -> tuple[float, dict[tuple[str, str], float]]:
    """ΔE76 mínimo y cifras declaradas en «Colores de datos»: {(modo, deficiencia): ΔE}."""
    text = " ".join(text.split())
    minimum = float(re.search(r"mínimo exigido (\d+(?:[.,]\d+)?)", text).group(1).replace(",", "."))
    declared: dict[tuple[str, str], float] = {}
    names = {"prot": "protanopía", "deut": "deuteranopía", "trit": "tritanopía"}
    for mode, chunk in re.findall(r"(claro|oscuro) ((?:(?:prot|deut|trit)\. \d+,\d+(?: · )?)+)", text):
        for short, value in re.findall(r"(prot|deut|trit)\. (\d+,\d+)", chunk):
            declared[(mode, names[short])] = float(value.replace(",", "."))
    return minimum, declared


# ---------- Color ----------

RGB = tuple[float, float, float]


def hex_to_rgb(value: str) -> RGB:
    """`#RGB` o `#RRGGBB` → sRGB en 0..1."""
    h = value.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        raise ValueError(f"Color no admitido: {value}")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]


def to_linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def from_linear(c: float) -> float:
    c = min(1.0, max(0.0, c))
    return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def luminance(rgb: RGB) -> float:
    """Luminancia relativa WCAG 2.x."""
    r, g, b = (to_linear(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: RGB, b: RGB) -> float:
    """Relación de contraste WCAG 2.x (1 a 21)."""
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def rgb_to_oklab(rgb: RGB) -> RGB:
    r, g, b = (to_linear(c) for c in rgb)
    l = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
    m = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
    s = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b
    l, m, s = (math.copysign(abs(x) ** (1 / 3), x) for x in (l, m, s))
    return (0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
            1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
            0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s)


def oklab_to_rgb(lab: RGB) -> RGB:
    L, a, b = lab
    l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s = (L - 0.0894841775 * a - 1.2914855480 * b) ** 3
    return (from_linear(4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s),
            from_linear(-1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s),
            from_linear(-0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s))


def mix_oklab(a: RGB, b: RGB, weight_a: float) -> RGB:
    """`color-mix(in oklab, a p%, b)` con p = weight_a (0..1)."""
    la, lb = rgb_to_oklab(a), rgb_to_oklab(b)
    return oklab_to_rgb(tuple(x * weight_a + y * (1 - weight_a) for x, y in zip(la, lb)))  # type: ignore[arg-type]


def lab_d65(rgb_linear: RGB) -> RGB:
    """RGB lineal → CIELAB (D65)."""
    r, g, b = (min(1.0, max(0.0, c)) for c in rgb_linear)
    x = (0.4124564 * r + 0.3575761 * g + 0.1804375 * b) / 0.95047
    y = 0.2126729 * r + 0.7151522 * g + 0.0721750 * b
    z = (0.0193339 * r + 0.1191920 * g + 0.9503041 * b) / 1.08883
    f = lambda t: t ** (1 / 3) if t > (6 / 29) ** 3 else t / (3 * (6 / 29) ** 2) + 4 / 29
    fx, fy, fz = f(x), f(y), f(z)
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


def simulate(rgb: RGB, deficiency: str) -> RGB:
    """Color visto con la deficiencia (Machado 2009), en RGB lineal."""
    lin = [to_linear(c) for c in rgb]
    return tuple(sum(m * c for m, c in zip(row, lin)) for row in MACHADO[deficiency])  # type: ignore[return-value]


def delta_e76(a: RGB, b: RGB) -> float:
    return math.dist(a, b)


def split_args(text: str) -> list[str]:
    """Argumentos separados por comas de primer nivel."""
    parts, depth, begin = [], 0, 0
    for i, ch in enumerate(text):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append(text[begin:i].strip())
            begin = i + 1
    parts.append(text[begin:].strip())
    return parts


def resolve_color(value: str, mode: str, tokens: dict[str, Token], seen: tuple[str, ...] = ()) -> RGB:
    """Color opaco de un valor de token en el modo dado (hex, var() o color-mix en Oklab)."""
    value = value.strip()
    if value.startswith("#"):
        return hex_to_rgb(value)
    match = re.fullmatch(r"var\((--[\w-]+)\)", value)
    if match:
        name = match.group(1)
        if name in seen:
            raise ValueError(f"Referencia circular: {' → '.join(seen + (name,))}")
        return token_color(name, mode, tokens, seen + (name,))
    match = re.fullmatch(r"color-mix\((.*)\)", value)
    if match:
        space, first, second = split_args(match.group(1))
        if space.lower() != "in oklab":
            raise ValueError(f"Solo se calcula color-mix en Oklab: {value}")
        parts = []
        for arg in (first, second):
            pct = re.search(r"\s(\d+(?:\.\d+)?)%$", arg)
            parts.append((resolve_color(arg[:pct.start()] if pct else arg, mode, tokens, seen), float(pct.group(1)) / 100 if pct else None))
        (a, pa), (b, pb) = parts
        weight = pa if pa is not None else (1 - pb if pb is not None else 0.5)
        if pa is not None and pb is not None:
            weight = pa / (pa + pb)
        return mix_oklab(a, b, weight)
    raise ValueError(f"Color no admitido para el contraste: {value}")


def token_value(name: str, mode: str, tokens: dict[str, Token]) -> str:
    token = tokens[name]
    return token.dark if mode == "oscuro" and token.dark is not None else token.light


def token_color(name: str, mode: str, tokens: dict[str, Token], seen: tuple[str, ...] = ()) -> RGB:
    return resolve_color(token_value(name, mode, tokens), mode, tokens, seen or (name,))


# ---------- CSS ----------

@dataclass
class Rule:
    selectors: list[str]
    declarations: list[tuple[str, str]]
    context: tuple[str, ...]  # Preludios de las reglas @ que la contienen.
    start: int


@dataclass
class Sheet:
    rules: list[Rule] = field(default_factory=list)
    comments: list[tuple[int, str]] = field(default_factory=list)  # Comentarios de primer nivel.


def norm_selector(selector: str) -> str:
    return " ".join(selector.replace("'", '"').split())


def strip_comments(text: str) -> str:
    return re.sub(r"/\*.*?\*/", " ", text, flags=re.S)


def parse_declarations(body: str) -> list[tuple[str, str]]:
    """`prop: valor; …` → [(prop, valor)], sin comentarios ni `!important`."""
    body = strip_comments(body)
    decls, depth, begin, quote = [], 0, 0, ""
    chunks = []
    for i, ch in enumerate(body):
        if quote:
            if ch == quote and body[i - 1] != "\\":
                quote = ""
        elif ch in "\"'":
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == ";" and depth == 0:
            chunks.append(body[begin:i])
            begin = i + 1
    chunks.append(body[begin:])
    for chunk in chunks:
        if ":" not in chunk:
            continue
        prop, value = chunk.split(":", 1)
        prop = prop.strip()
        value = re.sub(r"\s*!important\s*$", "", " ".join(value.split()), flags=re.I)
        if prop:
            decls.append((prop if prop.startswith("--") else prop.lower(), value))
    return decls


GROUP_AT_RULES = ("@media", "@supports", "@layer", "@container", "@keyframes", "@-webkit-keyframes", "@document")


def parse_css(css: str) -> Sheet:
    """Reglas (con su contexto de reglas @) y comentarios de primer nivel de una hoja de estilos."""
    sheet = Sheet()
    context: list[str] = []
    i, n, begin = 0, len(css), 0
    while i < n:
        if css.startswith("/*", i):
            end = css.find("*/", i + 2)
            end = n if end < 0 else end + 2
            if not context and not css[begin:i].strip():
                sheet.comments.append((i, css[i + 2:end - 2].strip()))
                begin = end  # El comentario no forma parte del selector que sigue.
            i = end
            continue
        ch = css[i]
        if ch in "\"'":
            j = i + 1
            while j < n and css[j] != ch:
                j += 2 if css[j] == "\\" else 1
            i = j + 1
            continue
        if ch == "{":
            prelude = " ".join(strip_comments(css[begin:i]).split())
            if prelude.lower().startswith(GROUP_AT_RULES):
                context.append(prelude)
                i += 1
                begin = i
                continue
            close, depth, j = -1, 1, i + 1
            while j < n:
                if css[j] == "{":
                    depth += 1
                elif css[j] == "}":
                    depth -= 1
                    if depth == 0:
                        close = j
                        break
                j += 1
            close = n if close < 0 else close
            selectors = [norm_selector(s) for s in split_args(prelude)] if not prelude.startswith("@") else [prelude]
            sheet.rules.append(Rule(selectors, parse_declarations(css[i + 1:close]), tuple(context), begin + len(css[begin:i]) - len(css[begin:i].lstrip())))
            i = close + 1
            begin = i
            continue
        if ch == "}":
            if context:
                context.pop()
            i += 1
            begin = i
            continue
        if ch == ";" and not context and css[begin:i].strip().startswith("@"):
            begin = i + 1  # @import, @charset…
        i += 1
    return sheet


def page_css(page: str) -> str:
    match = re.search(r"<style>(.*?)</style>", page, re.S)
    return match.group(1) if match else ""


def is_root(rule: Rule) -> bool:
    return rule.selectors == [":root"]


def root_declarations(sheet: Sheet) -> tuple[dict[str, str], dict[str, str]]:
    """Propiedades personalizadas de `:root` en claro y dentro de `@media (prefers-color-scheme: dark)`."""
    light: dict[str, str] = {}
    dark: dict[str, str] = {}
    for rule in sheet.rules:
        if not is_root(rule):
            continue
        if not rule.context:
            target = light
        elif len(rule.context) == 1 and re.fullmatch(r"@media \(prefers-color-scheme: ?dark\)", rule.context[0]):
            target = dark
        else:
            continue
        target.update((p, v) for p, v in rule.declarations if p.startswith("--"))
    return light, dark


def norm_value(value: str) -> str:
    value = " ".join(value.split())
    value = re.sub(r"\s*,\s*", ", ", value)
    value = re.sub(r"\(\s+", "(", value)
    value = re.sub(r"\s+\)", ")", value)
    return re.sub(r"#[0-9a-fA-F]{3,8}", lambda m: m.group().lower(), value)


def compare_root(sheet: Sheet, tokens: dict[str, Token], aliases: set[str]) -> list[str]:
    """Diferencias entre `:root` (y su modo oscuro) y la tabla de tokens."""
    light, dark = root_declarations(sheet)
    errors: list[str] = []
    for name, token in tokens.items():
        if name not in light:
            errors.append(f":root no declara {name}.")
        elif norm_value(light[name]) != norm_value(token.light):
            errors.append(f":root {name}: {light[name]!r} ≠ {token.light!r} (claro).")
        if token.dark is None:
            if name in dark and norm_value(dark[name]) != norm_value(token.light):
                errors.append(f"Modo oscuro {name}: {dark[name]!r}, pero la tabla dice «—» (mismo valor).")
        elif name not in dark:
            errors.append(f"El modo oscuro no declara {name}.")
        elif norm_value(dark[name]) != norm_value(token.dark):
            errors.append(f"Modo oscuro {name}: {dark[name]!r} ≠ {token.dark!r}.")
    for name in sorted((set(light) | set(dark)) - set(tokens) - aliases):
        errors.append(f":root declara {name}, que no está en docs/design.md ni es un alias viejo.")
    return errors


# ---------- Secciones @legacy ----------

LEGACY_MARK = re.compile(r"^@legacy(?:\s+(\S.*))?$", re.S)


def sections(sheet: Sheet) -> list[tuple[str, bool, list[Rule]]]:
    """Secciones (comentario que las abre, legacy, reglas). La primera, antes de todo comentario, se llama «(inicio)»."""
    bounds = [(0, "(inicio)")] + sheet.comments
    result: list[tuple[str, bool, list[Rule]]] = []
    for k, (start, title) in enumerate(bounds):
        end = bounds[k + 1][0] if k + 1 < len(bounds) else math.inf
        rules = [r for r in sheet.rules if start <= r.start < end]
        result.append((title, bool(LEGACY_MARK.match(title)), rules))
    return result


def root_migrated(sheet: Sheet) -> bool:
    return ROOT_MIGRATION_TOKEN in root_declarations(sheet)[0]


# ---------- Comprobación de declaraciones (plan 3.2) ----------

def strip_strings_and_urls(value: str) -> str:
    value = re.sub(r"url\([^)]*\)", "url()", value, flags=re.I)
    return re.sub(r"\"[^\"]*\"|'[^']*'", '""', value)


def words(value: str) -> list[str]:
    return re.findall(r"(?<![\w#.-])[A-Za-z][\w-]*", value)


def is_color_prop(prop: str) -> bool:
    return ("color" in prop or prop.startswith(("background", "border", "outline", "column-rule", "text-decoration"))
            or prop in {"fill", "stroke", "box-shadow", "text-shadow"} or prop.startswith("--"))


def top_level_terms(value: str) -> list[str]:
    """Términos separados por espacios de primer nivel (`0 var(--sp-2) calc(…)` → 3 términos)."""
    terms, depth, current = [], 0, ""
    for ch in value:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch in " /" and depth == 0:
            if current:
                terms.append(current)
            current = ""
        else:
            current += ch
    if current:
        terms.append(current)
    return terms


ZERO = re.compile(r"-?0(?:\.0+)?(?:px|r?em|%)?")


def spacing_term_ok(term: str) -> bool:
    if term in {"auto"} or ZERO.fullmatch(term) or re.fullmatch(r"var\(--sp-\d+\)", term):
        return True
    if re.fullmatch(r"env\(safe-area-inset-(top|right|bottom|left)(, ?-?0(px)?)?\)", term):
        return True
    match = re.fullmatch(r"(calc|max|min)\((.*)\)", term)
    if match:
        return only_multipliers(match.group(2))
    return False


def only_multipliers(inner: str) -> bool:
    """En `calc()`: los números sin unidad solo pueden multiplicar o dividir un token."""
    cleaned = re.sub(r"var\(--sp-\d+\)|env\(safe-area-inset-(?:top|right|bottom|left)(?:, ?-?0(?:px)?)?\)", "T", inner)
    cleaned = re.sub(r"(calc|max|min)\(", "(", cleaned)
    if re.search(r"[A-SU-Za-z%]", cleaned) or not re.fullmatch(r"[\sT\d.+*/(),-]*", cleaned):
        return False
    # Cada número debe ir junto a `*` o `/`, o ser cero.
    for match in re.finditer(r"-?\d*\.?\d+", cleaned):
        before = cleaned[:match.start()].rstrip()[-1:]
        after = cleaned[match.end():].lstrip()[:1]
        if float(match.group()) != 0 and before not in ("*", "/") and after not in ("*", "/"):
            return False
    return True


def check_declaration(prop: str, value: str, fixed: bool) -> list[str]:
    """Problemas de una declaración fuera de `:root` (vacía = solo usa tokens)."""
    problems: list[str] = []
    if value.lower() in CSS_WIDE:
        return problems
    plain = strip_strings_and_urls(value)
    if HEX_COLOR.search(plain) or COLOR_FUNCTION.search(re.sub(r"color-mix\(", "", plain, flags=re.I)):
        problems.append("literal de color")
    elif is_color_prop(prop) and any(w.lower() in NAMED_COLORS for w in words(plain)):
        problems.append("color con nombre")
    if prop == "font-size" and not re.fullmatch(r"var\(--fs-[\w-]+\)", value):
        problems.append("tamaño de letra fuera de var(--fs-*)")
    if prop == "font" and LENGTH_LITERAL.search(plain):
        problems.append("tamaño de letra literal en `font`")
    if prop.startswith(("margin", "padding")) or prop in SPACING_PROPS or (fixed and prop in INSET_PROPS):
        if not all(spacing_term_ok(t) for t in top_level_terms(value)):
            problems.append("espacio fuera de var(--sp-*)")
    if prop == "border-radius" or (prop.startswith("border-") and prop.endswith("-radius")):
        if not all(ZERO.fullmatch(t) or re.fullmatch(r"var\(--r-[\w-]+\)", t) for t in top_level_terms(value)):
            problems.append("radio fuera de var(--r-*)")
    if prop.startswith(("transition", "animation")):
        bare = re.sub(r"var\(--[\w-]+\)", " ", plain)
        if any(float(m.group(1)) != 0 for m in TIME_LITERAL.finditer(bare)):
            problems.append("duración literal (usa var(--dur-*))")
        lowered = {w.lower() for w in words(bare)}
        if "all" in lowered:
            problems.append("`all` en transición")
        if lowered & EASINGS or re.search(r"cubic-bezier\(|steps\(", bare, re.I):
            problems.append("curva literal (usa var(--ease-*))")
    return problems


def exception_for(rule_selectors: list[str], prop: str, exceptions: list[Exception_]) -> Exception_ | None:
    """Excepción aprobada que cubre la propiedad en alguno de los selectores de la regla."""
    for exc in exceptions:
        if not (prop == exc.prop or prop.startswith(exc.prop + "-")):
            continue
        for selector in rule_selectors:
            for target in exc.selectors:
                if selector == target or (selector.startswith(target) and selector[len(target)] in ":[ .>#"):
                    return exc
    return None


def fixed_selectors(sheet: Sheet) -> set[str]:
    return {s for r in sheet.rules if ("position", "fixed") in r.declarations for s in r.selectors}


def check_rules(rules: list[Rule], exceptions: list[Exception_], fixed: set[str]) -> list[str]:
    errors: list[str] = []
    for rule in rules:
        if is_root(rule):
            continue
        is_fixed = any(s in fixed for s in rule.selectors)
        for prop, value in rule.declarations:
            problems = check_declaration(prop, value, is_fixed)
            if problems and not exception_for(rule.selectors, prop, exceptions):
                where = " ".join(rule.context + (", ".join(rule.selectors),))
                errors.append(f"{where} {{ {prop}: {value} }} → {', '.join(problems)}")
    return errors


class _InlineStyles(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.styles: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.styles.extend(v for k, v in attrs if k == "style" and v)

    handle_startendtag = handle_starttag


def inline_styles(page: str) -> list[str]:
    html = re.sub(r"<(style|script)>.*?</\1>", "", page, flags=re.S)
    parser = _InlineStyles()
    parser.feed(html)
    parser.close()
    return parser.styles


def check_inline(styles: list[str]) -> list[str]:
    errors: list[str] = []
    for style in styles:
        decls = parse_declarations(style)
        fixed = ("position", "fixed") in decls
        for prop, value in decls:
            problems = check_declaration(prop, value, fixed)
            if problems:
                errors.append(f'style="{style}" → {prop}: {", ".join(problems)}')
    return errors


def script_styles(page: str) -> list[tuple[str, str]]:
    """Valores literales que el script asigna a estilos: `.style.x = "…"` y `.style.setProperty("--x", "…")`."""
    script = "\n".join(re.findall(r"<script>(.*?)</script>", page, re.S))
    found = [(re.sub(r"[A-Z]", lambda m: "-" + m.group().lower(), p), v)
             for p, v in re.findall(r"\.style\.(\w+)\s*=\s*\"([^\"]*)\"\s*[;,)\n]", script)]
    found += re.findall(r"\.style\.setProperty\(\s*\"([\w-]+)\"\s*,\s*\"([^\"]*)\"\s*\)", script)
    return found


def check_script(values: list[tuple[str, str]]) -> list[str]:
    errors: list[str] = []
    for prop, value in values:
        if prop in JS_GEOMETRY:
            continue
        problems = check_declaration(prop, value, False)
        if problems:
            errors.append(f"script: .style {prop} = {value!r} → {', '.join(problems)}")
    return errors


# ---------- Datos compartidos ----------

def load() -> tuple[str, dict[str, Token], Sheet]:
    text = DESIGN.read_text(encoding="utf-8")
    return text, parse_tokens(text), parse_css(page_css(PAGE))


# ---------- Pruebas de las funciones (casos conocidos) ----------

class ColorMathTests(unittest.TestCase):
    def test_black_white_is_21(self):
        self.assertAlmostEqual(contrast((0, 0, 0), (1, 1, 1)), 21.0, places=6)
        self.assertAlmostEqual(contrast((1, 1, 1), (1, 1, 1)), 1.0, places=6)

    def test_known_contrast(self):
        # #767676 sobre blanco es el gris más claro con 4,5:1 (valor conocido: 4,54).
        self.assertAlmostEqual(contrast(hex_to_rgb("#767676"), hex_to_rgb("#ffffff")), 4.54, places=2)

    def test_oklab_round_trip_and_mix(self):
        for value in ("#17697a", "#ffffff", "#000000", "#b42318"):
            back = oklab_to_rgb(rgb_to_oklab(hex_to_rgb(value)))
            for x, y in zip(back, hex_to_rgb(value)):
                self.assertAlmostEqual(x, y, places=5)
        white, black = hex_to_rgb("#ffffff"), hex_to_rgb("#000000")
        self.assertEqual(mix_oklab(white, black, 1.0), mix_oklab(white, white, 0.3))
        # En Oklab, la mitad entre negro y blanco tiene L = 0,5 (más claro que el 50 % en sRGB).
        self.assertAlmostEqual(rgb_to_oklab(mix_oklab(white, black, 0.5))[0], 0.5, places=4)

    def test_resolve_var_and_color_mix(self):
        tokens = {
            "--a": Token("--a", "#ffffff", "#000000", "color"),
            "--b": Token("--b", "var(--a)", None, "color"),
            "--m": Token("--m", "color-mix(in oklab, var(--a) 100%, #123456)", None, "color"),
        }
        self.assertEqual(token_color("--b", "claro", tokens), (1, 1, 1))
        self.assertEqual(token_color("--b", "oscuro", tokens), (0, 0, 0))
        for x in token_color("--m", "oscuro", tokens):
            self.assertAlmostEqual(x, 0.0, places=6)

    def test_machado_identity_on_grey_and_lab(self):
        grey = hex_to_rgb("#808080")
        for deficiency in MACHADO:
            sim = simulate(grey, deficiency)
            for c in sim:
                self.assertAlmostEqual(c, to_linear(grey[0]), places=2)
        self.assertAlmostEqual(lab_d65((1, 1, 1))[0], 100.0, places=3)
        self.assertAlmostEqual(delta_e76(lab_d65((1, 1, 1)), lab_d65((0, 0, 0))), 100.0, places=3)


class ParserTests(unittest.TestCase):
    DOC = (
        "| Token | Claro | Oscuro | Escala | Uso |\n|---|---|---|---|---|\n"
        "| `--bg` | `#FFFFFF` | `#000000` | color | Fondo |\n"
        "| `--fs-md` | `16px` | — | fuente | Cuerpo |\n\n"
        "| Color | Fondo | Mínimo | Claro | Oscuro |\n|---|---|---|---|---|\n"
        "| `--bg` | `--bg` | 4.5 | 1.00 | 1.00 |\n\n"
        "| # | Selector | Propiedad | Regla que rompe | Motivo | Aprobación |\n|---|---|---|---|---|---|\n"
        "| E2 | `.chip-color` | `color` | x | y | Aprobada por el usuario (2026-11-18) |\n"
        "| E3 | `.ripple`, `.orb[data-state=\"pensando\"] .disc` | `animation` | x | y | Aprobada |\n"
        "| E5 | archivos `logo.webp` | — | x | y | Aprobada |\n"
    )

    def test_tables(self):
        tokens = parse_tokens(self.DOC)
        self.assertEqual(tokens["--bg"], Token("--bg", "#FFFFFF", "#000000", "color"))
        self.assertIsNone(tokens["--fs-md"].dark)
        self.assertEqual(parse_contrast(self.DOC), [("--bg", "--bg", 4.5, 1.0, 1.0)])
        exceptions = parse_exceptions(self.DOC)
        self.assertEqual([e.key for e in exceptions], ["E2", "E3"])
        self.assertEqual(exceptions[1].selectors, [".ripple", '.orb[data-state="pensando"] .disc'])

    def test_css_parser_sections_and_root(self):
        css = (":root { --bg:#fff; --x: 1px }\n@media (prefers-color-scheme: dark) { :root { --bg:#000; } }\n"
               "/* @legacy tareas */\n.a, .b { color:#123 }\n@media (max-width:640px) { .c { gap:4px } }\n"
               "/* Marco */\n/* explicación */\n.d { color:var(--ink); /* nota */ }\n")
        sheet = parse_css(css)
        self.assertEqual(root_declarations(sheet), ({"--bg": "#fff", "--x": "1px"}, {"--bg": "#000"}))
        got = [(title, legacy, [r.selectors for r in rules]) for title, legacy, rules in sections(sheet)]
        self.assertEqual(got, [("(inicio)", False, [[":root"], [":root"]]),
                               ("@legacy tareas", True, [[".a", ".b"], [".c"]]),
                               ("Marco", False, []),
                               ("explicación", False, [[".d"]])])
        self.assertEqual(sheet.rules[3].context, ("@media (max-width:640px)",))

    def test_literal_color_is_detected(self):
        self.assertEqual(check_declaration("color", "#e05d5d", False), ["literal de color"])
        self.assertEqual(check_declaration("box-shadow", "0 1px 2px rgba(0,0,0,.1)", False), ["literal de color"])
        self.assertEqual(check_declaration("background", "white", False), ["color con nombre"])
        self.assertEqual(check_declaration("color", "var(--muted, #a19f96)", False), ["literal de color"])
        self.assertEqual(check_declaration("background", "color-mix(in oklab, var(--accent) 12%, var(--surface))", False), [])
        self.assertEqual(check_declaration("border", "1px solid var(--line-strong)", False), [])
        self.assertEqual(check_declaration("color", "currentColor", False), [])

    def test_sizes_spacing_radius_and_motion(self):
        ok = [("font-size", "var(--fs-md)"), ("font", "inherit"), ("font", "600 var(--fs-md)/1.5 var(--font)"),
              ("margin", "0 auto"), ("padding", "var(--sp-2) var(--sp-4)"),
              ("padding-bottom", "calc(var(--sp-7) + env(safe-area-inset-bottom))"),
              ("margin-top", "calc(-1 * var(--sp-2))"), ("padding-left", "max(var(--sp-4), env(safe-area-inset-left))"),
              ("border-radius", "var(--r-md) var(--r-md) 0 0"),
              ("transition", "opacity var(--dur-2) var(--ease-out), transform var(--dur-2) var(--ease-out)"),
              ("animation", "none")]
        for prop, value in ok:
            self.assertEqual(check_declaration(prop, value, True), [], f"{prop}: {value}")
        bad = [("font-size", "15px"), ("font", "15px/1.5 system-ui"), ("gap", "12px"),
               ("padding", "calc(56px + env(safe-area-inset-bottom))"), ("border-radius", "50%"),
               ("transition", "opacity .2s"), ("transition", "all var(--dur-1)"),
               ("transition", "opacity var(--dur-1) ease-in"), ("animation", "spin 1s linear infinite")]
        for prop, value in bad:
            self.assertTrue(check_declaration(prop, value, False), f"{prop}: {value}")
        self.assertEqual(check_declaration("bottom", "22px", False), [])  # Solo en elementos fijos.
        self.assertTrue(check_declaration("bottom", "22px", True))

    def test_approved_exception_is_accepted(self):
        exceptions = parse_exceptions(DESIGN.read_text(encoding="utf-8"))
        rules = parse_css('.chip-color { color:#3567b5 } .orb[data-state="pensando"] .disc { animation:breathe 1.6s ease-in-out infinite }'
                          ' .other { color:#3567b5 } .chip-color { background:#fff }').rules
        errors = check_rules(rules, exceptions, set())
        self.assertEqual(len(errors), 2, errors)
        self.assertTrue(errors[0].startswith(".other "))
        self.assertTrue(errors[1].startswith(".chip-color { background"))

    def test_inline_and_script_styles(self):
        page = ('<div style="margin:10px 0 8px"></div><div style="/* @legacy ajustes */ margin:10px"></div><style>x{}</style>'
                '<script>a.style.width = "40%"; b.style.background = "#fff"; c.style.setProperty("--cat", "red");'
                ' d.style.background = "var(--s-" + k + ")";</script>')
        self.assertEqual(inline_styles(page), ["margin:10px 0 8px", "/* @legacy ajustes */ margin:10px"])
        self.assertEqual(script_styles(page), [("width", "40%"), ("background", "#fff"), ("--cat", "red")])
        self.assertEqual(len(check_script(script_styles(page))), 2)
        self.assertEqual(len(check_inline(["margin:10px 0 8px", "margin:0"])), 1)


# ---------- docs/design.md ----------

class DesignDocTests(unittest.TestCase):
    def setUp(self):
        self.text, self.tokens, _ = load()

    def test_token_scales(self):
        self.assertTrue(self.tokens, "docs/design.md no tiene tablas de tokens.")
        for token in self.tokens.values():
            prefix = SCALE_PREFIX.get(token.scale)
            if prefix:
                self.assertTrue(token.name.startswith(prefix), f"{token.name} no corresponde a la escala {token.scale}.")
        for name, scale in (("--fs-", "fuente"), ("--sp-", "espacio"), ("--r-", "radio"), ("--dur-", "duración"), ("--ease", "curva")):
            for token in self.tokens.values():
                if token.name.startswith(name):
                    self.assertEqual(token.scale, scale, token.name)

    def test_five_font_sizes(self):
        sizes = [t for t in self.tokens.values() if t.scale == "fuente"]
        self.assertEqual(len(sizes), FONT_SIZES)
        for token in sizes:
            self.assertIsNone(token.dark)
            self.assertGreaterEqual(float(re.fullmatch(r"(\d+(?:\.\d+)?)px", token.light).group(1)), MIN_FONT_PX, token.name)

    def test_motion_tokens(self):
        for token in self.tokens.values():
            for value in filter(None, (token.light, token.dark)):
                if token.scale == "duración":
                    match = re.fullmatch(r"(\d+(?:\.\d+)?)(ms|s)", value)
                    self.assertIsNotNone(match, token.name)
                    ms = float(match.group(1)) * (1 if match.group(2) == "ms" else 1000)
                    self.assertLessEqual(ms, MAX_DURATION_MS, token.name)
                if token.scale == "curva":
                    self.assertNotIn(value, {"ease-in", "ease-in-out", "linear"}, token.name)

    def test_contrast_pairs(self):
        pairs = parse_contrast(self.text)
        self.assertTrue(pairs, "docs/design.md no tiene la tabla «Contraste».")
        failures = []
        for color, background, minimum, *declared in pairs:
            for mode, stated in zip(MODES, declared):
                ratio = contrast(token_color(color, mode, self.tokens), token_color(background, mode, self.tokens))
                if ratio < minimum:
                    failures.append(f"{color} sobre {background} ({mode}): {ratio:.2f} < {minimum}")
                if abs(ratio - stated) > 0.02:
                    failures.append(f"{color} sobre {background} ({mode}): calculado {ratio:.2f}, la tabla dice {stated:.2f}")
        self.assertEqual(failures, [], "\n".join(failures))

    def test_data_colors_with_colour_blindness(self):
        minimum, declared = parse_daltonism(self.text)
        self.assertEqual(len(declared), 6, "Faltan las cifras de ΔE de «Colores de datos».")
        failures = []
        for mode in MODES:
            one, two = token_color("--data-1", mode, self.tokens), token_color("--data-2", mode, self.tokens)
            for deficiency in MACHADO:
                de = delta_e76(lab_d65(simulate(one, deficiency)), lab_d65(simulate(two, deficiency)))
                if de < minimum:
                    failures.append(f"{mode}, {deficiency}: ΔE76 {de:.1f} < {minimum}")
                if abs(de - declared[(mode, deficiency)]) > 0.1:
                    failures.append(f"{mode}, {deficiency}: calculado {de:.1f}, docs/design.md dice {declared[(mode, deficiency)]}")
        self.assertEqual(failures, [], "\n".join(failures))

    def test_exceptions_are_approved(self):
        exceptions = parse_exceptions(self.text)
        self.assertTrue(exceptions, "docs/design.md no tiene la tabla «Excepciones».")
        for exc in exceptions:
            self.assertTrue(exc.selectors and exc.prop, exc.key)
            self.assertTrue(exc.approval.startswith("Aprobada"), f"{exc.key} no está aprobada (RF-4).")


# ---------- La página ----------

class PageTokensTests(unittest.TestCase):
    def setUp(self):
        self.text, self.tokens, self.sheet = load()
        self.migrated = root_migrated(self.sheet)

    def test_root_matches_design(self):
        errors = compare_root(self.sheet, self.tokens, ALIAS_VIEJOS)
        if not self.migrated:
            self.assertTrue(errors, f":root ya coincide con docs/design.md, pero no declara {ROOT_MIGRATION_TOKEN}.")
            self.skipTest(f"Pendiente (T6): :root sin migrar, {len(errors)} diferencias con docs/design.md.")
        self.assertEqual(errors, [], "\n".join(errors))

    def test_legacy_marks_name_a_view(self):
        for title, legacy, _ in sections(self.sheet):
            if title.startswith("@legacy"):
                match = LEGACY_MARK.match(title)
                self.assertTrue(match and match.group(1), f"Marca sin vista: /* {title} */")

    def test_css_outside_legacy_uses_tokens(self):
        exceptions = parse_exceptions(self.text)
        if not self.migrated:
            # Estado inicial: todo el CSS es @legacy (ver docstring del módulo). La comprobación
            # sí encuentra los literales de la hoja actual: no es una prueba vacía.
            self.assertTrue(check_rules(self.sheet.rules, exceptions, fixed_selectors(self.sheet)))
            return
        rules = [r for _, legacy, rs in sections(self.sheet) if not legacy for r in rs]
        errors = check_rules(rules, exceptions, fixed_selectors(self.sheet))
        self.assertEqual(errors, [], "\n".join(errors))

    def test_inline_styles_use_tokens(self):
        if not self.migrated:
            return  # Estado inicial: todos los style="…" son @legacy.
        styles = [s for s in inline_styles(PAGE) if not re.search(r"/\*\s*@legacy\b", s)]
        errors = check_inline(styles)
        self.assertEqual(errors, [], "\n".join(errors))

    def test_script_styles_use_tokens(self):
        errors = check_script(script_styles(PAGE))
        self.assertEqual(errors, [], "\n".join(errors))

    def test_pending_legacy_sections(self):
        found = sections(self.sheet)
        self.assertTrue(len(found) > 1 and any(rules for _, _, rules in found), "No se encontró el CSS de la página.")
        pending = [title for title, legacy, rules in found if rules and (legacy or not self.migrated)]
        inline = [s for s in inline_styles(PAGE) if not self.migrated or re.search(r"/\*\s*@legacy\b", s)]
        if pending or inline:
            self.skipTest(f"Pendiente: {len(pending)} secciones de CSS y {len(inline)} style=\"…\" @legacy sin migrar.")


if __name__ == "__main__":
    unittest.main()
