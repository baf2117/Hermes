---
description: SDD · Valida la spec RF por RF (tests + Playwright)
argument-hint: <NNN-nombre>
arguments: [spec]
disallowed-tools: Edit Write
---
Recorre specs/$spec/spec.md requisito por requisito. Para cada RF indica qué test
lo cubre y el resultado de ejecutarlo con el comando de tests de CLAUDE.md.
Los RF de interfaz que no se puedan testear con ese comando, verifícalos con
el MCP de Playwright (incluida la vista móvil de 375 px y el modo oscuro).
Si algún RF no está cubierto o falla, dilo claramente. NO arregles nada todavía.
Después comprueba los criterios de finalización y dame un veredicto:
¿la spec está cumplida?
