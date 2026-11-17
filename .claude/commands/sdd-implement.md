---
description: SDD · Implementa UNA tarea, tests primero
argument-hint: <NNN-nombre> <Tn>
arguments: [spec, task]
---
Implementa SOLO la tarea $task de specs/$spec/tasks.md, siguiendo specs/$spec/plan.md,
CLAUDE.md, docs/constitution.md y la skill sdd.
Antes de empezar, comprueba que el Estado de la spec es "aprobada", que $task existe,
no está hecha y que las tareas de su "Depende de" (si lo tiene) están marcadas `[x]`.
Si no, para y avísame.
1. Si la tarea toca lógica: escribe primero los tests y comprueba que fallan.
2. Escribe el código hasta que pasen.
3. Ejecuta el comando de tests de CLAUDE.md y muéstrame el resultado. Si la tarea solo
   toca la interfaz, verifícala con el MCP de Playwright (vista móvil de
   375 px con browser_resize y modo oscuro con browser_emulate_media).
Si $task tiene `Checkpoint: visual`: captura la pantalla con Playwright (375×812 y 1280×800, en
   claro y en oscuro) en specs/$spec/checkpoint/, muéstrame las rutas y espera mi aprobación.
4. Marca $task como hecha en tasks.md (`- [ ]` → `- [x]`) e indica qué RF cubre.
Si la tarea o el plan son incorrectos o imposibles, para y explícalo: no improvises
otra solución.

Después PÁRATE. No empieces la siguiente tarea. Si era la última, dímelo para
validar con /sdd-validate.
