# Diseño

Estado: aprobado · Aprobado por el usuario el 2026-11-18 · Última revisión: 2026-11-18
Origen: apartado 4 de `specs/001-rediseno-visual/plan.md` (aprobado el 2026-11-17).

Las tablas con columna `Token` las lee `tests/test_design_tokens.py`: una fila por token, valor
entre comillas invertidas, `—` en «Oscuro» = mismo valor en los dos modos (solo en `:root`).

## Contexto
- **Modo:** Operar.
- **Plataforma:** web adaptable. Sobre todo app instalada en iPhone (375 px, táctil, de pie o
  caminando); a veces laptop con teclado y ratón (1280 px).
- **Trabajo de la página:** mirar pendientes, marcar hechos y apuntar (tareas, gastos) en segundos,
  varias veces al día.
- **Idea:** Hermes es el mensajero; su color es el **verdín**, la pátina verde azulada del bronce
  de sus estatuas. La audacia se gasta en un solo sitio (tipografía hiperlegible y marca); el resto,
  quieto y ordenado por luminosidad.
- **Tema retirado (RF-9):** el tema negro y dorado de «En vivo» (`body.stage`, `--gold`) y el negro
  fijo `#0a0c0f` del manifiesto se retiran de toda la página, también de En vivo.

## Principios
1. **Un acento, tres usos.** El verdín marca solo la acción principal, la selección
   (`aria-pressed`, `aria-current`, `checked`, día elegido) y el foco. Nunca títulos, enlaces,
   iconos decorativos, barras de progreso ni «hoy». Se rechaza el dorado repartido de hoy.
2. **Jerarquía por luminosidad, no por tamaños.** Tres tintas (`--ink`, `--ink-2`, `--ink-3`) y
   cinco tamaños. Un dato secundario se atenúa; no baja de 13 px.
3. **El estado vive en el glifo.** Urgente, vencida, hecha y pendiente se distinguen por forma
   (triángulo, círculo lleno o hueco, tachado) más color de estado, en columna fija, con el texto
   que ya existe. Las filas no se pintan de color.
4. **Sombra solo en lo que flota.** Tarjetas y secciones: superficie + borde de 1 px, sin sombra.
   Sombra solo en aviso, diálogos, panel de voz, botón de hablar y tooltip.
5. **El pulgar manda.** Zona pulsable de 44×44 px en táctil o a ≤ 640 px; 32 px de alto con ratón.
   El editor sube como hoja inferior con Guardar siempre a la vista.

## Color
Neutros con tinte verde azulado leve (matiz ≈ 195°, el del acento). Un único acento.

