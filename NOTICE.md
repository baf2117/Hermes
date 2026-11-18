# Avisos y atribuciones de terceros

Esta plantilla incluye, adapta o se inspira en el trabajo de terceros. Aquí se indica qué,
de quién y bajo qué licencia.

## Skill `taste` (`.claude/skills/taste/`)
Copia adaptada de **senlindesign/taste-skill** v1.1.0, de Sen Lin
(<https://github.com/senlindesign/taste-skill>). Los cuatro prompts de análisis
(`references/step1-measure.md` a `step4-observer.md`) y `references/extract.js` se incluyen
sin cambios, salvo el nombre de la herramienta en un comentario de `extract.js`. El
`SKILL.md` está modificado (activación explícita, salidas en `docs/references/`, sin
exportación, comprobación con un script propio en Node); la cabecera del propio archivo lista
los cambios. `scripts/check.js` es obra de esta plantilla, no del proyecto original.

El README del proyecto declara la licencia MIT (© 2025 Sen Lin). En el momento de adaptarla,
el archivo `LICENSE` del repositorio no estaba disponible (HTTP 404); si lo publican, conviene
sustituir este aviso por su texto exacto. Texto de la licencia MIT aplicable:

```
MIT License

Copyright (c) 2025 Sen Lin

Permission is hereby granted, free of charge, to any person obtaining a copy of this
software and associated documentation files (the "Software"), to deal in the Software
without restriction, including without limitation the rights to use, copy, modify, merge,
publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons
to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or
substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED,
INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR
PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE
FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR
OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
DEALINGS IN THE SOFTWARE.
```

## Skill `frontend-design` (`.claude/skills/frontend-design/`)
Skill de terceros incluida sin modificar, con su propia licencia en
`.claude/skills/frontend-design/LICENSE.txt`.

## Reglas de movimiento (`.claude/skills/sdd-design/references/motion.md`)
Resumen reescrito, no una copia, de las ideas de las skills de **Emil Kowalski**
(<https://github.com/emilkowalski/skills>, licencia MIT, © 2026 Emil Kowalski). No se incluye
texto literal de su repositorio.

## Modos y anti-patrones (`.claude/skills/sdd-design/`)
Los cuatro modos de superficie (Persuadir, Operar, Leer, Experimentar), la estructura de
contexto de diseño y la lista de anti-patrones se inspiran en **Impeccable** de Paul Bakaus
(<https://github.com/pbakaus/impeccable>, licencia Apache 2.0, que a su vez parte de la skill
`frontend-design` de Anthropic). Están reescritos con palabras propias y resumidos; no se
incluye código ni texto literal de ese proyecto.

## Otros
Las cifras de curvas y duraciones son valores técnicos de uso común. Si detectas una
atribución que falta o es incorrecta, abre un issue o corrígela en este archivo.
