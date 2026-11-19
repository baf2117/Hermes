Source: https://linear.app/ · analyzed on 2026-11-17 · for style study, not for copying

Pages analyzed: 4 (https://linear.app/, /mobile, /plan, /build), public, no login. Viewport 1440×900, plus /mobile at 375×812. [S] = system signal (2+ pages), [L] = local (1 page). Screenshots stay local and are git-ignored. Note: the app UI is seen only inside marketing mock-ups and images, so in-app measurements (row heights, sheet rows) are ~approx.

# Design Map

## Spacing Scale
- Base unit: 4px [S]
- Component values: 2, 4, 6, 8, 12, 16, 24px (most frequent on /: 8px ×135, 4px ×128, 6px ×76, 12px ×46)
- Property-row gaps: 4 / 6 / 8px; list `ul` gap 8px [S]
- Marketing sections: 32, 48, 96, 128px; 224px between blocks [S]
- Mobile (375px): 24px side padding, fixed header 65px
- Method: `gap` on flex/grid; headings margin 0

## Font Hierarchy
- 72px / 500 / lh 72px / -1.584px — hero on /plan, /build [S]
- 64px / 510 / lh 64px / -1.408px — hero on / [L]
- 48px / 510 / lh 48px / -1.056px — section heading [S]
- 32px / 590 / lh 36px / -0.704px — hero at 375px
- 20px / 590 / lh 26.6px / -0.24px — card and feature title
- 15px / 400 / lh 24px — marketing body
- 14px / 510 — app row title (mock-ups)
- 13px / 510 / lh 19.5px — app property label, buttons [S]
- 12px / 400 — meta, group headers, timestamps [S]
- Weights: 400 ×487, 510 ×141, 590 ×8 (variable-font steps, not 500/600)
- Families: Inter Variable (all UI and copy), Berkeley Mono (issue IDs, code, gesture captions)
- Letter-spacing ≈ -0.022em on headings only; no modular ratio; no `ch` max-width

## Color Palette
- #08090A — page background (64–95% of painted area on all 4 pages) [S]
- #0F1011 — app panel surface (20.6% on /)
- #1C1C1F / #232326 — bg-secondary / tertiary (selected row, sheet, chips)
- #23252A — border-primary; #37393A — line
- #F7F8F8 — text primary
- #D0D6E0 — text secondary (cool tint, +16 blue)
- #8A8F98 — text tertiary (most used text color on every page) [S]
- #62666D — text quaternary (disabled, faded cards)
- #7170FF — accent token; #5E6AD2 — brand fill and focus ring (#5E69D1); #828FFF — eyebrow text on /mobile [L]
- #E5E5E6 — primary CTA fill (neutral light pill, not the accent) [S]
- Status glyph colors (yellow in progress, green review, indigo done, red #C52828 canceled, orange #F2994A): 0% painted area — icons only
- Theme: marketing forces `data-theme="dark"`, 0 `prefers-color-scheme` rules; light variants exist in CSS (`[data-theme=light]`, accent-tint #F1F1FF vs #18182F dark)

## Image Ratios
- 1.79:1 — hero app screenshot (/)
- 1.99:1 — full-width feature bands (/plan)
- 1.58:1 — feature screenshots (/plan, /build) [S]
- 1.18:1 — mobile feature illustrations (/mobile)
- 1.49:1 — mobile hero photo, desaturated with grain

## Component Tokens
- Radius: 9999px pills (actions, nav, CTA, ×82) · 12px panels, QR card, floating window · 8px rows, selection, small buttons · 6px · 4px code chips
- Nesting: panel 12 > row 8 > chip 4; window frame 12px 12px 0 0
- Rings: `0 0 0 1px rgba(0,0,0,.2)`; `inset 0 0 0 1px rgba(255,255,255,.05)`; `inset 0 0 0 .5px rgba(255,255,255,.08)`
- Elevation (floating only): `0 2px 32px rgba(0,0,0,.25)`
- Motion: color / background / border-color 100–160ms `cubic-bezier(.25,.46,.45,.94)`; reveal opacity 1s `cubic-bezier(.215,.61,.355,1)` + blur 0.2s; `prefers-reduced-motion` handled
- Focus: `:focus-visible` present, ring #5E69D1
- Grid: 2 columns (665.6px ×2, gap 0) on /plan and /build; bento 487px ×2, gap 2px on /mobile; app mock 232px sidebar + 1072px panel
- Group header (Reviews mock): 12–13px label + count + chevron on #1C1C1F-ish band; rows: title 14px/510 primary, meta 12px tertiary, time right-aligned
- Mobile sheet (mock): grabber, title 13px/590, full-width rows icon + label left, value right in tertiary, check on the current item
- Touch at 375px: nav pills 32px high, store buttons 40px, menu button 64×64

---

# Taste DNA

### State lives in the glyph, not the row
- **Trigger**: When showing status, priority and labels on hundreds of items in a list…
- **Decision**: They chose 14px glyphs with semantic color *and* a distinct shape (dashed, empty, half-filled, check, cross) next to neutral text, over colored badges, tinted row backgrounds or colored text.
- **Reason**: In a long list a glyph in a fixed column is caught by peripheral vision; painted rows turn the list into a patchwork and color stops meaning anything.
- **Evidence**: status reds/oranges/greens cover 0% of painted area on /plan; the /mobile status sheet separates 8 states by shape as well as hue; property rows are 14–16px icon + 13px/510 label with 4/6/8px gaps.

### Four greys do the work of four sizes
- **Trigger**: When ordering title, metadata, date and secondary text inside 32–40px rows…
- **Decision**: They chose four text luminance steps (#F7F8F8, #D0D6E0, #8A8F98, #62666D) at 12–15px over a wider type scale or heavier weights.
- **Reason**: Changing size changes row height and breaks the list rhythm; dimming keeps the row compact and still says what to read first.
- **Evidence**: text color counts 192 / 131 / 115 / 81 on /; 12/13/14/15px make up ~85% of text nodes; only three structural weights (400 / 510 / 590). The font itself is stock Inter — the hierarchy comes from the grey ladder, not from typographic craft.

### No shadow on what does not float
- **Trigger**: When separating sidebar, panel, cards and chips on a near-black page…
- **Decision**: They chose a luminance ladder (#08090A → #0F1011 → #1C1C1F → #232326) plus 1px rings at 0.05–0.08 white, over the soft drop shadow on every card that comparable SaaS sites use.
- **Reason**: On a dark ground a drop shadow is barely visible and muddies edges; lighter reads as nearer instantly, so the real shadow is kept for what truly sits on top.
- **Evidence**: rings `0 0 0 1px rgba(0,0,0,.2)` ×8 and inset white .05 ×4; only the floating 400×520 panel gets `0 2px 32px rgba(0,0,0,.25)`; the 5-layer stacks peak at 0.07 opacity and are imperceptible.

### On the phone, choices go to the thumb in a sheet
- **Trigger**: When moving status changes and snoozing to mobile…
- **Decision**: They chose a bottom sheet with a grabber, full-width rows (icon + label left, value right in tertiary grey) and a check on the current item, over dropdowns, popovers or inline chips.
- **Reason**: The reachable zone on a phone is the bottom of the screen, and a full-width row is a large target that needs no precision; the right-aligned value (time, date) lets you decide without opening anything else.
- **Evidence**: /mobile Status sheet (8 rows, check on the current state) and Snooze sheet (4 rows, time/date right-aligned in #8A8F98); the gesture caption "swipe left to delete" in Berkeley Mono signals swipe as a first-class action.

---

# Notas de traslado (Hermes, modo Operar, 375 px)

- Trasladable: estado de tareas como glifo de forma distinta (vacío, mitad, check, cruz) en columna fija, con color solo en el glifo y texto neutro; jerarquía en filas por 3–4 pasos de luminosidad en vez de más tamaños; superficies por escalera de luminosidad + borde de 1px y sombra solo en lo flotante (hojas, menús); radios concéntricos (contenedor 12 > fila 8 > chip 4) y píldora para acciones; listas agrupadas con cabecera + contador (+ plegar) para Hoy / Próximas / Hechas; hoja inferior con filas a ancho completo y valor alineado a la derecha (posponer: «en 1 h · 17:48») para elegir con el pulgar; fila de propiedades icono + etiqueta corta (fecha, prioridad, lista); botón principal neutro de alto contraste y acento reservado a foco/selección/estado; transiciones de color de 100–160 ms con `prefers-reduced-motion`; `:focus-visible` con anillo del color de marca; cifras e IDs en monoespaciada (en Hermes: cifras tabulares).
- No trasladar: solo oscuro forzado en la web (Hermes sigue el sistema: definir la escalera también en claro, donde los anillos blancos no sirven y hacen falta bordes oscuros con tinte); cuerpo de 12–15 px (Hermes: cuerpo 16 px, máximo 5 tamaños; la densidad de Linear es de escritorio con teclado); objetivos táctiles de 32–40 px medidos a 375 px (Hermes exige 44 px: las filas de hoja deben medir ≥44 px aunque Linear las dibuje más bajas); pesos 510/590 de fuente variable (con fuente propia local, elegir pesos que existan en el archivo incluido); titulares de 48–72 px, 224 px entre secciones, fotos con grano y entradas con desenfoque de 1 s (ritmo de página de marketing, no de herramienta); acento índigo #5E6AD2/#7170FF como color concreto (se toma el principio de un solo acento, no el tono); Berkeley Mono e Inter (fuentes de terceros; Hermes usa su tipografía propia en local).
