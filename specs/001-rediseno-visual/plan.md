# Plan — Spec 001: Rediseño visual de la página de Hermes
Aprobado por el usuario el 2026-11-17

Spec: `specs/001-rediseno-visual/spec.md` (Estado: aprobada) · Clarificación: `clarify.md` (rondas 1-3).
Modo de la superficie: **Operar**. Fuentes de diseño leídas: `.claude/skills/sdd-design/` (con
`references/` y `frontend-design`), `docs/references/raycast.com/` y `docs/references/linear.app/`.
`docs/design.md` no existe: este plan define el diseño y la tarea T2 lo crea a partir de él.

Las marcas **[APROBAR]** señalan lo que el usuario aprueba al aprobar el plan (lo piden la spec o
CLAUDE.md). Las decisiones que la spec no cubría (P1-P3) ya están tomadas (ver «Decisiones del
usuario sobre P1-P3», al final).

---

## 1. Archivos y responsabilidades

### Archivos que se modifican
| Archivo | Qué cambia | RF |
|---|---|---|
| `hermes/status.py` **(compartido)** | Todo el CSS en línea se reescribe con tokens; se retira `body.stage`; `@font-face` local; metas `theme-color` por modo y `status-bar-style`; colores del manifiesto; ruta `/fonts/…` y `font-src 'self'` en la CSP; retoques mínimos de HTML/JS (glifos, estados de carga, foco de diálogos, nombres de la tabla de renombres). Sin cambios de funciones, rutas (salvo la de la fuente) ni datos. | RF-5 a RF-52 |
| `tests/test_status.py` | Tests de la ruta de la fuente (solo los archivos listados), de la CSP (`font-src 'self'` y el resto igual) y de los colores del manifiesto. | RF-48, RF-41, RF-9 |
| `tests/test_remote.py` | La ruta de la fuente exige sesión por el túnel; lo que se sirve sin sesión no cambia. | RF-48 |
| `hermes/assets/logo.webp` | Logo nuevo, mismo nombre, mismo tamaño (1254×1254). | RF-51, RF-52 |
| `hermes/assets/icon-192.png`, `hermes/assets/icon-512.png` | Iconos nuevos, mismos nombres y tamaños. | RF-51, RF-52 |

No se tocan: `hermes/__main__.py` (no hay piezas nuevas que conectar), `hermes/remote.py` (decisión
P1: sus pantallas no se tocan en esta spec), `hermes/settings.py` (los colores de categoría se guardan igual), `telegram.py`.

### Archivos nuevos **[APROBAR]** (CLAUDE.md: «pregunta antes de crear archivos»)
| # | Archivo | Para qué | RF |
|---|---|---|---|
| N1 | `docs/design.md` | Documento de diseño (fuente de verdad). Lo crea T2 a partir del apartado 4 de este plan. | RF-1 a RF-4, RF-39, RF-49 |
| N2 | `hermes/assets/fonts/atkinson-hyperlegible-next-latin.woff2` | Tipografía propia (descarga con permiso explícito, tarea aparte). | RF-48, RNF-2 |
| N3 | `hermes/assets/fonts/OFL.txt` | Licencia de la fuente: la SIL OFL exige acompañar el archivo con su licencia al redistribuirlo. No se sirve por ninguna ruta. | RNF-2 |
| N4 | `tests/test_design_tokens.py` | Test de tokens (RNF-6), coherencia `docs/design.md` ↔ `:root`, contraste de los pares de tokens y distinción de los colores de datos con daltonismo. | RF-2, RF-8, RF-11, RF-13, RF-27, RF-31, RF-39, RF-49, RNF-6 |
| N5 | `tests/test_page_texts.py` | Test de textos visibles e id/clases contra la lista de referencia y la tabla «antes → después». | RF-32, RF-33, RNF-8 |
| N6 | `tests/data/page_reference.json` | Lista de referencia tomada **antes** de cambiar nada (carpeta `tests/data/` nueva). | RNF-8 |
| N7 | `tests/browser/demo_server.py` | Servidor de la página con datos ficticios en memoria, para checkpoints y mediciones (no lo recoge `unittest discover`: no empieza por `test`). Hasta T6 se usó en 47822 con Hermes parado; desde T7 se usa en 47823 sin parar Hermes (decisión P2, cambio del 2026-11-18). | RNF-4, RNF-7 |
| N8 | `tests/browser/medir.js` | Script que se ejecuta con `browser_evaluate` del MCP de Playwright y devuelve las mediciones de RNF-7 (contraste, 44/32 px, desplazamiento horizontal, tamaños de letra fuera de escala). | RNF-7, RF-24, RF-25, RF-27 |
| N9 | `docs/logo.svg` | Fuente vectorial del logo y de los iconos (de ella salen los tres archivos raster). No se sirve. | RF-51, RF-52 |

### `.gitignore`
No cambia. La fuente no es una tecnología con artefactos, y las capturas del checkpoint
(`specs/*/checkpoint/`) y de las referencias ya están ignoradas. Los raster intermedios del logo
se generan en el directorio temporal de la sesión, no en el repositorio.

---

## 2. Lógica pura separada de la E/S

- **E/S (HTTP):** solo `status.py`, en `do_GET`: una entrada nueva para la fuente, detrás del
  bloque de sesión remota (igual que `/logo.webp`), y una directiva nueva en la CSP.
- **Presentación:** CSS/HTML/JS en línea de `PAGE`. No hay lógica de negocio nueva.
- **Lógica pura nueva, solo en los tests** (no hace falta en producción): parser de CSS y de la
  tabla de tokens de `docs/design.md`, contraste WCAG, simulación de daltonismo, extracción de
  textos e id/clases. Son funciones sin E/S dentro de N4 y N5, probadas con casos conocidos
  (p. ej. contraste negro/blanco = 21:1).
- **Derivación del color de categoría:** regla en CSS (`color-mix`), no en JS; el valor guardado
  no cambia (RF-2, RF-8, RF-39).

---

## 3. Algoritmos (pseudocódigo)

### 3.1 Ruta de la fuente (RF-48)
```
FONTS = ASSETS / "fonts"
FONT_FILES = {"/fonts/atkinson-hyperlegible-next.woff2": "atkinson-hyperlegible-next-latin.woff2"}
CSP = <la actual> + "; font-src 'self'"          # nada más cambia
do_GET:
  ... (Host, manifiesto, PUBLIC_FILES y bloque remoto, sin cambios)
  elif path in FONT_FILES and (FONTS / FONT_FILES[path]).exists():   # clave exacta: sin recorrer carpetas
      send(200, "font/woff2", bytes)
```
`FONT_FILES` **no** entra en `PUBLIC_FILES`: por el túnel, sin sesión aprobada, responde 401 como
el resto. La página de acceso no declara `@font-face` (usa la del sistema).

