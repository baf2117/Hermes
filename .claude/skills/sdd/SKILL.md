---
name: sdd
description: Spec-Driven Development del proyecto. Úsala al redactar, revisar o cambiar specs, planes y tareas, o al implementar y validar una tarea (docs/constitution.md, specs/).
---

# Spec-Driven Development (SDD)

## Flujo
Constitución → Spec → Clarificación → Plan → Tareas → Implementación → Validación →
Commit → Integración. Un cambio de requisitos (Cambio) reabre el flujo desde la spec.
- Nunca pases a la siguiente fase sin la aprobación explícita del usuario.
- La spec manda: si algo no está en la spec, no se implementa. Si falta una decisión,
  para y pregunta.
- Un cambio de requisitos se hace primero en la spec, luego en el plan y las tareas, y
  por último en el código.
- En el plan y en la validación, comprueba que nada viola `docs/constitution.md`. Si algo
  la viola, dilo antes de seguir.
- Solo el usuario marca la spec como `aprobada`. `implementada` se marca tras la
  validación con veredicto positivo y la confirmación del usuario.
- Cada spec vive en su carpeta: `specs/NNN-nombre/` (NNN = siguiente número libre de tres
  dígitos: 001, 002…) con `spec.md`, `plan.md` y `tasks.md` (y `clarify.md` tras la
  clarificación).
- Al terminar una spec, o ante una decisión importante, actualiza `MEMORY.md`.
- El commit de una spec solo se hace con ella `implementada` (o por lote u ola, en el modo
  continuo) y con la confirmación explícita del usuario sobre el mensaje y los archivos,
  salvo que el usuario haya consentido, para esa spec, los commits de lote y de ola sin
  confirmación o la integración con puertas. La integración de la rama de la spec es solo
  con fast-forward y con el sí del usuario. El push lo hace siempre el usuario.
- El comando de tests y la verificación de interfaz del proyecto están en `CLAUDE.md`
  (secciones "Comandos" y "Verificación"). Léelos de ahí; no los supongas.

## Comandos por fase
| Fase | Comando |
|---|---|
| Constitución | `/sdd-constitution` |
| Spec | `/sdd-spec` |
| Clarificación | `/sdd-clarify` |
| Plan | `/sdd-plan` |
| Tareas | `/sdd-tasks` |
| Implementación | `/sdd-implement` |
| Validación | `/sdd-validate` |
| Cambio | `/sdd-change` |
| Dónde estamos | `/sdd-status` |

## Coordinación con agentes
El flujo completo lo lleva el agente `sdd-coordinator`
(`claude --agent sdd-coordinator`): spec, clarificación en bucle, plan, tareas,
implementación, validación, commit e integración, y te pregunta lo que hay que decidir. Los agentes `planner`,
`reviewer` e `implementer` hacen el trabajo, y el `brancher` crea la rama de la spec. Si el
cambio es pequeño y no merece una spec, usa `/features`. Los comandos `/sdd-*` sirven para
repetir una fase a mano.
0. **Rama**: al confirmar la carpeta de la spec, si estás en la rama principal con el árbol
   limpio, el coordinador te propone `spec/NNN-nombre` y, solo con tu sí, el `brancher` la
   crea. Si ya estás en una rama de spec, no pregunta.
1. **Spec**: el `planner` la redacta. Si devuelve preguntas, el coordinador te las hace una
   a una y se las devuelve.
2. **Clarificación (bucle)**: el `reviewer` detecta, el `planner` guarda las detecciones en
   `clarify.md`, el coordinador te las presenta como decisiones y el `planner` las aplica. Se
   repite hasta que el usuario diga basta.
3. **Aprobación de la spec**: solo el usuario; el `planner` la marca `aprobada`.
4. **Plan**: el `planner` redacta plan.md. Para hasta que el usuario lo apruebe.
5. **Tareas**: el `planner` redacta tasks.md. Para hasta que el usuario lo apruebe.
6. **Implementación**: el usuario elige el modo (tarea por tarea o continuo). El
   coordinador llama al `implementer` UNA vez por tarea, en orden. Tras cada una comprueba
   que sus tests o su verificación de interfaz están en verde; si no, para y avisa. Tras
   cada tarea muestra una línea de formato fijo con la barra de progreso calculada desde
   `tasks.md` (`T3 ✓ <resumen> · [███░░░░░░░] 3/10 tareas (30%)`). El proyecto la muestra
   además en la línea de estado de Claude Code (`.claude/scripts/sdd-progress.js`).
7. **Validación**: el `reviewer` valida la spec RF por RF.
8. **Correcciones**: si dice CAMBIOS NECESARIOS, vuelve al `implementer` con la lista exacta
   y después otra vez al `reviewer`. Máximo 2 vueltas; si sigue fallando, para y explica al
   usuario qué ocurre.
9. **Implementada**: con VEREDICTO: APROBADO y la confirmación del usuario, el `planner`
   marca la spec como `implementada`.
