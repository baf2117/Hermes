---
name: sdd-design
description: Diseño de interfaz en el flujo SDD. Úsala al redactar el apartado "Interfaz" de un plan, al construir o cambiar una pantalla y al revisar los RF de interfaz. Fija la jerarquía de fuentes de diseño, el modo de la superficie, la estructura de docs/design.md y qué referencias cargar (movimiento, anti-patrones).
---

# Diseño de interfaz en el SDD

Esta skill es la puerta de entrada del diseño. No sustituye a `frontend-design`: la usa como
base de criterio estético y añade lo que el SDD necesita (jerarquía, modos, `docs/design.md`,
checkpoint visual). Carga solo lo que la tarea necesita; no leas todo por defecto.

## Jerarquía de fuentes (la de arriba manda)
1. La petición explícita del usuario y `docs/constitution.md` / `CLAUDE.md`.
2. `docs/design.md` aprobado del proyecto.
3. El apartado "Interfaz" del `plan.md` de la spec.
4. Las referencias analizadas en `docs/references/` (entrada de inspiración, no de copia).
5. Las reglas de esta skill y sus referencias.
6. `.claude/skills/frontend-design/SKILL.md` (criterio base).

Si dos fuentes chocan, gana la de arriba y lo dices en la respuesta. Una excepción a una
regla de esta skill es válida si `docs/design.md` la justifica.

## Modo de la superficie
Antes de diseñar, decide el modo y anótalo en `docs/design.md`; condiciona la ambición:
- **Operar** (aplicaciones, ERP, POS, paneles, ajustes): precisión, densidad útil, rapidez
  de uso repetido, estados claros. Poco movimiento. Es el modo por defecto de las
  herramientas de trabajo.
- **Leer** (documentación, artículos): medida de línea cómoda, jerarquía tipográfica, calma.
- **Persuadir** (landing, marketing, precios): un punto de vista claro, ritmo, una acción
  principal. Admite más expresión.
- **Experimentar** (portafolios, galerías, juegos): expresión alta; el criterio es la
  coherencia con una idea, no la neutralidad.

## Cuándo usar cada parte
| Momento | Qué hacer |
|---|---|
| Plan, apartado "Interfaz" (`planner`) | Elige el modo; lee `docs/design.md` (si existe) y `docs/references/`; deja en el plan el diseño concreto: modo, paleta, tipografías, espaciado, layout, movimiento y principios, y los estados (carga, vacío, error) |
| Primera tarea de interfaz (`implementer`) | Si no existe `docs/design.md`, créalo a partir del diseño aprobado del plan con la estructura de `references/design-md.md` |
| Tarea de interfaz (`implementer`) | Sigue `docs/design.md`. Si la tarea lleva movimiento, lee `references/motion.md` |
| Validación de RF de interfaz (`reviewer`) | Revisa con la lista de `references/anti-patterns.md` y las comprobaciones de abajo |

## Comprobaciones mínimas en toda interfaz
- Móvil a 375 px sin scroll horizontal ni elementos recortados; objetivo táctil de al menos
  44 px en acciones principales.
- Modo oscuro (si el proyecto lo declara) y `prefers-reduced-motion` respetado.
- Contraste WCAG AA: 4,5:1 en texto normal y 3:1 en texto grande y componentes.
- Foco visible con teclado y orden de tabulación lógico.
- Estados de carga, vacío y error definidos; un error dice qué pasó y cómo arreglarlo.
- Texto de la interfaz en el idioma que fija la constitución, desde archivos de traducción si
  el proyecto es multilingüe.
- Sin datos reales en capturas, pruebas ni ejemplos: solo datos ficticios.

## Referencias de esta skill
- `references/design-md.md` — estructura de `docs/design.md`.
- `references/motion.md` — reglas de movimiento (qué animar, curvas, duraciones, accesibilidad).
- `references/anti-patterns.md` — lista de señales de interfaz genérica y de errores
  frecuentes, para diseñar y para revisar.

Para estudiar un sitio de referencia existe el comando manual `/taste <url>` (skill `taste`);
sus resultados quedan en `docs/references/<dominio>/`. Atribuciones de las ideas adaptadas:
`NOTICE.md` en la raíz del repositorio.