| Token | Claro | Oscuro | Escala | Uso |
|---|---|---|---|---|
| `--bg` | `#F4F6F6` | `#101416` | color | Fondo de página |
| `--surface` | `#FFFFFF` | `#171C1F` | color | Tarjetas, secciones, diálogos, avisos, campos en página |
| `--surface-soft` | `#EAEEEF` | `#20272A` | color | Pestaña inactiva, chips, pistas de progreso, esqueleto, campos dentro de tarjeta |
| `--line` | `#DCE2E4` | `#2A3236` | color | Separadores decorativos (no bordes de control) |
| `--line-strong` | `#7C898E` | `#6A777D` | color | Bordes de controles (≥ 3:1; ver Contraste) |
| `--ink` | `#142023` | `#E8EEEF` | color | Texto principal |
| `--ink-2` | `#3D4A4F` | `#AAB6BA` | color | Texto secundario, iconos |
| `--ink-3` | `#5F6C72` | `#8A979C` | color | Metadatos, rótulos |
| `--accent` | `#17697A` | `#5CC3D6` | color | Acción principal, selección, foco |
| `--accent-ink` | `#FFFFFF` | `#0B1A1E` | color | Texto e icono sobre acento |
| `--accent-soft` | `color-mix(in oklab, var(--accent) 12%, var(--surface))` | — | color | Fondo de lo seleccionado (≈ `#E4ECEE` / `#202D32`) |
| `--focus` | `var(--accent)` | — | color | Anillo de foco 2 px, separación 2 px |
| `--ok` | `#2D7A2F` | `#6CC36F` | color | Estado éxito: «conectado», hecha |
| `--warn` | `#8A5A00` | `#E0B04A` | color | Estado aviso: pago próximo, presupuesto cerca |
| `--danger` | `#B42318` | `#F2836F` | color | Estado peligro: urgente, vencida, desconectado, borrar, error |
| `--danger-soft` | `color-mix(in oklab, var(--danger) 10%, var(--surface))` | — | color | Fondo de «Hermes no responde» (≈ `#FBEAE7` / `#2A2627`) |
| `--data-1` | `#3A5FCD` | `#7F9BF0` | color | Serie 1 del gráfico (Claude), lisa. Solo en gráficos, leyenda y tooltip |
| `--data-2` | `#C26A00` | `#E89A3C` | color | Serie 2 (Modelo local), con rayado diagonal. Solo en gráficos, leyenda y tooltip |
| `--scrim` | `rgb(16 20 22 / .5)` | `rgb(0 0 0 / .6)` | color | Fondo detrás de los diálogos |
| `--shadow-float` | `0 8px 24px rgb(20 32 35 / .16)` | `0 8px 24px rgb(0 0 0 / .5)` | sombra | Solo elementos flotantes |
| `--cat-mix` | `65%` | `55%` | mezcla | Proporción del color de categoría en su variante atenuada |
| `--u-alta` | `var(--danger)` | — | color | Urgencia Urgente |
| `--u-media` | `var(--ink-2)` | — | color | Urgencia Normal |
| `--u-baja` | `var(--ink-3)` | — | color | Urgencia Baja (más tenue que Normal) |
| `--c-trabajo` | `#3567b5` | `#7aa5ec` | categoría | Color de entrada por defecto (no se pinta tal cual) |
| `--c-negocios` | `#7a4fb3` | `#b496e8` | categoría | Ídem |
| `--c-casa` | `#b36b2a` | `#e3a46a` | categoría | Ídem |
| `--c-personal` | `#2f8a87` | `#5fc4c0` | categoría | Ídem |
| `--c-salud` | `#c0436b` | `#ec86a7` | categoría | Ídem |
| `--c-finanzas` | `#4b7d2f` | `#93c56f` | categoría | Ídem |
| `--c-reptiles` | `#6d7a1f` | `#b8c55a` | categoría | Ídem |
| `--c-otra` | `#7b7870` | `#a3a198` | categoría | Ídem |

- **Categoría atenuada (RF-2, RF-8):** `color-mix(in oklab, var(--cat) var(--cat-mix), var(--surface))`
  en los dos modos (65 % en claro, 55 % en oscuro, sobre la superficie del modo). `--cat` es el color
  guardado en Ajustes o el `--c-*` por defecto. Solo como punto de 8 px (`.dot`) o borde de 2 px,
  también dentro de un filtro o del selector de categoría; nunca fondo, borde o texto de un botón ni
  foco. El texto de la categoría va en `--ink-2`. Es decorativo: sin mínimo de contraste (RF-27).
  Excepción E2. El valor guardado no cambia.
- **Colores de datos (RF-49):** azul y ámbar. Comprobación: simulación con las matrices de
  Machado et al. (2009), severidad 1,0, en RGB lineal, y ΔE76 en CIELAB (D65) entre las dos series;
  mínimo exigido 20. Calculado: claro prot. 114,0 · deut. 126,0 · trit. 83,5; oscuro prot. 102,9 ·
  deut. 107,6 · trit. 76,3. Además del color: serie 2 rayada, orden fijo en la pila (Claude abajo),
  separación de 2 px y leyenda con los dos nombres en texto (RF-43, RF-50).
- **Manifiesto (RF-41):** `theme_color` y `background_color` = `#56646A` (neutro medio con el mismo
  tinte, válido en los dos modos). En la página: dos `<meta name="theme-color">` con
  `media="(prefers-color-scheme: light|dark)"` y el `--bg` de cada modo; `status-bar-style`
  `default`. `:root { color-scheme: light dark; }` (controles nativos siguen el modo).