10. **Commit**: con la spec `implementada`, el `planner` actualiza `MEMORY.md` (modo
    cierre, con la aprobación del usuario) y el coordinador propone el mensaje y la lista de
    archivos, y hace el commit local solo con el sí explícito del usuario. El push lo
    hace el usuario.
11. **Integración**: con la spec `implementada` y el commit hecho, el coordinador propone
    integrar la rama de la spec con fast-forward y borrarla, solo con el sí del usuario.
    Si la rama principal avanzó, para: el rebase o el merge lo decide el usuario. El push
    sigue siendo del usuario.
12. **Cierre**: resume lo hecho, el veredicto del `reviewer`, el commit, la integración y
    lo pendiente.

Un cambio de requisitos sigue el mismo camino: el `planner` actualiza spec.md y enseñas
el diff; con la aprobación se actualizan plan.md y tasks.md, y después se implementa.

### Pasar contexto a los agentes
Los agentes NO ven la conversación. En cada llamada pásales: la fase y qué se espera, la
petición original con las palabras del usuario y sus decisiones, las rutas de los archivos
que deben leer y el resultado de la fase anterior.

### Reglas de la coordinación
- No resuelvas tú las dudas de la spec: pregunta al usuario.
- Informa en una línea al empezar cada fase.
- Tras usar el `planner`, revisa `git status`: solo debe haber cambios en specs/ (y en
  `MEMORY.md`, únicamente en el modo cierre). Tras el
  `implementer`, solo en el código del proyecto y en specs/ (tasks.md); nunca en `.claude/`
  ni en `docs/constitution.md`.

## Plantilla de spec (spec.md)
```
# Spec NNN — <Nombre>
Estado: borrador | aprobada | implementada
## Contexto y objetivo
## Usuarios
## Historias de usuario
- HU-1. Como <rol>, quiero <acción> para <beneficio>.
## Definiciones (solo si hay términos que puedan interpretarse de varias formas)
## Requisitos funcionales
## Requisitos no funcionales
## Datos personales y privacidad (obligatoria si toca datos personales)
## Aislamiento entre usuarios o tenants (obligatoria si hay datos de varios usuarios u organizaciones)
## Casos límite
## Fuera de alcance
## Criterios de finalización
## Dudas abiertas
- [NECESITA ACLARACIÓN] <duda>
```
La spec describe el QUÉ y el POR QUÉ. Nada de stack, arquitectura ni nombres de archivos.
Si la spec toca datos personales o de varios usuarios u organizaciones, las secciones
marcadas como obligatorias deben decir qué datos se usan, quién puede verlos y que cada
consulta se limita a lo que corresponde a quien la hace.

## Requisitos en EARS (en español)
- RF-x: CUANDO <evento>, EL SISTEMA <respuesta>.
- RF-x: SI <condición no deseada>, ENTONCES EL SISTEMA <respuesta>.
- RF-x: MIENTRAS <estado>, EL SISTEMA <respuesta>.
- RF-x: EL SISTEMA <comportamiento permanente>.

Cada RF debe ser verificable: nada de "rápido", "seguro" o "fácil de usar" sin un criterio
medible.
Cada RF indica la HU que cubre: `RF-1 (HU-1): CUANDO <evento>, EL SISTEMA <respuesta>.`
Toda HU debe tener al menos un RF, y todo RF debe cubrir una HU.

## Plan (plan.md)
Archivos y responsabilidades · Lógica pura separada de la E/S (base de datos, HTTP) ·
Algoritmo en pseudocódigo · Interfaz · Decisiones justificadas con su alternativa
descartada · Estrategia de tests con el comando de tests del proyecto. Indica qué RF cubre
cada parte.
Si hay interfaz, el apartado "Interfaz" se decide con la skill `sdd-design`
(`.claude/skills/sdd-design/SKILL.md`, que se apoya en `frontend-design`) y respeta
`docs/design.md` y, si existen, los análisis de `docs/references/`. Si `docs/design.md` no
existe aún, el plan define el diseño (modo, paleta, tipografías, espaciado, layout,
movimiento, estados y principios) y la primera tarea de interfaz crea `docs/design.md` a
partir de él.
Si la spec introduce una tecnología nueva, el plan incluye `.gitignore` entre los
archivos a modificar, con los artefactos a ignorar.

## Tareas (tasks.md)
```
- [ ] **Tn. <Descripción>.** RF-x, RF-y
 - Depende de: <Tm, Tk | ninguna>
 - Toca: <rutas de archivos que crea o modifica, separadas por comas>
 - Paralelo: <sí | no>
 - Checkpoint: visual   (opcional, solo en la primera tarea de una pantalla nueva)
 - Hecho cuando: <comprobación verificable>.
```
Cada tarea tiene una sola preocupación y un cambio commiteable, en orden de dependencia,
con un "Hecho cuando:" que se pueda comprobar. Hasta 10 tareas van en una lista
simple. Si salen más, agrúpalas en lotes de máximo 10 (`## Lote A — <nombre>`,
`## Lote B — <nombre>`…): cada lote deja el proyecto en verde por sí solo, y la numeración
Tn sigue corrida entre lotes. Si salen más de 30 tareas, propón dividir la spec.
Al cerrar un lote el coordinador ofrece un commit parcial (modo continuo).