### 3.2 Test de tokens (RNF-6, RF-39)
```
css = bloque <style> de PAGE ; inline = atributos style="…" del HTML ; js = asignaciones .style.* y setProperty del <script>
tokens = tabla de docs/design.md (nombre, claro, oscuro, escala)
assert nombres y valores de :root (claro) y de @media (prefers-color-scheme: dark) == tokens
para cada declaración fuera de :root:
  color / background / border-color / outline-color / fill / stroke / box-shadow → sin literales (#hex, rgb(), hsl(), nombres);
        solo var(--…), color-mix() de var(--…), transparent, currentColor, inherit
  font-size → solo var(--fs-*)
  margin*, padding*, gap, row-gap, column-gap, inset/top/right/bottom/left de elementos fijos
        → 0, auto, var(--sp-*), o calc()/max()/min() de var(--sp-*) con env(safe-area-inset-*)
  border-radius → 0 o var(--r-*)
  transition / animation → duraciones var(--dur-*), curvas var(--ease-*); prohibido "all" y "ease-in"
excepciones = las de la tabla «Excepciones» de docs/design.md (selector + propiedad) → se aceptan
LEGACY = conjunto de secciones de CSS aún sin migrar (marcadas con /* @legacy <vista> */);
         se vacía lote a lote; la última tarea comprueba LEGACY == ∅
```
En JS se aceptan los tamaños calculados con datos (alto de barras, ancho de progreso, posición del
tooltip y del medidor): son geometría, no espaciado.

### 3.3 Contraste y daltonismo (RF-2, RF-27, RF-49)
```
contraste(a, b) = (L1 + 0.05) / (L2 + 0.05), con luminancia relativa sRGB (WCAG 2.x)
pares = tabla «Contraste» de docs/design.md (color, fondo, mínimo) en claro y en oscuro
assert contraste(par) >= mínimo  (4.5 texto, 3 texto grande / iconos / bordes de control / foco / datos)
para cada modo: para p en (protanopía, deuteranopía, tritanopía):
   simular data-1 y data-2 con las matrices de Machado et al. (2009), severidad 1.0
   assert ΔE76(Lab(sim1), Lab(sim2)) >= 20
```
Las cifras calculadas se copian en `docs/design.md`; la medición en el navegador (3.6) las
comprueba sobre la página pintada.

### 3.4 Textos e id/clases (RNF-8, RF-32, RF-33)
```
extraer(PAGE):
  textos  = nodos de texto del HTML + aria-label/placeholder/title/alt + literales de cadena del <script>
            que contienen letras y no son selectores ni nombres de clase
  ids     = id="…" del HTML + $("…")/getElementById("…") del script
  clases  = class="…" del HTML + className/classList/text(tag, "clase")/querySelector(".clase") del script
T1 guarda extraer(PAGE actual) en tests/data/page_reference.json (antes de cualquier cambio)
test:
  ref, ahora = json, extraer(PAGE)
  para cada (viejo → nuevo) de RENAMES: assert viejo ∉ ahora (en ningún uso) y nuevo ∈ ahora
  assert (ref.textos - ahora.textos) == ∅
  assert (ref.ids ∪ ref.clases_del_script) - RENAMES.viejos ⊆ ahora
  nuevos_textos = ahora.textos - ref.textos → solo si están en ACCESIBLES
        (dentro de .sr-only o de aria-*, lista cerrada en el test)
```

### 3.5 Diálogos: foco y Escape (RF-29)
```
openDialog(d): d._opener = document.activeElement; d.showModal(); enfocar el primer control útil
d.addEventListener("close", () => d._opener?.focus())
```
`showModal()` ya mantiene el foco dentro (el resto de la página queda inerte) y cierra con Escape
(`cancel`); solo falta devolver el foco, y el editor lo hace también al cerrar con ✕.

### 3.6 Medición en el navegador (RNF-7)
`tests/browser/medir.js` devuelve un JSON con cuatro listas (vacías = verde):
```
desborde: document.documentElement.scrollWidth > innerWidth
pequeños: controles visibles (button, a, input, select, summary, [tabindex], label con input)
          con caja < 44×44 si (pointer:coarse) o innerWidth <= 640; alto < 32 si no;
          salvo enlaces dentro de texto y .col (excepción del gráfico, alto >= 44)
contraste: para cada elemento con texto visible: color vs primer fondo opaco de sus ancestros
           (los colores se normalizan pintándolos en un canvas 1×1), umbral 4.5 o 3 si es grande;
           bordes de control, iconos SVG y barras .seg contra su fondo: 3
escala:  font-size calculado fuera de {13,14,16,20,24}
```
Se ejecuta por vista y subpestaña, a 375×812 y 1280×800, en claro y en oscuro
(`browser_emulate_media`), con la consola y las peticiones fallidas revisadas.

---

## 4. Interfaz (base de `docs/design.md`)

### 4.1 Contexto y punto de partida
- **Modo:** Operar. **Plataforma:** web adaptable, sobre todo app instalada en iPhone (375 px,
  táctil, de pie o caminando) y a veces laptop con teclado y ratón (1280 px).
- **Trabajo de la página:** mirar pendientes, marcar hechos y apuntar (tareas, gastos) en segundos.
- **Idea del diseño:** Hermes es el mensajero; su color es el **verdín**, la pátina verde azulada
  del bronce de sus estatuas. Se gasta la audacia en un solo sitio: la tipografía hiperlegible y la
  marca. Todo lo demás, quieto y ordenado por luminosidad.

### 4.2 Principios (5)
1. **Un acento, tres usos.** El verdín marca solo la acción principal, la selección
   (`aria-pressed`, `aria-current`, `checked`, día elegido) y el foco. Nunca títulos, enlaces,
   iconos decorativos, barras de progreso ni «hoy». Se rechaza el dorado por todas partes de hoy.
2. **Jerarquía por luminosidad, no por tamaños.** Tres tintas (`--ink`, `--ink-2`, `--ink-3`) y
   cinco tamaños. Un dato secundario se atenúa, no se encoge por debajo de 13 px.
3. **El estado vive en el glifo.** Urgente, vencida, hecha y pendiente se distinguen por forma
   (triángulo, círculo lleno o hueco, tachado) más color de estado, en columna fija, con el texto
   que ya existe. Las filas no se pintan de color.
4. **Sombra solo en lo que flota.** Tarjetas y secciones: superficie + borde de 1 px, sin sombra.
   Sombra solo en avisos, diálogos, panel de voz, botón de hablar y tooltip.
5. **El pulgar manda.** Toda zona pulsable mide 44×44 px en táctil o a 375 px (32 px de alto con
   ratón); el editor sube como hoja inferior con Guardar siempre a la vista.

### 4.3 Color **[APROBAR]**
Neutros con tinte verde azulado leve (matiz ≈ 195°, el del acento). Contrastes calculados en este
plan (aprox.; `docs/design.md` guarda los medidos).