### Contraste
Luminancia relativa WCAG 2.x. **Medido en T23 (2026-11-18)** en el navegador (Chromium del MCP de
Playwright, demo con datos ficticios): cada token pintado con `var()` y leído en un lienzo de 1×1, en
claro y en oscuro; `tests/browser/medir.js` sin fallos de contraste en todas las vistas y diálogos a
375×812 y 1280×800. Los `color-mix` los resuelve el navegador (redondeo a 8 bits), por eso cuatro
pares difieren en ±0,01 del cálculo en Oklab de `tests/test_design_tokens.py`, que admite ±0,02.
Mínimo: 4,5 texto · 3 texto grande, iconos, bordes de control, foco y datos.

| Color | Fondo | Mínimo | Claro | Oscuro |
|---|---|---|---|---|
| `--ink` | `--bg` | 4.5 | 15.36 | 15.80 |
| `--ink` | `--surface` | 4.5 | 16.66 | 14.65 |
| `--ink` | `--surface-soft` | 4.5 | 14.26 | 12.93 |
| `--ink` | `--accent-soft` | 4.5 | 13.91 | 12.08 |
| `--ink` | `--danger-soft` | 4.5 | 14.30 | 12.75 |
| `--ink-2` | `--bg` | 4.5 | 8.45 | 8.92 |
| `--ink-2` | `--surface` | 4.5 | 9.17 | 8.27 |
| `--ink-2` | `--surface-soft` | 4.5 | 7.85 | 7.30 |
| `--ink-3` | `--bg` | 4.5 | 5.00 | 6.16 |
| `--ink-3` | `--surface` | 4.5 | 5.42 | 5.72 |
| `--ink-3` | `--surface-soft` | 4.5 | 4.64 | 5.04 |
| `--accent` | `--bg` | 4.5 | 5.80 | 9.03 |
| `--accent` | `--surface` | 4.5 | 6.29 | 8.37 |
| `--accent` | `--surface-soft` | 4.5 | 5.38 | 7.39 |
| `--accent` | `--accent-soft` | 3 | 5.25 | 6.90 |
| `--accent-ink` | `--accent` | 4.5 | 6.29 | 8.67 |
| `--bg` | `--ink` | 4.5 | 15.36 | 15.80 |
| `--ok` | `--bg` | 4.5 | 4.92 | 8.53 |
| `--ok` | `--surface` | 4.5 | 5.33 | 7.91 |
| `--ok` | `--surface-soft` | 4.5 | 4.57 | 6.98 |
| `--warn` | `--bg` | 4.5 | 5.46 | 9.24 |
| `--warn` | `--surface` | 4.5 | 5.93 | 8.57 |
| `--warn` | `--surface-soft` | 4.5 | 5.07 | 7.57 |
| `--danger` | `--bg` | 4.5 | 6.06 | 7.28 |
| `--danger` | `--surface` | 4.5 | 6.57 | 6.75 |
| `--danger` | `--surface-soft` | 4.5 | 5.63 | 5.96 |
| `--danger` | `--danger-soft` | 3 | 5.64 | 5.87 |
| `--line-strong` | `--bg` | 3 | 3.32 | 4.01 |
| `--line-strong` | `--surface` | 3 | 3.60 | 3.72 |
| `--line-strong` | `--surface-soft` | 3 | 3.09 | 3.28 |
| `--data-1` | `--surface` | 3 | 5.68 | 6.42 |
| `--data-2` | `--surface` | 3 | 3.92 | 7.46 |

`--line-strong` claro pasó de `#7F8C91` (2,96 sobre `--surface-soft`) a `#7C898E`, mismo matiz,
para llegar a 3:1 en los campos dentro de tarjeta (decisión del usuario, 2026-11-18).

## Tipografía
- **Familia:** Atkinson Hyperlegible Next (Braille Institute, SIL OFL 1.1), una sola para todo:
  distingue I/l/1, O/0 y rn/m, lo que más se lee de pie (ids `#123`, importes, horas, fechas).
  **Pendiente de descarga en T4** (woff2 variable, subconjunto latín, pesos 400/500/600, servida por
  `/fonts/…`). Si no tiene cifras tabulares o los glifos del español, alternativa: Public Sans.
