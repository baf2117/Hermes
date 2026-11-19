Source: https://www.raycast.com/ · analyzed on 2026-11-17 · for style study, not for copying

Pages analyzed: 1 (home only). Viewport 1440×900. Screenshots (viewport, mid, footer) stay local and are git-ignored.

# Design Map

## Spacing Scale
- Base unit: 4px
- Component values: 2, 4, 8, 12, 16, 24px (most frequent: 8px ×285, 12px ×138, 24px ×128, 16px ×66)
- Card inner padding: 24px
- Navbar padding: 16px 32px
- Section containers: 224px top/bottom, 24px sides
- Method: `gap` on flex/grid (44 grids on the page)

## Font Hierarchy
- 64px / 600 / lh 70.4px — hero (Inter)
- 32px / 500 / lh 38.4px / -0.8px — section heading
- 24px / 500 — subheading
- 20px / 500 / +0.2px — card heading
- 18px / 400 / +0.2px — lead text, feature title
- 16px / 400 — body
- 14px / 500 / lh 22.4px / +0.2px — nav links, buttons, card copy
- 13px / 500 — small buttons
- 11px / 400 — kbd chips, meta (system font)
- Weights: 500 ×370, 400 ×315, 600 ×91, 700 ×4
- Families: Inter (UI), system stack Segoe UI Variable / SF Pro Text inside product mockups, GeistMono for install hints
- No modular ratio; no `ch` max-width

## Color Palette
- #07080A — page background (slightly cool)
- #0C0D0F → #07080A, 45° — card surface gradient
- rgba(255,255,255,.02 / .03 / .05 / .10) — surface tints
- rgba(255,255,255,.06) — hairline borders
- #FFFFFF — primary text
- rgba(255,255,255,.6) — secondary text, kbd
- #9C9C9D — nav links, card copy
- #6A6B6C — tertiary
- #434345 — disabled / quiet
- #E6E6E6 bg + #2F3031 text — primary button
- #FF6363 — brand red: logo, hero artwork, link underline only
- rgba(255,255,255,.5) — focus ring
- Color scheme: dark only (no light theme)

## Image Ratios
- 16:9 — feature section background (1185px wide)
- 1:1 — extension cards (360px)
- 1:1 — app icons rendered at 16–22px

## Component Tokens
- Radius: 16px navbar · 12px card · 11px keycap · 8px primary button · 6px nav link and kbd · 4px small button · 100% avatars
- Card: 0.8px solid rgba(255,255,255,.06) + `inset 0 1px 0 rgba(255,255,255,.10)`
- Navbar: floating, 16px radius, gradient rgba(17,18,20,.75)→rgba(12,13,15,.9), `inset 0 1px 1px rgba(255,255,255,.15)`, backdrop blur 5px
- Primary button: 36px high, 8px 12px padding, 4 layers: `0 0 0 2px rgba(0,0,0,.5)`, `0 0 14px rgba(255,255,255,.19)`, `inset 0 -1px .4px rgba(0,0,0,.2)`, `inset 0 1px .4px #fff`
- Nav link: 14px/500, #9C9C9D, 12px 8px padding, 6px radius
- kbd: 11px, 6px radius, padding 0 4px, `inset 0 0 0 1px rgba(255,255,255,.2)`
- Focus: `:focus-visible { box-shadow: 0 0 0 2px rgba(255,255,255,.5) }`
- Motion: transform .1–.3s, opacity + transform .3s ease-out, background/box-shadow .2s ease-in-out; `prefers-reduced-motion` turns off transforms
- Grid: 1204px container, 2-column feature grid, ~40px gutter

---

# Taste DNA

### Accent Off the Controls
- **Trigger**: When a strong red brand meets a near-black page where red would pop on any control…
- **Decision**: They kept red for the logo, the hero artwork and a single link underline, and made the primary button light grey #E6E6E6 with #2F3031 text and the focus ring white at 50%, over red CTAs and red focus states.
- **Reason**: On near-black the brightest object wins: a light button out-shouts any hue, and keeping red rare lets it mean the brand instead of "press here".
- **Evidence**: accent candidates from buttons and links are all greys; button bg #E6E6E6; focus `0 0 0 2px rgba(255,255,255,.5)`; #FF6363 appears only in the logo and the link underline.

### Light Draws the Edges
- **Trigger**: When separating cards and the navbar from a #07080A page where black drop shadows disappear…
- **Decision**: They used a 0.8px rgba(255,255,255,.06) border plus a 1px inset top highlight and a 45° #0C0D0F→#07080A gradient, over drop shadows or solid grey panels.
- **Reason**: A thin bright top edge reads as a lit bevel, so the eye finds the container without it lifting off the page.
- **Evidence**: card 12px radius, border .06, inset 0 1px .10; navbar 16px, inset .15, blur 5px; white tints .02–.10 cover ~34% of painted area.

### Rank by Brightness, Not by Hue
- **Trigger**: When ordering titles, body, meta and disabled text on a dark ground…
- **Decision**: They built a 5-step luminance ladder (#FFFFFF → .6 white → #9C9C9D → #6A6B6C → #434345) over colored secondary text.
- **Reason**: Readers scan a dark interface by brightness first, so importance is read at a glance and no color is spent on hierarchy.
- **Evidence**: text node counts 471 / 105 / 95 / 49 / 35; card copy 14px/500 #9C9C9D under 18px white titles.

### Demonstrate the Shortcut
- **Trigger**: When explaining a keyboard-first product…
- **Decision**: They rendered keycaps (11px radius, 4-layer shadow) and inline kbd chips (11px text, 6px radius, inset ring) over icons or prose about shortcuts.
- **Reason**: Seeing the exact key to press removes a translation step; the page shows the interaction instead of describing it.
- **Evidence**: 11px radius ×158 with a matching 4-layer shadow ×158; kbd text rgba(255,255,255,.6), inset ring rgba(255,255,255,.2).

---

# Notas de traslado (Hermes, modo Operar, 375 px)

- Trasladable: acento fuera de los controles comunes (el acento marca estado o selección; el botón principal puede ser neutro de alto contraste); jerarquía de texto por luminosidad en 4-5 pasos; bordes de 1px con tinte en lugar de sombras en oscuro; radios concéntricos (contenedor > control); peso 500 para etiquetas; movimiento solo en transform/opacity de 0.1–0.3 s con `prefers-reduced-motion`; foco visible con anillo de 2px.
- No trasladar: solo existe tema oscuro (Hermes necesita claro y oscuro; en claro el borde con brillo superior no funciona igual y hay que redefinirlo); escala de 9+ tamaños (Hermes: máximo 5, cuerpo 16px); textos de 11–14px como copy de tarjeta (en 375 px táctil, mínimo 16px de cuerpo); 224px de aire entre secciones (es ritmo de página de marketing, no de herramienta densa); arte de fondo, desenfoque de barra y sombras de 4 capas (coste y ruido en móvil); keycaps (Hermes es táctil, no de teclado); grises casi puros (#9C9C9D) mientras Hermes pide neutros con tinte; sin cifras tabulares observadas.