| Token | Claro | Oscuro | Uso |
|---|---|---|---|
| `--bg` | `#F4F6F6` | `#101416` | Fondo de página |
| `--surface` | `#FFFFFF` | `#171C1F` | Tarjetas, secciones, diálogos, avisos, campos dentro de página |
| `--surface-soft` | `#EAEEEF` | `#20272A` | Pestaña inactiva, chips, pistas de progreso, esqueleto de carga, campos dentro de tarjeta |
| `--line` | `#DCE2E4` | `#2A3236` | Separadores decorativos (no bordes de control) |
| `--line-strong` | `#7F8C91` | `#6A777D` | Bordes de controles (≥ 3:1: 3,5 sobre `--surface` claro; 3,3 sobre `--surface-soft` oscuro) |
| `--ink` | `#142023` | `#E8EEEF` | Texto principal |
| `--ink-2` | `#3D4A4F` | `#AAB6BA` | Texto secundario, iconos |
| `--ink-3` | `#5F6C72` | `#8A979C` | Metadatos, rótulos (≥ 4,6:1 también sobre `--surface-soft`) |
| `--accent` | `#17697A` | `#5CC3D6` | Acción principal, selección, foco (6,3:1 sobre blanco; 8,9:1 sobre `--bg` oscuro) |
| `--accent-ink` | `#FFFFFF` | `#0B1A1E` | Texto e icono sobre acento |
| `--accent-soft` | `color-mix(in oklab, var(--accent) 12%, var(--surface))` | ídem | Fondo de lo seleccionado |
| `--focus` | `var(--accent)` | ídem | Anillo de foco 2 px, separación 2 px |
| `--ok` | `#2D7A2F` | `#6CC36F` | Éxito, «conectado», hecha |
| `--warn` | `#8A5A00` | `#E0B04A` | Aviso (pago próximo, presupuesto cerca) |
| `--danger` | `#B42318` | `#F2836F` | Peligro: urgente, vencida, desconectado, borrar, error |
| `--danger-soft` | `color-mix(in oklab, var(--danger) 10%, var(--surface))` | ídem | Fondo del aviso «Hermes no responde» |
| `--data-1` | `#3A5FCD` | `#7F9BF0` | Serie 1 del gráfico (Claude), liso |
| `--data-2` | `#C26A00` | `#E89A3C` | Serie 2 del gráfico (Modelo local), con rayado diagonal |
| `--scrim` | `rgb(16 20 22 / .5)` | `rgb(0 0 0 / .6)` | Fondo detrás de los diálogos |
| `--shadow-float` | `0 8px 24px rgb(20 32 35 / .16)` | `0 8px 24px rgb(0 0 0 / .5)` | Solo elementos flotantes |
| `--cat-mix` | `65%` | `55%` | Regla de atenuación de categoría |

- **Urgencia:** `--u-alta: var(--danger)`; `--u-media: var(--ink-2)`; `--u-baja: var(--ink-3)`
  (se conservan los nombres de hoy, que usa el HTML del editor).
- **Categorías:** `--c-trabajo` … `--c-otra` se conservan como **colores de entrada por defecto**
  (los que usa la página si el usuario no eligió uno); nunca se pintan tal cual. Regla de la
  variante atenuada (RF-2): `color-mix(in oklab, var(--cat) var(--cat-mix), var(--surface))`, solo
  en el punto de 8 px (`.dot`) o en un borde de 2 px; el texto de la categoría va en `--ink-2`.
  Excepción: el `input type="color"` de Ajustes (ver 4.10).
- **Colores de datos:** azul y ámbar (pareja segura con protanopía y deuteranopía; con tritanopía
  difieren en luminosidad), ≥ 3:1 contra `--surface` en ambos modos (claro 5,7 y 3,9; oscuro 6,4 y
  7,5). Además del color, la serie 2 lleva rayado y orden fijo en la pila (Claude abajo) y la
  leyenda nombra las dos series (RF-43, RF-50).
- **Manifiesto (RF-41):** `theme_color` y `background_color` = `#56646A`, neutro medio con el
  mismo tinte, válido en los dos modos. En la página: dos `<meta name="theme-color">` con
  `media="(prefers-color-scheme: light|dark)"` y valores `--bg` de cada modo (cambian al momento sin
  JS), y `apple-mobile-web-app-status-bar-style` pasa de `black` a `default`.
- `:root { color-scheme: light dark; }` para que los controles nativos (fecha, hora, color,
  casilla) sigan el modo; se quita el `color-scheme:dark` fijo de `.date-row input`.

### 4.4 Tipografía **[APROBAR]**
- **Familia:** **Atkinson Hyperlegible Next** (Braille Institute, 2025), una sola familia para
  todo. Motivo ligado al uso: está diseñada para distinguir caracteres que se confunden (I/l/1,
  O/0, rn/m), justo lo que se lee de pie o caminando: ids `#123`, importes, horas y fechas.
  No es Inter ni la del sistema por inercia.
  - Origen oficial: https://www.brailleinstitute.org/freefont/ y repositorio
    https://github.com/googlefonts/atkinson-hyperlegible-next (también en Google Fonts:
    https://fonts.google.com/specimen/Atkinson+Hyperlegible+Next).
  - Licencia: **SIL Open Font License 1.1** (uso, inclusión y redistribución libres, con la
    licencia al lado: archivo N3).
  - Formato y archivo: **1 woff2 variable**, eje de peso, subconjunto **latín** (cubre español:
    á é í ó ú ü ñ ¿ ¡, «», “”, …, –, €). Se usan los pesos **400, 500 y 600**.
  - Tamaño aproximado: **40-60 KB** el woff2 + ~4 KB la licencia. El tamaño exacto, la URL exacta
    del archivo y su suma se dan al pedir el permiso de descarga (tarea T4); no se descarga nada
    hasta entonces.
  - Comprobación al descargar: que tenga cifras tabulares (`tnum`; se mide en el navegador que
    «111» y «000» ocupen lo mismo con `tabular-nums`) y los glifos del español. Si no cumple, se
    para y se propone la alternativa.
  - Alternativa (solo si la principal no cumple o el usuario la prefiere): **Public Sans**
    (USWDS, OFL 1.1, variable, con `tnum`), https://github.com/uswds/public-sans.
- **Pila de respaldo (RF-36):** `"Atkinson Hyperlegible Next", system-ui, -apple-system,
  "Segoe UI Variable Text", "Segoe UI", sans-serif`, con `font-display: swap`. Los anchos usan
  `min-width:0`, `overflow-wrap:anywhere` y no dependen de la métrica de la fuente. Los glifos ✓ ✕
  🔁 caen a la fuente del sistema.
- **Escala (5 tamaños, RF-10, RF-11):**