- **Respaldo (RF-36):** la del sistema, con `font-display: swap`. Los anchos no dependen de la
  métrica (`min-width:0`, `overflow-wrap:anywhere`); ✓ ✕ 🔁 caen a la fuente del sistema.

| Token | Claro | Oscuro | Escala | Uso |
|---|---|---|---|---|
| `--font` | `"Atkinson Hyperlegible Next", system-ui, -apple-system, "Segoe UI Variable Text", "Segoe UI", sans-serif` | — | familia | Toda la página |
| `--fs-xs` | `13px` | — | fuente | 400/500, interlineado 1.4: metadatos, chips, tags, ejes, contadores de subpestaña |
| `--fs-sm` | `14px` | — | fuente | 500, 1.4: rótulos de contadores, etiquetas de campo, tablas de Consumo, subtítulos |
| `--fs-md` | `16px` | — | fuente | 400/500, 1.5: **cuerpo** (títulos de tarea, párrafos, avisos, mensajes del historial, todos los campos), botones, pestañas |
| `--fs-lg` | `20px` | — | fuente | 600, 1.3: títulos de sección, de grupo y de diálogo, cifras de Fechas |
| `--fs-xl` | `24px` | — | fuente | 600, 1.25: título de vista, cifras de contadores y de Consumo, total de Gastos, estado de En vivo |

- **Cifras tabulares (RF-12):** `font-variant-numeric: tabular-nums` en los cinco contadores, los
  números de día de los dos calendarios, cifras y tablas de Consumo y todo importe.
- Sin mayúsculas forzadas (se quitan en `.dt-group h4` y `.dt-badge span`). Párrafos con
  `max-width: 70ch`.

## Espaciado y layout
| Token | Claro | Oscuro | Escala | Uso |
|---|---|---|---|---|
| `--sp-0` | `2px` | — | espacio | Separación de barras, ajustes finos |
| `--sp-1` | `4px` | — | espacio | Dentro de un componente |
| `--sp-2` | `8px` | — | espacio | Dentro de un componente |
| `--sp-3` | `12px` | — | espacio | Dentro de un componente |
| `--sp-4` | `16px` | — | espacio | Entre componentes; margen lateral a 375 px (+ zona segura) |
| `--sp-5` | `24px` | — | espacio | Entre componentes |
| `--sp-6` | `32px` | — | espacio | Entre bloques de una vista |
| `--sp-7` | `48px` | — | espacio | Márgenes reservados (p. ej. bajo `main` por el aviso) |
| `--w-page` | `1040px` | — | ancho | Ancho máximo de cada vista (RF-37) |
| `--w-col` | `720px` | — | ancho | Formularios, listas de una columna, conversación |

- A 375 px: una columna. A ≥ 1024 px: grupos de Tareas en 2 columnas; Historial y Consumo en `grid2`.
  Alineación a la izquierda salvo estados vacíos y En vivo (centrados).
- **Cabecera:** fondo `--bg` opaco (sin desenfoque), borde inferior `--line`, marca a la izquierda,
  indicador a la derecha; a ≤ 640 px las pestañas pasan a una segunda fila con desplazamiento interno.
- **Zonas seguras (RF-26):** `env(safe-area-inset-*)` en cabecera, avisos, diálogos, botón de
  hablar, panel de voz y margen inferior de `main`.
- La página nunca se desplaza en horizontal; pestañas, subpestañas, filtros y tablas anchas, por dentro.

## Forma
| Token | Claro | Oscuro | Escala | Uso |
|---|---|---|---|---|
| `--r-sm` | `6px` | — | radio | Tags, marcas del calendario, chips pequeños, esquina del emisor en burbujas |
| `--r-md` | `10px` | — | radio | Botones, campos, filas, días del calendario |
| `--r-lg` | `14px` | — | radio | Tarjetas, secciones, diálogos, hoja inferior, burbujas |
| `--r-full` | `999px` | — | radio | Píldoras, círculos |

