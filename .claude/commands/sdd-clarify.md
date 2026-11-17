---
description: SDD · Revisa la spec como un QA y guarda las detecciones en clarify.md
argument-hint: <NNN-nombre>
arguments: [spec]
disallowed-tools: Edit
---
Revisa specs/$spec/spec.md como si fueras un QA muy profesional. Usa la skill sdd y lee
docs/constitution.md.
Detecta, según estas categorías:
1. Ambigüedades restantes (requisitos que no se pueden verificar).
2. Contradicciones entre requisitos.
3. Casos límite no cubiertos.
4. Conflictos con docs/constitution.md.
5. Historias de usuario sin requisito (HU sin RF) o requisitos sin historia (RF sin HU).
6. Si la spec toca datos personales o de varios usuarios u organizaciones: secciones de
   privacidad y aislamiento vacías o incompletas.

NO propongas soluciones: solo detecta.
Guarda el resultado en specs/$spec/clarify.md, sobrescribiendo el anterior si existe
(cada ejecución es una ronda: si ya había un clarify.md, la nueva es la ronda siguiente;
conserva las detecciones ya cerradas en una sección "## Historial").
Es lo único que puedes escribir: no modifiques spec.md ni ningún otro archivo.

Formato de clarify.md: un título "# Clarificación — Spec NNN (ronda N)", una línea con el
Estado de la spec y el total de detecciones por severidad, y una sección por detección:

## C-01 · <título corto>
- Categoría: <1 a 6>
- Severidad: Alta | Media | Baja
- Dónde: <RF-x, HU-x o sección>
- Detección: <qué falla, en 1-3 frases, sin solución>
- Estado: abierta

Severidad: Alta si impide verificar un RF, contradice la constitución o contradice una
decisión ya tomada; Media si deja un caso sin definir; Baja si es redacción o detalle
menor. Ordénalas de mayor a menor severidad.

Al terminar, muestra en pantalla solo un resumen (no la lista completa). Para decidir qué
hacer con cada detección y aplicarlo en la spec, usa el agente `sdd-coordinator` o
/sdd-change $spec.