| Token | px | Peso | Interlineado | Uso |
|---|---|---|---|---|
| `--fs-xs` | 13 | 400/500 | 1.4 | Metadatos, chips, tags, ejes del gráfico, contadores de subpestaña |
| `--fs-sm` | 14 | 500 | 1.4 | Rótulos de contadores, etiquetas de campo, tablas de Consumo, subtítulos |
| `--fs-md` | 16 | 400/500 | 1.5 | **Cuerpo**: títulos de tarea, párrafos, avisos, mensajes del historial, **todos los campos**, botones, pestañas |
| `--fs-lg` | 20 | 600 | 1.3 | Títulos de sección, de grupo y de diálogo, cifras de Fechas |
| `--fs-xl` | 24 | 600 | 1.25 | Título de vista, cifras de contadores y de Consumo, total de Gastos, estado de En vivo |

- **Cifras tabulares (RF-12):** `font-variant-numeric: tabular-nums` en los cinco contadores,
  los números de día de los dos calendarios, cifras y tablas de Consumo y todo importe
  (Gastos, Pagos, presupuestos).
- Sin mayúsculas forzadas: se quitan los `text-transform: uppercase` de `.dt-group h4` y
  `.dt-badge span` (el texto es el mismo; cambia solo cómo se pinta). Párrafos largos con
  `max-width: 70ch`.

### 4.5 Espaciado, layout y forma **[APROBAR]**
- **Espaciado (base 4):** `--sp-0` 2 · `--sp-1` 4 · `--sp-2` 8 · `--sp-3` 12 · `--sp-4` 16 ·
  `--sp-5` 24 · `--sp-6` 32 · `--sp-7` 48 px. Dentro de un componente 4-12; entre componentes
  16-24; entre bloques de vista 32.
- **Radios (concéntricos):** `--r-sm` 6 (tags, marcas del calendario, chips pequeños) ·
  `--r-md` 10 (botones, campos, filas, días del calendario) · `--r-lg` 14 (tarjetas, secciones,
  diálogos, hoja inferior) · `--r-full` 999 (píldoras, círculos).
- **Bordes:** 1 px; `--line` para separar, `--line-strong` para controles. Sin borde lateral grueso
  de color.
- **Layout:** `--w-page` 1040 px (ancho máximo de cada vista, RF-37) y `--w-col` 720 px (formularios,
  listas de una columna, conversación). A 375 px: márgenes laterales `--sp-4` más zona segura;
  una columna. A ≥ 1024 px: Tareas en rejilla de grupos de 2 columnas, Historial y Consumo en
  `grid2`. Alineación a la izquierda salvo estados vacíos y En vivo (centrados).
- **Cabecera:** fondo `--bg` opaco (se quita el desenfoque), borde inferior `--line`, marca a la
  izquierda, indicador de conexión a la derecha; a ≤ 640 px las pestañas pasan a una segunda fila
  que se desplaza por dentro.
- **Zonas seguras (RF-26):** se conservan los `env(safe-area-inset-*)` de cabecera, avisos,
  diálogos, botón de hablar, panel de voz y margen inferior de `main`.

### 4.6 Movimiento **[APROBAR]**
- Tokens: `--dur-1` 120 ms (color, hover, chevron) · `--dur-2` 200 ms (aviso, tooltip, panel de
  voz) · `--dur-3` 240 ms (diálogos y hoja) · `--ease-out` `cubic-bezier(.23,1,.32,1)` ·
  `--ease-io` `cubic-bezier(.77,0,.175,1)` · `--ease` `ease`. Máximo 300 ms (RF-31).
- Sin animación: cambio de pestaña y subpestaña, filtros, contadores, marcar hecha, filas.
- Aviso: entra con `opacity` + `translateY(8px)` en `--dur-2`, sale ~20 % más rápido. Diálogos:
  `opacity` + `scale(.98)` (hoja inferior: `translateY`). Pulsado: `scale(.97)` en `:active`.
- `hover` solo con `@media (hover:hover) and (pointer:fine)`. Nunca `transition: all` ni `ease-in`.
- Medidor de nivel de En vivo: sin transición (se actualiza 5 veces por segundo).
- **Reducir movimiento (RF-30):** se quitan desplazamientos y escalas en toda la página; quedan
  cambios de opacidad y color. Incluye panel de voz, aviso, diálogos, ondas, anillos y «respirar»
  de En vivo, pulso y giro del botón de hablar.

### 4.7 Componentes del marco y sus estados (RF-14 a RF-18, RF-38)
| Componente | Reposo | Encima (ratón) | Pulsado | Foco | Desactivado | En curso / seleccionado |
|---|---|---|---|---|---|---|
| Botón principal | `--accent` + `--accent-ink`, 600, `--r-md`, alto 44 (32-36 con ratón) | acento 8 % más oscuro (`color-mix`) | `scale(.97)` | anillo `--focus` 2 px, separación 2 px | `--surface-soft` + `--ink-3`, sin sombra, `cursor:default` | `aria-busy`: texto igual, icono de espera a la izquierda |
| Botón secundario (`.ghost`) | `--surface` + borde `--line-strong` + `--ink` | fondo `--surface-soft` | `scale(.97)` | ídem | ídem | — |
| Botón de peligro (`.danger`) | como secundario, texto `--danger` | borde `--danger` | ídem | ídem | ídem | — |
| Botón de icono (`.icon-btn`, ✕, ‹ ›) | transparente, icono `--ink-2`, zona 44×44 | fondo `--surface-soft` | ídem | ídem | ídem | — |
| Pestañas | `--ink-2`, 500 | `--ink` | — | anillo | — | activa: `--ink`, 600 y **subrayado de 2 px `--accent`** (más que color) |
| Subpestañas | píldora `--surface` + borde `--line` | borde `--line-strong` | — | anillo | — | activa: fondo `--accent-soft`, borde `--accent`, 600 |
| Indicador de conexión | punto 8 px `--ink-3` + texto | — | — | — | — | conectado: punto `--ok`; desconectado: punto `--danger` hueco (forma distinta) |
| Campos | `--surface` (o `--surface-soft` dentro de tarjeta), borde `--line-strong`, 16 px, alto 44 | — | — | borde `--accent` + anillo | opacidad .5 + `--surface-soft` | error: borde `--danger` y el texto de error que ya existe |
| Aviso emergente | `--surface` + borde `--line-strong` + `--shadow-float`, «Deshacer» en `--accent` 600 | — | — | anillo | — | entra/sale (4.6) |
| «Hermes no responde» | franja en flujo al inicio de `main`: `--danger-soft`, icono ⚠ en SVG `--danger`, texto `--ink` | — | — | — | — | — |
| Diálogos | `--surface`, `--r-lg`, `--shadow-float`, fondo `--scrim` | — | — | foco dentro (RF-29) | — | — |
| Botón de hablar | círculo 60 px `--accent` + `--accent-ink`, `--shadow-float` | — | `scale(.94)` | anillo `--ink` | — | grabando: `--danger` + icono ■ y pulso; pensando: icono de espera girando; hablando: icono ■ |
| Panel de voz | `--surface` + borde + `--shadow-float`, oído en `--ink-3` 13 px, respuesta 16 px | — | — | — | — | error: texto `--danger` |