Radios concéntricos (14 > 10 > 6). Bordes de 1 px: `--line` separa, `--line-strong` en controles.
Sin borde lateral grueso de color. Sombra: solo `--shadow-float`, solo en lo que flota.

## Movimiento
| Token | Claro | Oscuro | Escala | Uso |
|---|---|---|---|---|
| `--dur-1` | `120ms` | — | duración | Color, encima, chevron |
| `--dur-2` | `200ms` | — | duración | Aviso, tooltip, panel de voz |
| `--dur-3` | `240ms` | — | duración | Diálogos y hoja inferior |
| `--ease-out` | `cubic-bezier(.23,1,.32,1)` | — | curva | Entradas |
| `--ease-io` | `cubic-bezier(.77,0,.175,1)` | — | curva | Movimiento en pantalla |
| `--ease` | `ease` | — | curva | Cambios de color |

- Máximo 300 ms (RF-31), salvo E3 y E4. Solo `transform` y `opacity` (y color). Nunca
  `transition: all` ni `ease-in`. `hover` solo con `@media (hover:hover) and (pointer:fine)`.
- Sin animación: pestañas, subpestañas, filtros, contadores, marcar hecha, filas, medidor de En vivo.
- Aviso: `opacity` + `translateY(8px)` en `--dur-2`, sale ~20 % más rápido. Diálogos: `opacity` +
  `scale(.98)`; hoja inferior: `translateY`. Pulsado: `scale(.97)` en `:active`.
- **Reducir movimiento (RF-30):** sin desplazamientos ni escalas en toda la página (aviso, diálogos,
  panel de voz, ondas, anillos y «respirar» de En vivo, pulso y giro del botón de hablar); quedan
  opacidad y color. En lugar del pulso, «grabando» muestra un anillo fijo `--danger` (decisión del
  usuario, 2026-11-18).

## Componentes clave
| Componente | Reposo | Encima | Pulsado | Foco | Desactivado | En curso / seleccionado |
|---|---|---|---|---|---|---|
| Botón principal | `--accent` + `--accent-ink`, 600, `--r-md`, alto 44 (32-36 con ratón) | acento 8 % más oscuro (`color-mix`) | `scale(.97)` | anillo `--focus` 2 px, sep. 2 px | `--surface-soft` + `--ink-3`, `cursor:default` | `aria-busy`: mismo texto + icono de espera |
| Secundario (`.ghost`) | `--surface` + borde `--line-strong` + `--ink` | `--surface-soft` | `scale(.97)` | anillo | ídem | — |
| Peligro (`.danger`) | como secundario, texto `--danger` | borde `--danger` | ídem | anillo | ídem | — |
| Icono (`.icon-btn`, ✕, ‹ ›) | transparente, `--ink-2`, zona 44×44 | `--surface-soft` | ídem | anillo | ídem | — |
| Pestañas | `--ink-2`, 500 | `--ink` | — | anillo | — | activa: `--ink` 600 + subrayado 2 px `--accent` |
| Subpestañas | píldora `--surface` + borde `--line` | borde `--line-strong` | — | anillo | — | activa: `--accent-soft`, borde `--accent`, 600 |
| Indicador de conexión | punto 8 px `--ink-3` + texto | — | — | — | — | conectado: punto `--ok`; desconectado: punto `--danger` hueco |
| Campo | `--surface` (o `--surface-soft` en tarjeta), borde `--line-strong`, 16 px, alto 44 | — | — | borde `--accent` + anillo | opacidad .5 + `--surface-soft` | error: borde `--danger` + texto de error existente |
| Aviso emergente | `--surface` + borde `--line-strong` + `--shadow-float`; «Deshacer» `--accent` 600 | — | — | anillo | — | entra/sale (Movimiento) |
| «Hermes no responde» | franja en flujo al inicio de `main`: `--danger-soft`, ⚠ SVG `--danger`, texto `--ink` | — | — | — | — | — |
| Diálogos | `--surface`, `--r-lg`, `--shadow-float`, fondo `--scrim` | — | — | foco dentro, Escape, foco devuelto (RF-29) | — | — |
| Botón de hablar | círculo 60 px `--accent` + `--accent-ink`, `--shadow-float` | — | `scale(.94)` | anillo `--ink` | — | grabando: `--danger` + ■ y pulso (con reducir movimiento, anillo fijo `--danger` de 2 px separado del botón, sin animación; decisión del usuario, 2026-11-18); pensando: icono de espera girando; hablando: ■ |
| Panel de voz | `--surface` + borde + `--shadow-float`; oído `--ink-3` 13 px, respuesta 16 px | — | — | — | — | error: texto `--danger` |

