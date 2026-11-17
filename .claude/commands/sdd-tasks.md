---
description: SDD · Divide el plan en tareas pequeñas y verificables
argument-hint: <NNN-nombre>
arguments: [spec]
---
A partir de specs/$spec/spec.md y specs/$spec/plan.md, genera specs/$spec/tasks.md
siguiendo el formato de la skill sdd:
- Tareas pequeñas (una sola preocupación y un cambio commiteable cada una), en orden de
  dependencia.
- Cada una con los RF que cubre y una línea "Hecho cuando:" verificable.
- Formato: `- [ ] **Tn. <Descripción>.** RF-x, RF-y`, con las líneas "Depende de:"
  (tareas anteriores o "ninguna"), "Toca:" (rutas concretas de plan.md; `(compartido)`
  en lockfiles, configuración global, índices de rutas, migraciones y generados),
  "Paralelo:" (sí o no; "no" en interfaz, integración, recursos compartidos y ante la
  duda), "Checkpoint: visual" (opcional: solo en la primera tarea de cada spec que construya
  una pantalla nueva, con "Paralelo: no") y "Hecho cuando:". Si dos tareas tocan el mismo
  archivo, la posterior depende de la anterior.
- Hasta 10 tareas, lista simple. Si salen más, agrúpalas en lotes de máximo 10
  (`## Lote A — <nombre>`), cada uno en verde por sí solo y con la numeración Tn corrida.
  Si salen más de 30, propón dividir la spec.