- **Avisos y acción principal (RF-16):** el aviso va abajo, centrado, por encima del botón de
  hablar (clase `can-speak`, como hoy) y nunca dentro del área de la acción principal de la vista
  (todas están arriba del contenido, salvo En vivo y Ajustes; en esas dos la acción está en el
  flujo y el aviso se separa con un margen inferior reservado en `main`). Con el teclado virtual
  abierto, iOS deja el aviso fijo detrás del teclado: no tapa el campo enfocado.
- **Diálogos a 375×812 (RF-17):** el editor es hoja inferior (como hoy) con la fila de acciones
  `position: sticky; bottom: 0` dentro del diálogo, así Guardar se ve sin desplazar y sigue
  alcanzable con el teclado abierto. Confirmación y foto: acciones al pie, alto máximo con
  `100dvh`, imagen con `max-height` para que «Cerrar» se vea siempre.

### 4.8 Acción principal de cada vista **[APROBAR]** (Definiciones, RF-16)
| Vista | Acción principal propuesta |
|---|---|
| Tareas | La caja de escribir/hablar: campo, «Enviar» y botón de hablar (fijada por la spec) |
| Apuntes | El formulario de crear/agregar de la subpestaña activa (campo + su botón principal: «+ Crear lista», «+ Crear hábito», «Guardar», «+ Agregar», «Agregar», «+ Agregar pago», «+ Guardar»); en **Gastos**, que no tiene formulario, la navegación de mes (‹ ›) |
| Consumo | «Ver como tabla» (el único control de la vista además de las columnas del gráfico) |
| Historial | El buscador |
| En vivo | El botón del micrófono («Dejar de escuchar» / su estado contrario) |
| Ajustes | «Guardar cambios» (barra de Guardar) |
| Diálogos | Guardar (editor), confirmar (confirmación), Cerrar (foto de recibo) — fijadas por la spec |

### 4.9 Vistas
- **Tareas (RF-19 a RF-23, RF-35):**
  - Contadores: 5 botones `--surface` con borde `--line`; cifra `--fs-xl` tabular; rótulo
    `--fs-sm` `--ink-3`; seleccionado: borde 2 px `--accent` + fondo `--accent-soft`; «Vencidas»
    con valor > 0: cifra en `--danger` 600. A 375 px: rejilla 2 columnas, el quinto a lo ancho.
  - Lista/Calendario: control segmentado `--surface-soft`; activo `--surface` + 600.
  - Filtros: fila que se desplaza por dentro a 375 px; punto de categoría atenuado; activo como
    subpestaña activa.
  - Tarjeta de tarea (fila de 44 px mínimo): columna fija de glifo de urgencia (alta: triángulo
    10 px `--danger`; normal: círculo lleno 8 px `--ink-2`; baja: círculo hueco 8 px `--ink-3`;
    sustituye la barra lateral de 4 px) · casilla (círculo 22 px, zona 44) · título 16/500 cortado
    a 2 líneas con puntos suspensivos (`-webkit-line-clamp: 2`), completo en el editor · metadatos
    13 px `--ink-3`. Urgente: tag «Urgente» en `--danger` 600. Vencida: «Vencida · …» en
    `--danger` 600. Hecha: casilla llena `--accent` con ✓, título tachado `--ink-3`.
  - Calendario: celdas `--r-md`, número tabular; hoy: número en círculo `--ink` con texto `--bg`
    (neutro invertido); elegido: borde `--accent` + `--accent-soft`; marcas urgentes/vencidas en
    `--danger`. A 375 px las celdas miden ≥ 44×48.
  - Carga (RF-21): se mantiene «Cargando…» visible; debajo, esqueleto quieto (3 filas
    `--surface-soft`, sin animación); `aria-busy="true"` en la vista y un anuncio `.sr-only`
    («Cargando las tareas»). Vacío (RF-22): el `.empty-state` de hoy, centrado, título 16/600
    `--ink` y texto 14 `--ink-2`. Error (RF-23): la franja «Hermes no responde».
- **Apuntes (RF-42, RF-47):** subpestañas como 4.7 (fila con desplazamiento interno a 375 px);
  aviso de silencio con `--accent-soft` + borde `--accent` (es una selección activa del usuario);
  formularios de una columna a 375 px con campos de 44; cada subpestaña con su tarjeta `--surface`.
  Hábitos: botón de hoy 46 px (casilla grande), semana de 7 días con zona ≥ 44 (se quitan huecos
  y se reduce el relleno de la tarjeta para que quepan a 375 px), racha en `--ink` 600.
  Fechas: calendario igual que el de Tareas; distintivo de día `--surface-soft`; hoy en neutro
  invertido; próximas en `--ink` 600. Gastos: total `--fs-xl` tabular; barras de presupuesto
  `--ink-3`, cerca `--warn`, pasado `--danger` + 600; miniatura 48 px con zona 44. Pagos:
  próximos `--warn`, vencidos `--danger` (borde 2 px y texto). Lecturas: enlace largo cortado con
  `overflow-wrap:anywhere`. Carga nueva: esqueleto + `.sr-only` + `aria-busy`.
- **Consumo (RF-43, RF-50):** 4 cifras `--fs-xl` tabulares; gráfico de 14 columnas sin
  desplazamiento; cada `.col` ocupa todo el alto (≥ 44 px, hoy 200) y su franja entera es la zona
  pulsable/enfocable; barras `--data-1` (lisa) y `--data-2` (rayado diagonal con
  `repeating-linear-gradient` de `--data-2` y `--surface`), separadas 2 px; leyenda con muestra
  (también rayada) y nombre en texto; tooltip `--surface` + `--shadow-float`; ejes 13 px `--ink-3`
  (a 375 px se oculta una etiqueta de cada dos, como hoy). Tablas 14 px tabulares, desplazamiento
  interno. Carga nueva: esqueleto + `.sr-only` + `aria-busy`.
- **Historial (RF-44):** buscador de 44 px; burbujas: tuyas `--surface-soft`, de Hermes `--surface`
  + borde `--line`, 16 px, radio `--r-lg` con la esquina del lado del emisor `--r-sm`; separador de
  día 13 px `--ink-3`; escuchas por voz con resultado `--ok` / `--danger` y chips de tiempos 13 px
  tabulares.