- **Aviso:** abajo, centrado, por encima del botón de hablar (`can-speak`), nunca sobre la acción
  principal; en En vivo y Ajustes, margen inferior reservado en `main`.
- **Diálogos a 375×812 (RF-17):** editor como hoja inferior con acciones `position: sticky; bottom: 0`;
  confirmación y foto con acciones al pie, alto máximo `100dvh`, imagen con `max-height`.
- **Estados de carga (RF-21, RF-47):** «Cargando…» visible donde ya existe; esqueleto quieto (3 filas
  `--surface-soft`, sin animación); `aria-busy="true"` y anuncio `.sr-only`. Vacío: `.empty-state`
  centrado, título 16/600 `--ink`, texto 14 `--ink-2`, mismo texto de hoy. Error: «Hermes no responde».

### Acción principal por vista (RF-16)
| Vista | Acción principal |
|---|---|
| Tareas | Caja de escribir/hablar: campo, «Enviar» y botón de hablar |
| Apuntes | Formulario de crear/agregar de la subpestaña activa; en Gastos, la navegación de mes (‹ ›) |
| Consumo | «Ver como tabla» |
| Historial | El buscador |
| En vivo | El botón del micrófono |
| Ajustes | «Guardar cambios» |
| Diálogos | Guardar (editor), confirmar (confirmación), Cerrar (foto de recibo) |

### Vistas
- **Tareas:** contadores `--surface` + borde `--line`, cifra `--fs-xl` tabular, rótulo `--fs-sm`
  `--ink-3`; seleccionado: borde 2 px `--accent` + `--accent-soft`; «Vencidas» > 0 en `--danger` 600;
  a 375 px rejilla de 2 columnas, el quinto a lo ancho. Lista/Calendario: segmentado `--surface-soft`,
  activo `--surface` + 600. Filtros con punto atenuado, activo como subpestaña activa. Tarjeta (≥ 44 px):
  glifo de urgencia en columna fija (alta: triángulo 10 px `--danger`; normal: círculo lleno 8 px
  `--ink-2`; baja: círculo hueco 8 px `--ink-3`), casilla 22 px con zona 44, título 16/500 a 2 líneas
  (`-webkit-line-clamp: 2`), metadatos 13 px `--ink-3`; «Urgente» y «Vencida · …» en `--danger` 600;
  hecha: casilla `--accent` con ✓ y título tachado `--ink-3`. Calendario: celdas `--r-md` ≥ 44×48 a
  375 px, número tabular; hoy: círculo `--ink` con texto `--bg`; elegido: borde `--accent` +
  `--accent-soft`; marcas urgentes/vencidas `--danger`.
- **Apuntes:** subpestañas con desplazamiento interno; aviso de silencio `--accent-soft` + borde
  `--accent`; formularios de una columna a 375 px. Hábitos: botón de hoy 46 px, 7 días con zona ≥ 44,
  racha `--ink` 600. Fechas: como el Calendario, distintivo `--surface-soft`, próximas `--ink` 600.
  Gastos: total `--fs-xl` tabular; barras `--ink-3`, cerca `--warn`, pasado `--danger` 600; miniatura
  48 px. Pagos: próximos `--warn`, vencidos `--danger` (borde 2 px y texto). Lecturas: enlace con
  `overflow-wrap:anywhere`.
