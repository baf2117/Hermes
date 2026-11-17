---
description: SDD · Dónde estamos - fase actual y siguiente paso de una spec
argument-hint: <NNN-nombre>
arguments: [spec]
disallowed-tools: Edit Write
---
Lee specs/$spec/ (spec.md, clarify.md, plan.md y tasks.md, los que existan) y MEMORY.md.
Dime en pocas líneas:
1. En qué fase del flujo SDD está esta spec y su estado.
2. Tareas hechas y pendientes (x de y), con una barra de progreso
   (`[████░░░░░░] 4/10 tareas (40%)`: cuenta las líneas `- [x]` y `- [ ]` de tasks.md, 10
   casillas, llenas = hechas*10/total hacia abajo; con lotes, el avance de cada uno), y
   cuáles están listas (con sus "Depende de" cumplidas) y cuáles bloqueadas, y por quién.
3. El siguiente paso exacto, con el comando /sdd-* que debo ejecutar.

No modifiques ningún archivo.