- **En vivo (RF-45, RF-47):** sin tema negro y dorado ni degradado radial; fondo `--bg`.
  Indicador: anillos de 1,5 px en `--accent` con opacidad según el estado y el nivel, sin halos ni
  resplandores; ondas solo en escuchando/grabando/pensando/hablando; disco `--surface` con borde
  `--line-strong` y el logo; en pausa, logo en gris y atenuado (como hoy) y anillos en
  `--line-strong`. Mensaje de estado `--fs-xl` 600 `--ink` (el texto de estado ya nombra el
  estado: más que color) y pista `--ink-2`. Botón del micrófono: secundario; con `aria-pressed`
  activo, principal (acento). Medidor: pista `--surface-soft`, nivel `--ink-3`, voz `--ok`,
  umbral `--ink`. Carga nueva: esqueleto del disco + `.sr-only` + `aria-busy`.
- **Ajustes (RF-46):** grupos `--surface` con título `--fs-lg`; filas etiqueta/control (una
  columna a ≤ 640 px); interruptores nativos con `accent-color: var(--accent)` y zona 44; chips de
  categoría con el selector de color nativo (excepción) y ✕ con zona 44; aviso de reinicio como
  el de silencio; dispositivos en filas con su botón secundario; barra de Guardar al pie del
  formulario.

### 4.10 Excepciones previstas **[APROBAR]** (se registran en `docs/design.md`, RF-4)
| # | Dónde | Qué regla rompe | Motivo |
|---|---|---|---|
| E1 | Columnas del gráfico de Consumo (`.col`) | Ancho de 44 px (RF-25) | 14 días sin desplazamiento a 375 px dejan ~16 px por columna; la zona pulsable ocupa todo el alto (≥ 44 px) y toda la franja (fijada por la spec, RF-43) |
| E2 | Selector de color de categoría en Ajustes (`.chip-color`) | Solo variantes atenuadas (RF-8) | Muestra el color guardado tal cual, sin vista previa: es lo que el usuario elige (fijada por la spec) |
| E3 | Indicador de En vivo (ondas, «respirar») | Animación > 300 ms, en bucle con keyframes | Comunica el estado de la voz mientras dura; ciclos de 1,5 a 4,2 s, solo `transform` y `opacity`; con reducir movimiento, sin ondas ni escala |
| E4 | Botón de hablar grabando / pensando | Pulso en bucle (1,2 s) y giro (1 s, `linear`) | Indican grabación y espera; con reducir movimiento, sin pulso y el icono de espera quieto con opacidad |
| E5 | Icono de la app y logo | Acento en más del ~20 % de la superficie | El icono es la marca: fondo de color de marca a sangre (iOS rellena de negro lo transparente) |
| E6 | Archivos de logo e iconos | Su tono `#1F7E90` no es un token CSS | Un único archivo debe verse en claro y en oscuro: es el tono medio del acento (4,7:1 sobre blanco y 3,6:1 sobre `--surface` oscuro) |

Si al implementar aparece otra, el implementer para y se aprueba una a una (RF-4).

### 4.11 Anti-patrones del proyecto (además de la lista de la skill)
- Acento en estados que no son selección (hoy, próximos, progreso, títulos al pasar el ratón).
- Color de categoría como fondo, borde o texto de un control, o en el foco.
- Sombra en tarjetas o secciones que no flotan; desenfoque de cabecera.
- Texto de menos de 16 px en campos (Safari acerca la página).
- Literales de color, tamaño, espacio, radio o tiempo fuera de `:root` (lo vigila N4).
- Textos visibles nuevos (salvo las excepciones de RF-32).
- Textos heredados con «·» o emojis: se conservan tal cual (RF-32); no son modelo para textos nuevos.

### 4.12 Referencias: qué se adopta y qué se descarta (RF-3)
| Referencia | Se adopta (principio) | Se descarta y por qué |
|---|---|---|
| Raycast | Jerarquía por luminosidad en 3 pasos de tinta; borde de 1 px en vez de sombra en superficies; anillo de foco de 2 px; peso 500 para etiquetas; movimiento solo en `transform`/`opacity` de 0,1-0,3 s; acento escaso, nunca decorativo | «Acento fuera de los controles»: la spec define que el acento marca la acción principal. Solo oscuro, brillo superior en bordes (no funciona en claro), barra con desenfoque, sombras de 4 capas, escala de 9 tamaños, cuerpo de 14 px, teclas dibujadas (Hermes es táctil), grises puros, 224 px entre secciones, su rojo y su tipografía |
| Linear | El estado vive en un glifo de forma distinta en columna fija, con texto neutro; sombra solo en lo que flota; radios concéntricos 14 > 10 > 6; grupos con cabecera y contador; hoja inferior con filas a ancho completo para el pulgar; transiciones de color de 100-160 ms | Botón principal neutro (la spec pone el acento en la acción principal); cuerpo de 12-15 px y objetivos de 32-40 px a 375 px (Hermes: 16 px y 44 px); pesos 510/590; solo oscuro; su índigo, Inter y Berkeley Mono; titulares de 48-72 px |

### 4.13 Logo e iconos (RF-51, RF-52)
- **Marca:** monograma «H» de trazo grueso cuyo travesaño es una diagonal ascendente (el mensaje
  que sale), en `#F4F6F6` sobre el tono de marca `#1F7E90` (E6). Logo: disco con la marca, fondo
  transparente fuera del disco (1254×1254, `logo.webp`). Iconos 192 y 512: cuadrado a sangre del
  tono de marca con la marca dentro del 60 % central (no la recortan las esquinas de iOS).
  Trazo ≥ 1/6 del lado, para que se lea a 16 y 32 px (la pestaña usa `icon-192.png` reducido,
  como hoy). La cabecera cambia el punto `.brand-dot` por la misma marca en SVG en línea de 20 px.
- **Método, sin dependencias nuevas:** la marca se dibuja a mano en SVG (`docs/logo.svg`). Se
  rasteriza en el navegador del MCP de Playwright: se carga el SVG como `data:` en un `<canvas>`
  del tamaño exacto, y `canvas.toDataURL("image/png" | "image/webp")` devuelve el archivo en base64
  por `browser_evaluate`; se escribe con `base64` de la biblioteca estándar. Mismos nombres,
  rutas y tamaños; el icono del iPhone sigue llegando en línea (`touch_icon()`), sin cambios.
- **Checkpoint:** 192, 512 y logo; icono a 16 y 32 px sobre claro y oscuro; vista con esquinas
  redondeadas de iOS (máscara de radio 22 %); logo dentro de En vivo en claro, oscuro y pausa.

---