- **Consumo:** 4 cifras `--fs-xl` tabulares; 14 columnas sin desplazamiento, cada `.col` a todo el alto
  (≥ 44 px) como zona pulsable; barras `--data-1` lisa y `--data-2` con `repeating-linear-gradient`
  de `--data-2` y `--surface`; leyenda con muestra y nombre; tooltip `--surface` + `--shadow-float`;
  ejes 13 px `--ink-3`; tablas 14 px tabulares con desplazamiento interno.
- **Historial:** buscador de 44 px; burbujas tuyas `--surface-soft`, de Hermes `--surface` + borde
  `--line`, 16 px, `--r-lg` con la esquina del emisor `--r-sm`; separador de día 13 px `--ink-3`;
  escuchas con resultado `--ok`/`--danger` y chips de tiempos 13 px tabulares.
- **En vivo:** fondo `--bg`, sin degradado; anillos de 1,5 px `--accent` con opacidad por estado y
  nivel, sin halos; ondas solo escuchando/grabando/pensando/hablando; disco `--surface` + borde
  `--line-strong` con el logo; en pausa, logo gris atenuado y anillos `--line-strong`. Estado
  `--fs-xl` 600 `--ink`, pista `--ink-2`. Micrófono: secundario; con `aria-pressed`, principal.
  Medidor: pista `--surface-soft`, nivel `--ink-3`, voz `--ok`, umbral `--ink`.
- **Ajustes:** grupos `--surface` con título `--fs-lg`; filas etiqueta/control (una columna a ≤ 640 px);
  interruptores con `accent-color: var(--accent)` y zona 44; chips de categoría con el selector nativo
  (E2) y ✕ con zona 44; aviso de reinicio como el de silencio; barra de Guardar al pie.

### Logo e iconos (RF-51, RF-52)
Desde T22 (2026-11-18) el logo es el monograma «H»: sustituye al logo anterior en los tres archivos y
en la cabecera (`.brand-dot` → `.brand-mark`). Monograma «H» de trazo grueso (≥ 1/6 del lado) con el travesaño en diagonal ascendente (el mensaje
que sale), en `#F4F6F6` sobre el tono de marca `#1F7E90` (E6). Logo (`logo.webp`, 1254×1254): disco
con la marca, transparente fuera. Iconos 192 y 512: cuadrado a sangre del tono de marca, marca dentro
del 60 % central. Fuente vectorial en `docs/logo.svg`; rasterizado en el navegador del MCP. Cabecera:
`.brand-mark`, la misma marca en SVG en línea de 20 px. Mismos nombres, rutas y tamaños.

## Accesibilidad
- Contraste: 4,5:1 texto; 3:1 texto grande, iconos, bordes de control, foco y datos (tabla Contraste).
  Desactivados exentos, pero visiblemente no disponibles.
- Foco: anillo `--focus` de 2 px con 2 px de separación en todo control; orden de Tab = orden visual.
- Zona táctil: 44×44 px con puntero táctil o a ≤ 640 px; 32 px de alto con ratón. Enlaces en texto
  exentos; `.col` exenta del ancho (E1).
- Estados nunca solo por color: glifo, peso, forma o texto existente. Campos a 16 px (Safari no acerca).

## Referencias
| Referencia | Se adopta (principio) | Se descarta y por qué |
|---|---|---|
| [Raycast](references/raycast.com/raycast.com.md) | Jerarquía por luminosidad en 3 pasos de tinta; borde de 1 px en vez de sombra en superficies; anillo de foco de 2 px; peso 500 en etiquetas; movimiento solo en `transform`/`opacity` de 0,1-0,3 s; acento escaso, nunca decorativo | «Acento fuera de los controles» (la spec pone el acento en la acción principal); solo oscuro; brillo superior en bordes (no funciona en claro); barra con desenfoque; sombras de 4 capas; 9 tamaños; cuerpo de 14 px; teclas dibujadas (Hermes es táctil); grises puros; 224 px entre secciones; su rojo y su tipografía |
| [Linear](references/linear.app/linear.app.md) | Estado en un glifo de forma distinta en columna fija con texto neutro; sombra solo en lo que flota; radios concéntricos 14 > 10 > 6; grupos con cabecera y contador; hoja inferior con filas a ancho completo; transiciones de color de 100-160 ms | Botón principal neutro (la spec pone el acento); cuerpo de 12-15 px y objetivos de 32-40 px a 375 px (Hermes: 16 px y 44 px); pesos 510/590; solo oscuro; su índigo, Inter y Berkeley Mono; titulares de 48-72 px |

