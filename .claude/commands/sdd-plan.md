---
description: SDD · Genera el plan técnico de una spec aprobada
argument-hint: <NNN-nombre>
arguments: [spec]
---
Lee docs/constitution.md, CLAUDE.md y specs/$spec/spec.md. Usa la skill sdd.
NO escribas código.
Genera specs/$spec/plan.md con: archivos que se crean o modifican y la
responsabilidad de cada uno, lógica pura separada de la E/S (base de datos,
HTTP), algoritmo en pseudocódigo, cómo se presenta en la interfaz (según la skill
sdd-design, .claude/skills/sdd-design/SKILL.md, y docs/design.md y docs/references/), decisiones
técnicas justificadas (con su alternativa descartada) y estrategia de tests con el
comando de tests de CLAUDE.md.
Si la spec introduce una tecnología nueva, incluye .gitignore entre los archivos a
modificar, con los artefactos a ignorar.
Todo debe respetar la constitución y cubrir todos los RF. Marca qué RF cubre
cada parte. Si la spec trata datos personales o de varios usuarios u organizaciones,
explica cómo se cumplen sus secciones de privacidad y aislamiento.
Si el Estado de la spec no es "aprobada" o tiene dudas abiertas, para y avísame.