## 5. Decisiones (con la alternativa descartada)
| Decisión | Alternativa descartada | Por qué |
|---|---|---|
| Tokens como propiedades CSS en `:root` + `@media (prefers-color-scheme: dark)`, contrastados por test contra la tabla de `docs/design.md` | Un módulo Python con los tokens que genere el CSS | Es el mecanismo nativo, no añade piezas; el test mantiene alineados documento y código |
| Retirar `body.stage` y sus reglas, y reescribir cada sección de CSS (no añadir capas que pisen a otras) | Mantener el CSS y añadir reglas nuevas encima | Evita cascadas que se anulan y que `status.py` crezca; el test de tokens solo es fiable sin restos |
| Migración por secciones con marca `/* @legacy <vista> */` en el test de tokens | Test de tokens completo desde el principio | Cada lote debe quedar en verde; la última tarea exige que no quede ninguna |
| `theme-color` con dos metas `media` | Cambiarlo por JS al detectar el modo | Sin JS, cambia al momento y la barra acierta al abrir la app |
| Fuente por ruta `/fonts/` con diccionario cerrado, tras la sesión | Fuente en `data:` dentro de la página | `data:` engordaría cada carga de `PAGE` y exigiría `font-src data:`; la spec pide ruta propia y solo propio origen |
| Una sola fuente variable, subconjunto latín | Tres archivos estáticos (400/500/600) | Un archivo, menos peso total y una sola entrada en la ruta |
| Subconjunto latín ya preparado por el origen oficial | Recortar la fuente con fontTools | fontTools sería una dependencia nueva |
| Glifos de urgencia con CSS (`clip-path`, bordes) | Iconos SVG creados por JS en cada fila | Sin cambios de DOM ni de JS; más ligero |
| Esqueleto de carga quieto | Esqueleto con brillo animado | Operar: poco movimiento y sin excepción nueva |
| Logo rasterizado con el navegador del MCP | Instalar Pillow, cairosvg o Inkscape | Sin dependencias nuevas (constitución, 1) |
| Medición con un script en `browser_evaluate` del MCP | Playwright para Python dentro de `unittest` | Sería una dependencia nueva y abriría un navegador en los tests (ver riesgos) |
| Contraste y daltonismo también calculados en Python sobre los tokens | Solo medirlo en el navegador | Queda en verde/rojo en cada ejecución de tests, sin navegador |

---

## 6. Tabla «antes → después» de renombres (RF-33, RNF-8)
| Antes | Después | Usos que cambian |
|---|---|---|
| clase `stage` en `<body>` | (se elimina) | Solo CSS del tema retirado; el script no la usa |
| `.brand-dot` (span) | `.brand-mark` (SVG en línea) | Solo HTML y CSS de la cabecera |
| `--s-claude` | `--data-1` | Leyenda (atributo `style`) y tooltip del gráfico en el script (`"var(--s-" + key + ")"` pasa a un mapa `{claude: "var(--data-1)", local: "var(--data-2)"}`) |
| `--s-local` | `--data-2` | Ídem |
| `--card`, `--muted`, `--faint`, `--soft`, `--bar`, `--shadow`, `--warn`¹ | `--surface`, `--ink-2`, `--ink-3`, `--surface-soft`, `--surface-soft`, `--shadow-float` (solo flotantes), `--danger`/`--warn` según el caso | Solo CSS (y los fallbacks `var(--muted, #a19f96)` de `.pw-eye`) |

¹ `--warn` se conserva como nombre pero cambia de rol: hoy pinta errores y vencidos (pasan a
`--danger`) y pasa a ser el color de estado «aviso». El test comprueba que los nombres viejos ya
no aparecen en ningún uso. Se conservan: ids, clases que usa el script, `data-*`, `--u-alta`,
`--u-media`, `--u-baja`, `--c-*` y `--cat`.

---

## 7. Estrategia de tests
Comando (CLAUDE.md): `~/.hermes/venv/Scripts/python.exe -m unittest discover -s tests`
(se recomienda añadir `-W error::SyntaxWarning`). Sin red ni datos reales.

| Test | Qué comprueba | RF |
|---|---|---|
| `tests/test_page_texts.py` (N5) | Textos visibles, ids y clases del script frente a la referencia; renombres; textos nuevos solo accesibles | RF-32, RF-33, RNF-8 |
| `tests/test_design_tokens.py` (N4) | Tokens de `:root` = tabla de `docs/design.md`; estilo solo con tokens (salvo excepciones y `@legacy`); escala de 5 tamaños; sin `transition: all`/`ease-in`; duraciones ≤ 300 ms salvo E3/E4; contraste de pares; colores de datos con daltonismo | RF-2, RF-8, RF-11, RF-13, RF-27, RF-31, RF-39, RF-49, RNF-6 |
| `tests/test_status.py` | Ruta de fuente: 200 `font/woff2` con firma `wOF2`; 404 para `/fonts/OFL.txt`, `/fonts/../logo.webp`, `/fonts/icon-192.png`, `/fonts/`; 403 con Host ajeno; CSP con `font-src 'self'` y el resto igual; manifiesto sin `#0a0c0f`; dos metas `theme-color`; `PAGE` sin `class="stage"` | RF-9, RF-41, RF-48 |
| `tests/test_remote.py` | Sin sesión: la fuente da 401; `PUBLIC_FILES` igual que hoy; la pantalla de acceso sin `@font-face` | RF-48 |
| Navegador (MCP Playwright, `medir.js`) | Todas las vistas y subpestañas a 375×812 y 1280×800, claro y oscuro: sin desborde, 44/32 px, contraste, escala; consola y peticiones fallidas; texto al 200 %; sin la fuente (servidor de demostración sin el archivo); teclado (Tab, Escape, foco devuelto); reducir movimiento | RF-5 a RF-7, RF-24, RF-25, RF-27 a RF-30, RF-36, RF-37, RF-40, RNF-4, RNF-7 |
| Manual del usuario (iPhone) | Zonas seguras, barra de estado al abrir, color de tema al cambiar de modo, icono tras reinstalar | RF-26, RF-41, RF-52 |

---

## 8. Constitución
Sin violaciones, con estas notas:
- **Principio 1 (dependencias):** no se añaden bibliotecas. La fuente es un recurso nuevo que se
  descarga solo con permiso explícito (nombre, origen, licencia y tamaño), en su propia tarea.
- **Principio 4 (verificación en 127.0.0.1:47822):** las capturas y mediciones deben usar datos
  ficticios, y la copia real tiene datos reales. Decisión P2: la verificación se hace en 47822
  con el servidor de demostración y Hermes parado durante ella, y Hermes se reinicia después.
  Cambio del 2026-11-18 (T7-T23): demo en 47823 sin parar Hermes y comprobación sin capturas en
  47822 al cerrar cada lote; desviación explícita del principio 4, aceptada por el usuario para
  esta spec (ver «Decisiones del usuario sobre P1-P3»).
- **Principio 3 (interruptor en Ajustes):** el rediseño no es una función nueva; no lleva
  interruptor.
- **Principio 5:** la página sigue solo en 127.0.0.1; la ruta de la fuente exige sesión por el
  túnel; la CSP solo suma `font-src 'self'`.

---

## 9. Propuesta de lotes (sin escribir las tareas)
Estimación: **23 tareas en 3 lotes**. Todas tocan `hermes/status.py` (compartido), así que son
secuenciales (`Paralelo: no`), salvo quizá T1/T3 (solo tests).