## Anti-patrones del proyecto
Además de `.claude/skills/sdd-design/references/anti-patterns.md`:
- Acento en lo que no es selección, acción principal ni foco (hoy, próximos, progreso, títulos al pasar).
- Color de categoría como fondo, borde o texto de un control, o en el foco; color de datos fuera de un gráfico.
- Sombra en tarjetas o secciones que no flotan; desenfoque de cabecera; tema negro y dorado.
- Texto de menos de 16 px en campos.
- Literales de color, tamaño, espacio, radio o tiempo fuera de `:root` (lo vigila el test de tokens).
- Textos visibles nuevos (salvo las excepciones de RF-32).
- Textos heredados con «·» o emojis: se conservan tal cual (RF-32); no son modelo para textos nuevos.

## Excepciones
Previstas en el plan (4.10). Las que surjan al implementar se añaden aquí y se aprueban una a una (RF-4).

| # | Selector | Propiedad | Regla que rompe | Motivo | Aprobación |
|---|---|---|---|---|---|
| E1 | `.col` | `width` | Ancho de 44 px (RF-25) | 14 días sin desplazamiento a 375 px dejan ~16 px por columna; la zona pulsable ocupa todo el alto (≥ 44 px) y toda la franja (RF-43) | Aprobada por el usuario (2026-11-18) |
| E2 | `.chip-color` | `color` | Solo variantes atenuadas (RF-8) | Muestra el color guardado tal cual, sin vista previa: es lo que el usuario elige (RF-8) | Aprobada por el usuario (2026-11-18) |
| E3 | `.ripple`, `.orb[data-state="pensando"] .disc` | `animation` | > 300 ms, en bucle con keyframes (RF-31) | Comunica el estado de la voz mientras dura; ciclos de 1,5 a 4,2 s, solo `transform` y `opacity`; con reducir movimiento, sin ondas ni escala | Aprobada por el usuario (2026-11-18) |
| E4 | `.talk-btn[data-state="grabando"]`, `.talk-btn[data-state="pensando"] .i-wait` | `animation` | Pulso en bucle (1,2 s) y giro (1 s, `linear`) (RF-31) | Indican grabación y espera; con reducir movimiento, sin pulso y el icono de espera quieto con opacidad | Aprobada por el usuario (2026-11-18) |
| E5 | archivos `logo.webp`, `icon-192.png`, `icon-512.png` | — | Acento en más del ~20 % de la superficie | El icono es la marca: fondo de color de marca a sangre (iOS rellena de negro lo transparente) | Aprobada por el usuario (2026-11-18) |
| E6 | archivos `logo.webp`, `icon-192.png`, `icon-512.png`, `docs/logo.svg` | — | Tono `#1F7E90` y blanco `#F4F6F6` fijos, que no son tokens CSS | Un único archivo debe verse en claro y en oscuro: tono medio del acento (4,72:1 sobre `--surface` claro y 3,64:1 sobre `--surface` oscuro, medido en T23). Blanco de marca `#F4F6F6` (el `--bg` claro, fijo en los archivos) para el monograma: 4,36:1 sobre `#1F7E90`, ≥ 3:1 de icono (propuesta de T22, aceptada en nombre del usuario por su delegación del 2026-11-18) | Aprobada por el usuario (2026-11-18) |
| E7 | `.cal-day`, `.ed-steps .linkish`, `.ed-steps .icon-btn` | `width`, `min-height` | Área táctil de 44 px (RF-25) | Solo con el texto al 200 % a 375 px (~188 px útiles): siete columnas de 44 px no caben en ~173 px, así que el calendario mensual (Tareas y Fechas) y los pasos del editor priorizan no desbordar ni solaparse (RF-40); fuera de ese caso siguen las reglas normales | Aprobada por el usuario (2026-11-18) |