### Mapa de bloqueos
`Depende de` y `Toca` forman el mapa de bloqueos de la spec. Reglas:
- `Depende de` solo nombra tareas anteriores (Tm con m < n), así que no hay ciclos. Una
  tarea que consume algo que otra crea depende de ella, aunque no comparta archivos.
- `Toca` lista rutas concretas, tomadas de "Archivos y responsabilidades" de `plan.md`.
  Los archivos compartidos o generados (lockfiles, configuración global, índices de rutas,
  migraciones, snapshots) llevan la marca `(compartido)`.
- Si dos tareas tocan el mismo archivo, la posterior depende de la anterior. Así, dos
  tareas sin dependencia entre sí nunca comparten archivo.
- Una tarea está lista cuando todas las tareas de su `Depende de` están marcadas `[x]`.
- `Paralelo: no` si la tarea es de interfaz, tiene tests de integración o usa recursos
  compartidos (base de datos, puertos, servidor de desarrollo), toca datos reales, toca
  archivos `(compartido)`, añade una dependencia o tecnología nueva o cambia
  configuración. Ante la duda, `no`. Solo la lógica aislada es `Paralelo: sí`.
- Un `tasks.md` anterior, sin estos campos, se trata como secuencial y no se reescribe.
El mapa sirve para validar el orden, saber qué tareas están listas y definir el alcance de
cada tarea, y es la base de la ejecución paralela.

### Checkpoint visual (interfaz)
Sustituye a la maqueta cuando no hay diseñador. En la primera tarea de cada spec que construya
una pantalla nueva, el `planner` añade `Checkpoint: visual` (y `Paralelo: no`). Al terminarla
y con sus tests en verde, el `implementer` captura la pantalla con Playwright a 375×812 y a
1280×800, en claro y en oscuro, con datos ficticios, y las guarda en
`specs/NNN-nombre/checkpoint/Tn-<ancho>-<claro|oscuro>.png` (ignoradas por git). El
coordinador para siempre (también en modo continuo y paralelo), te enseña las rutas y
pregunta si apruebas; sin tu sí no empieza la siguiente tarea de interfaz. Si pides cambios,
el `implementer` los aplica y vuelve a capturar (máximo 2 vueltas).

### Ejecución paralela (por olas)
Es opcional por spec: el coordinador la ofrece solo si hay una ola de 2 o más tareas. Por
defecto la ejecución es secuencial. Una **ola** son tareas listas con `Paralelo: sí`, con
`Toca` disjuntos entre sí y sin archivos `(compartido)`, hasta un máximo de 2
implementers a la vez (o el valor que fije `CLAUDE.md`). Garantías:
1. **Un solo escritor de `tasks.md`.** Los implementers no lo editan; el `planner` marca
   todas las tareas de la ola de una vez, tras integrar y comprobar que los tests están
   en verde.
2. **Aislamiento.** Cada implementer trabaja en su propio worktree (rama efímera) y hace
   commit ahí. Los worktrees nacen del último commit, así que antes de cada ola el árbol
   debe estar limpio (commit parcial, con confirmación salvo consentimiento de la spec).
3. **Ola segura.** El coordinador comprueba, rama por rama, que solo tocó archivos de su
   `Toca` y que sus tests pudieron ejecutarse en el worktree. Si no, descarta la ola y
   repite las tareas en serie.
4. **Integración con puertas (opcional).** Al elegir el modo paralelo, el usuario decide
   quién integra:
   - **"Sí, con puertas":** el coordinador integra una rama por vez, en orden de tarea,
     con `git merge --no-ff --no-commit`; el `reviewer` ejecuta los tests sobre ese
     resultado y solo con VERDE se confirma el merge. Con conflicto o ROJO se aborta el
     merge y se para; nunca lo resuelve él. Al final, el `planner` marca las tareas, se
     hace un commit solo de `tasks.md` y se limpian los worktrees y ramas efímeras sin
     `--force`.
   - **"No, las integro yo":** el coordinador para y te da las ramas y el orden; tú
     integras de una en una, con los tests tras cada merge, y avisas. Después el
     `reviewer` comprueba los tests antes de marcar nada.

### Antes de implementar (preflight)
Antes de lanzar la primera tarea, el coordinador lee la sección "Comandos" de `CLAUDE.md`
y para si el comando de tests está pendiente, sin rellenar o lleva un `cd` que impide
coincidir con los permisos del `reviewer`; comprueba el acceso a Playwright con una
verificación trivial si alguna tarea lo usa; y recuerda los servidores y puertos
necesarios.

## Implementación
Una sola tarea cada vez, y solo si sus dependencias (`Depende de`) están marcadas `[x]`.
Si toca lógica: tests primero (en rojo), después el código y el
comando de tests en verde. Si solo toca la interfaz, verifícala como indica la sección
"Verificación" de `CLAUDE.md`. Después marca la tarea (`- [ ]` → `- [x]` en `tasks.md`) y
para.