**Lote A — Base, marco y Tareas (10).** T1 referencia de textos e id/clases + su test (antes de
tocar nada) · T2 `docs/design.md` · T3 test de tokens con todo `@legacy` · T4 descarga de la
fuente (con permiso) + ruta + CSP + tests · T5 servidor de demostración y `medir.js` · T6 tokens,
modos, `@font-face`, metas, manifiesto y retiro de `stage` · T7 marco: cabecera, pestañas,
subpestañas, botones, campos y avisos (**checkpoint visual**) · T8 diálogos con foco/Escape · T9
botón de hablar y panel de voz · T10 vista Tareas con Calendario y estados.
**Lote B — Apuntes (7).** T11 marco de Apuntes + Listas (**checkpoint visual**) · T12 Hábitos ·
T13 Notas y Seguimientos · T14 Fechas · T15 Gastos y foto · T16 Pagos · T17 Lecturas.
**Lote C — Demás vistas, logo y cierre (6).** T18 Consumo (**checkpoint visual**) · T19
Historial (**checkpoint visual**) · T20 En vivo (**checkpoint visual**) · T21 Ajustes
(**checkpoint visual**) · T22 logo, iconos y marca de cabecera (**checkpoint visual** de logo e
iconos) · T23 cierre: `@legacy` vacío, medición completa, 200 %, sin fuente, excepciones al día
en `docs/design.md`.

Checkpoints visuales (decisión P3): 7, en T7, T11, T18, T19, T20, T21 y T22.

---

## 10. Riesgos y mitigación
| Riesgo | Mitigación |
|---|---|
| `status.py` (~3500 líneas, ~660 de CSS) crece o mezcla estilos viejos y nuevos | Reescribir cada sección en su sitio y borrar lo viejo; el test de tokens con `@legacy` muestra lo que falta; una tarea por vista |
| Conflictos al tocar todos el mismo archivo | Todo en serie; cada tarea con su sección de CSS delimitada |
| La verificación de navegador no es un test de `unittest` | `medir.js` versionado, misma ejecución en cada tarea de interfaz y en el cierre; el reviewer lo repite. Playwright para Python queda descartado (dependencia nueva) |
| El MCP no emula puntero táctil | La regla de 44 px se aplica también por ancho (`max-width: 640px`), que sí se emula |
| La fuente no tiene `tnum` o pesa más de lo previsto | Se comprueba al descargar; si falla, se para y se propone Public Sans |
| `Cache-Control: no-store` hace que la fuente se descargue en cada carga | Se acepta (40-60 KB, local); cambiar la caché sería tocar la política de cabeceras, fuera de alcance. Se anota como deuda |
| iOS conserva el icono viejo y no siempre repinta la barra de estado | Lo admite la spec: se comprueba tras reinstalar y al abrir la app |
| Romper un texto o un id que usa el script | T1 fija la referencia antes de tocar nada; N5 falla ante cualquier cambio no registrado |
| `color-mix` en Safari antiguo | Ya se usa hoy (Safari ≥ 16.2); sin cambio de soporte |
| Datos reales en capturas | Servidor de demostración con datos ficticios en memoria, en 47823 sin parar Hermes (decisión P2, cambio del 2026-11-18); en 47822 solo la comprobación de cierre de lote, sin capturas ni datos |
| Parar y reiniciar Hermes lo deja sin arrancar (pasó en T5 y T6) | Desde T7 Hermes no se para nunca: la demo va en 47823 (cambio P2 del 2026-11-18) |
| `docs/design.md` pasa de ~120 líneas por las tablas de contraste que pide RF-2 | Se acepta: lo exige la spec; se mantiene sin prosa de relleno |

---

## 11. Cobertura de RF
| Parte | RF |
|---|---|
| `docs/design.md` (4.1-4.13) | RF-1, RF-2, RF-3, RF-4, RF-39, RF-49 |
| Tokens, modos, manifiesto | RF-5, RF-6, RF-7, RF-8, RF-9, RF-41 |
| Tipografía y escala | RF-10, RF-11, RF-12, RF-36, RF-48, RNF-1, RNF-2 |
| Espaciado, radios, layout | RF-13, RF-24, RF-26, RF-37, RF-40 |
| Marco (4.7) | RF-14, RF-15, RF-16, RF-17, RF-18, RF-38 |
| Tareas | RF-19, RF-20, RF-21, RF-22, RF-23, RF-35 |
| Demás vistas | RF-34, RF-42, RF-43, RF-44, RF-45, RF-46, RF-47, RF-50 |
| Táctil y accesibilidad | RF-25, RF-27, RF-28, RF-29, RF-30, RF-31 |
| Sin cambios de comportamiento | RF-32, RF-33, RNF-8 |
| Logo e iconos | RF-51, RF-52 |
| Tests y verificación | RNF-3, RNF-4, RNF-5, RNF-6, RNF-7 |

---

## Decisiones del usuario sobre P1-P3 (2026-11-17)
- **P1 — Pantallas de acceso y de espera del acceso remoto** (`remote.py`, siguen en negro y
  dorado). **Decidido: (a).** No se tocan en esta spec; quedan como deuda que se anota en
  MEMORY.md al cierre, para una spec propia.
- **P2 — Dónde se verifica con datos ficticios.** **Decidido: (a).** Servidor de demostración en
  47822 con datos ficticios en una base temporal. Durante cada verificación se para Hermes y
  después se reinicia; el coordinador avisa al usuario antes de cada parada.
  - **Cambio (2026-11-18), para T7-T23:** la demo de verificación corre en 127.0.0.1:47823
    (`tests/browser/demo_server.py --puerto 47823`), con datos ficticios en base temporal, y el
    Hermes real del usuario no se para nunca. Al cerrar cada lote (A tras T10, B tras T17, C/fin en
    T23) se comprueba http://127.0.0.1:47822 (el Hermes real) sin capturas y sin leer ni describir
    datos: solo que carga, consola sin errores, peticiones fallidas y sin scroll horizontal,
    informando solo cantidades. **Por qué:** parar y reiniciar Hermes falló dos veces (en T5 no
    pudo volver a arrancar por un bloqueo de Windows; en T6 la tarea programada «Hermes» quedó en
    «En ejecución» sin escuchar en 47822, código 0x800710E0, y hubo que reiniciarlo a mano).
    **Desviación explícita**, aceptada por el usuario para esta spec, de «verificar en
    http://127.0.0.1:47822» (CLAUDE.md, sección Verificación, y constitución, principio 4).
- **P3 — Cuántos checkpoints visuales.** **Decidido: (a).** 7 checkpoints: uno por vista (marco y
  Tareas en T7, Apuntes en T11, Consumo en T18, Historial en T19, En vivo en T20, Ajustes en T21)
  y otro de logo e iconos (T22). La spec manda sobre la regla de un solo checkpoint.
